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
    def test_dataset_has_thirty_cases_and_five_categories(self) -> None:
        cases = json.loads(
            (
                Path(__file__).parents[1]
                / "evaluations"
                / "rag_questions.json"
            ).read_text(encoding="utf-8")
        )
        categories = {case["category"] for case in cases}

        self.assertEqual(len(cases), 30)
        self.assertEqual(
            categories,
            {
                "temperature",
                "pressure",
                "yield",
                "maintenance",
                "process",
            },
        )
        self.assertTrue(
            _is_relevant(
                {
                    "source": "equipment_alarm.txt",
                    "parameter_type": "temperature",
                    "title": "设备异常排查参考",
                    "section": "温度过高",
                    "content": "检查温度传感器。",
                },
                cases[0],
            )
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
