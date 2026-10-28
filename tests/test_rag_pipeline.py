from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import numpy as np

from app.rag.chunking import (
    ChunkingConfig,
    load_and_chunk_documents,
)
from app.rag.index import PersistentKnowledgeIndex
from app.rag.pipeline import KnowledgePipeline
from app.rag.retrieval import HybridRetriever
from app.llm.report import _facts_and_retrieval, build_report_prompt
import app.data.history as history
from scripts.evaluate_rag import _is_relevant


TERMS = [
    "温度",
    "压力",
    "良率",
    "传感器",
    "真空",
    "刻蚀",
    "检查",
    "因果",
    "安全",
    "气体",
    "射频",
]


class KeywordEmbedder:
    model_name = "test-keyword-embedder-v1"

    def __init__(self) -> None:
        self.encode_calls = 0

    def encode(self, texts: list[str]) -> np.ndarray:
        self.encode_calls += 1
        vectors = []
        for text in texts:
            vector = np.array(
                [text.count(term) for term in TERMS],
                dtype=np.float32,
            )
            norm = np.linalg.norm(vector)
            vectors.append(vector / norm if norm else vector)
        return np.asarray(vectors, dtype=np.float32)


def write_knowledge(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "temperature.txt").write_text(
        "文档标题：温度排查\n\n"
        "温度异常：检查温度传感器和温控系统。\n\n"
        "温度规则：温度超过阈值时记录异常。\n",
        encoding="utf-8",
    )
    (root / "pressure.txt").write_text(
        "文档标题：压力排查\n\n"
        "压力异常：检查压力控制阀和真空系统。\n",
        encoding="utf-8",
    )
    (root / "yield.txt").write_text(
        "文档标题：良率排查\n\n"
        "良率异常：比较异常批次和正常批次，相关性不等于因果关系。\n",
        encoding="utf-8",
    )


def pipeline_for_dir(
    knowledge: Path,
    index_dir: Path,
) -> KnowledgePipeline:
    embedder = KeywordEmbedder()
    index = PersistentKnowledgeIndex(
        knowledge_dir=knowledge,
        index_dir=index_dir,
        embedder=embedder,
        chunking=ChunkingConfig(max_chars=80, overlap_chars=10),
    )
    retriever = HybridRetriever(
        index,
        embedder,
        vector_weight=0.45,
        keyword_weight=0.55,
        semantic_only_min_score=0.01,
        min_hybrid_score=0.01,
    )
    return KnowledgePipeline(index, retriever)


def build_pipeline(base: Path) -> KnowledgePipeline:
    knowledge = base / "knowledge"
    write_knowledge(knowledge)
    return pipeline_for_dir(knowledge, base / "index")


class ChunkingTests(unittest.TestCase):
    def test_chunks_have_metadata_offsets_and_length_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            write_knowledge(base)
            chunks = load_and_chunk_documents(
                base,
                ChunkingConfig(max_chars=35, overlap_chars=8),
            )

        self.assertGreaterEqual(len(chunks), 4)
        for chunk in chunks:
            self.assertTrue(chunk.chunk_id)
            self.assertLessEqual(len(chunk.content), 35)
            self.assertIn(chunk.parameter_type, {
                "temperature",
                "pressure",
                "yield",
                "general",
            })
            self.assertLess(chunk.start_char, chunk.end_char)


class PersistentIndexTests(unittest.TestCase):
    def test_index_is_reused_without_reembedding_chunks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            knowledge = base / "knowledge"
            index_dir = base / "index"
            write_knowledge(knowledge)

            first_embedder = KeywordEmbedder()
            first_index = PersistentKnowledgeIndex(
                knowledge,
                index_dir,
                first_embedder,
                ChunkingConfig(max_chars=80, overlap_chars=10),
            )
            first_index.ensure_fresh()
            first_count = len(first_index.chunks)

            second_embedder = KeywordEmbedder()
            second_index = PersistentKnowledgeIndex(
                knowledge,
                index_dir,
                second_embedder,
                ChunkingConfig(max_chars=80, overlap_chars=10),
            )
            second_index.ensure_fresh()
            second_status = second_index.status()

        self.assertGreater(first_count, 0)
        self.assertEqual(second_embedder.encode_calls, 0)
        self.assertEqual(len(second_index.chunks), first_count)
        self.assertEqual(
            second_status["chunk_count"],
            first_count,
        )

    def test_index_refreshes_when_source_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            pipeline = build_pipeline(base)
            pipeline.index.ensure_fresh()
            initial_count = len(pipeline.index.chunks)

            (base / "knowledge" / "maintenance.txt").write_text(
                "文档标题：维护\n\n"
                "安全要求：维护设备时遵守规程。\n",
                encoding="utf-8",
            )
            pipeline.index.ensure_fresh()

        self.assertGreater(len(pipeline.index.chunks), initial_count)


class HybridRetrievalTests(unittest.TestCase):
    def test_hybrid_retrieval_and_metadata_filter(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pipeline = build_pipeline(Path(temp_dir))
            temperature = pipeline.search("温度传感器异常怎么检查", top_k=3)
            pressure = pipeline.search(
                "温度检查",
                top_k=3,
                filters={"parameter_type": "pressure"},
            )

        self.assertFalse(temperature["no_match"])
        self.assertEqual(
            temperature["hits"][0]["source"],
            "temperature.txt",
        )
        self.assertTrue(
            all(
                hit["parameter_type"] == "pressure"
                for hit in pressure["hits"]
            )
        )

    def test_unmatched_question_returns_no_match(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pipeline = build_pipeline(Path(temp_dir))
            result = pipeline.search("月球天气和股票价格", top_k=3)

        self.assertTrue(result["no_match"])
        self.assertEqual(result["hits"], [])

    def test_single_incidental_token_does_not_saturate_keyword_score(self) -> None:
        """命中一个偶然词不该拿满分，否则负例无法被拒答。

        「推荐一道川菜菜谱」与「下一道工序」只共享一个偶然词；旧实现把
        BM25 最大值归一化，这个片段会拿到 keyword_score=1.0 并进入结果。
        """

        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            knowledge = base / "knowledge"
            knowledge.mkdir(parents=True, exist_ok=True)
            (knowledge / "clean.txt").write_text(
                "文档标题：清洗流程\n\n"
                "残留与后续影响：清洗不彻底会在下一道工序表现为颗粒超标。\n",
                encoding="utf-8",
            )
            embedder = KeywordEmbedder()
            index = PersistentKnowledgeIndex(
                knowledge_dir=knowledge,
                index_dir=base / "index",
                embedder=embedder,
                chunking=ChunkingConfig(max_chars=200, overlap_chars=0),
            )
            pipeline = KnowledgePipeline(
                index,
                HybridRetriever(index, embedder),
            )
            off_topic = pipeline.search("推荐一道川菜菜谱", top_k=3)
            on_topic = pipeline.search("清洗不彻底会有什么影响", top_k=3)

        self.assertTrue(off_topic["no_match"])
        self.assertEqual(off_topic["hits"], [])
        self.assertFalse(on_topic["no_match"])

    def test_equipment_filter_excludes_other_equipment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            knowledge = base / "knowledge"
            knowledge.mkdir(parents=True)
            (knowledge / "etch_doc.txt").write_text(
                "文档标题：刻蚀温度\n\n"
                "刻蚀设备温度异常时检查温度传感器。\n",
                encoding="utf-8",
            )
            (knowledge / "cmp_doc.txt").write_text(
                "文档标题：CMP 温度\n\n"
                "CMP 抛光设备温度异常时检查抛光盘温度。\n",
                encoding="utf-8",
            )
            pipeline = pipeline_for_dir(knowledge, base / "index")

            filtered = pipeline.search(
                "温度异常怎么检查",
                top_k=5,
                filters={"equipment_type": ["etch", "general"]},
            )
            unfiltered = pipeline.search("温度异常怎么检查", top_k=5)

        self.assertIn(
            "cmp_doc.txt",
            {hit["source"] for hit in unfiltered["hits"]},
        )
        self.assertTrue(filtered["hits"])
        self.assertNotIn(
            "cmp_doc.txt",
            {hit["source"] for hit in filtered["hits"]},
        )


class IndexFreshnessTests(unittest.TestCase):
    def test_unchanged_corpus_never_rehashes_files(self) -> None:
        import app.rag.index as index_module

        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            pipeline = build_pipeline(base)
            pipeline.index.ensure_fresh()

            with patch.object(
                index_module,
                "_file_hashes",
                side_effect=AssertionError("热路径不应重算哈希"),
            ):
                pipeline.index.ensure_fresh()
                pipeline.index.ensure_fresh()

    def test_manifest_records_signature_and_detects_rewrite(self) -> None:
        import os

        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            pipeline = build_pipeline(base)
            pipeline.index.ensure_fresh()
            manifest = json.loads(
                (
                    base / "index" / "manifest.json"
                ).read_text(encoding="utf-8")
            )
            self.assertIn("source_signature", manifest)

            target = base / "knowledge" / "temperature.txt"
            target.write_text(
                "文档标题：温度排查\n\n"
                "温度异常：检查温度传感器和温控系统。\n",
                encoding="utf-8",
            )
            os.utime(target, (2_000_000_000, 2_000_000_000))
            pipeline.index.ensure_fresh()

            self.assertEqual(
                json.loads(
                    (
                        base / "index" / "manifest.json"
                    ).read_text(encoding="utf-8")
                )["source_signature"]["temperature.txt"][0],
                2_000_000_000_000_000_000,
            )


class EvaluationDatasetTests(unittest.TestCase):
    """评估集不只是数字，金标必须能在真实索引里落到具体段落。"""

    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).parents[1]
        cls.cases = json.loads(
            (root / "evaluations" / "rag_questions.json").read_text(
                encoding="utf-8"
            )
        )
        cls.available = {
            (chunk.source, chunk.section)
            for chunk in load_and_chunk_documents(
                root / "knowledge_base",
                ChunkingConfig(),
            )
        }

    def test_dataset_has_fifty_cases_and_seven_categories(self) -> None:
        categories = {case["category"] for case in self.cases}

        self.assertEqual(len(self.cases), 50)
        self.assertEqual(
            categories,
            {
                "temperature",
                "pressure",
                "yield",
                "equipment",
                "paraphrase",
                "distractor",
                "multi_hop",
            },
        )

    def test_case_ids_are_unique(self) -> None:
        ids = [case["id"] for case in self.cases]

        self.assertEqual(len(ids), len(set(ids)))

    def test_every_gold_section_exists_in_index(self) -> None:
        # 每个金标段落至少要能在该题列出的某个文档里找到，
        # 否则题目永远不可能命中。
        missing = [
            (case["id"], section)
            for case in self.cases
            for section in case["expected_sections"]
            if not any(
                (source, section) in self.available
                for source in case["sources"]
            )
        ]

        self.assertEqual(missing, [])

    def test_relevance_requires_gold_section_not_just_source(self) -> None:
        case = next(item for item in self.cases if item["id"] == "e01")
        base_hit = {
            "source": case["sources"][0],
            "parameter_type": "general",
            "title": "刻蚀终点检测与过刻控制",
            "content": "终点信号长时间不出现拐点。",
        }

        self.assertTrue(
            _is_relevant(
                {**base_hit, "section": case["expected_sections"][0]},
                case,
            )
        )
        # 同一文档的其它段落不算命中，这是 strict 口径与旧口径的关键差别
        self.assertFalse(
            _is_relevant({**base_hit, "section": "边界与限制"}, case)
        )


class ReportIntegrationTests(unittest.TestCase):
    def test_prompt_contains_retrieved_chunk_id(self) -> None:
        hit = {
            "chunk_id": "chunk-abc",
            "source": "equipment_alarm.txt",
            "section": "温度过高",
            "content": "检查温度传感器。",
            "parameter_type": "temperature",
            "equipment_type": "general",
            "score": 0.9,
        }
        fake_pipeline = type(
            "FakePipeline",
            (),
            {
                "search": lambda self, question, top_k, filters=None: {
                    "hits": [hit],
                    "no_match": False,
                },
                "build_context": lambda self, hits: (
                    "[chunk_id=chunk-abc] 检查温度传感器。"
                ),
            },
        )()

        with patch(
            "app.llm.report.get_knowledge_pipeline",
            return_value=fake_pipeline,
        ):
            prompt = build_report_prompt("ETCH-02")

        self.assertIn("chunk_id=chunk-abc", prompt)
        self.assertIn("每条 finding 至少引用一个真实 `chunk_id`", prompt)

    def test_report_search_uses_equipment_filter(self) -> None:
        hit = {
            "chunk_id": "chunk-abc",
            "source": "etch_doc.txt",
            "section": "温度过高",
            "content": "检查温度传感器。",
            "parameter_type": "temperature",
            "equipment_type": "etch",
            "score": 0.9,
        }
        captured: dict[str, object] = {}

        def search(self, question, top_k, filters=None):
            captured["filters"] = filters
            return {
                "question": question,
                "strategy": "hybrid_vector_bm25",
                "hits": [hit],
                "no_match": False,
                "filters": filters or {},
                "score_distribution": [0.9],
            }

        fake_pipeline = type(
            "FakePipeline",
            (),
            {
                "search": search,
                "build_context": lambda self, hits: "[chunk_id=chunk-abc] x",
            },
        )()

        with patch(
            "app.llm.report.get_knowledge_pipeline",
            return_value=fake_pipeline,
        ):
            build_report_prompt("ETCH-02")

        self.assertEqual(
            captured["filters"],
            {"equipment_type": ["etch", "general"]},
        )

    def test_report_relaxes_filter_when_nothing_matches(self) -> None:
        hit = {
            "chunk_id": "chunk-relaxed",
            "source": "process_rules.txt",
            "section": "规则",
            "content": "温度超过阈值记录异常。",
            "parameter_type": "temperature",
            "equipment_type": "general",
            "score": 0.4,
        }
        calls: list[object] = []

        def search(self, question, top_k, filters=None):
            calls.append(filters)
            if filters:
                return {
                    "question": question,
                    "strategy": "hybrid_vector_bm25",
                    "hits": [],
                    "no_match": True,
                    "filters": filters,
                    "score_distribution": [],
                }
            return {
                "question": question,
                "strategy": "hybrid_vector_bm25",
                "hits": [hit],
                "no_match": False,
                "filters": {},
                "score_distribution": [0.4],
            }

        fake_pipeline = type(
            "FakePipeline",
            (),
            {
                "search": search,
                "build_context": lambda self, hits: "[chunk_id=chunk-relaxed] x",
            },
        )()

        with patch(
            "app.llm.report.get_knowledge_pipeline",
            return_value=fake_pipeline,
        ):
            _, retrieval, contexts = _facts_and_retrieval("ETCH-02")

        self.assertEqual(len(calls), 2)
        self.assertTrue(retrieval["filters_relaxed"])
        self.assertIn("chunk_id=chunk-relaxed", contexts)

    def test_diagnosis_history_migrates_and_persists_references(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_file = Path(temp_dir) / "diagnosis.db"
            with closing(sqlite3.connect(database_file)) as conn:
                conn.execute(
                    """
                    CREATE TABLE diagnosis_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        equipment TEXT,
                        health_score INTEGER,
                        risk_level TEXT,
                        report_text TEXT,
                        create_time TEXT
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO diagnosis_history (
                        equipment, health_score, risk_level,
                        report_text, create_time
                    ) VALUES ('ETCH-X', 80, '正常', 'legacy', '2026-01-01')
                    """
                )
                conn.commit()

            with patch.object(history, "DB_NAME", database_file):
                history.init_database()
                history.save_diagnosis(
                    "ETCH-X",
                    45,
                    "高风险",
                    "report",
                    references=[
                        {
                            "chunk_id": "chunk-1",
                            "source": "manual.txt",
                            "section": "规则",
                            "score": 0.9,
                        }
                    ],
                    report_json={
                        "equipment_id": "ETCH-X",
                        "health_score": 45,
                    },
                    provider="rules_fallback",
                    fallback=True,
                )
                with closing(sqlite3.connect(database_file)) as conn:
                    columns = {
                        row[1]
                        for row in conn.execute(
                            "PRAGMA table_info(diagnosis_history)"
                        )
                    }
                    detail = history.get_diagnosis_detail(2)

        self.assertIn("references_json", columns)
        self.assertEqual(
            detail["references"][0]["chunk_id"],
            "chunk-1",
        )
        self.assertEqual(
            detail["report_json"]["health_score"],
            45,
        )
        self.assertEqual(detail["provider"], "rules_fallback")
        self.assertTrue(detail["fallback"])


if __name__ == "__main__":
    unittest.main()
