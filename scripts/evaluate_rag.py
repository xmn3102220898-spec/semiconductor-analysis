"""Evaluate the production RAG pipeline against the fixed 50-question set.

相关性判定有两套口径，同一份报告里都会给出：

* strict（门禁口径）：命中 `sources` 中的文档，且 `section` 落在
  `expected_sections` 里。金标是段落级的，同文档其它段落不算命中。
* legacy（历史口径）：命中 `sources`，参数类型一致，且正文出现某个关键词。
  这套口径在语料很小时容易得到结构性满分，保留它只用于对比，不作为门禁。
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.config import settings  # noqa: E402
from app.rag.embeddings import DeterministicHashEmbedder  # noqa: E402
from app.rag.pipeline import (  # noqa: E402
    create_knowledge_pipeline,
    get_knowledge_pipeline,
)

NEGATIVE_QUESTIONS = [
    "月球天气预报和潮汐时间",
    "今天股票市场的价格走势",
    "推荐一道川菜菜谱",
    "昨晚足球比赛的比分",
    "周末旅行机票和酒店",
]


def _is_relevant(hit: dict[str, Any], case: dict[str, Any]) -> bool:
    """段落级金标：文档对得上，且 section 落在标注集合里。"""

    if hit["source"] not in case["sources"]:
        return False
    expected_sections = case.get("expected_sections")
    if expected_sections:
        return hit["section"] in expected_sections
    return _is_relevant_legacy(hit, case)


def _is_relevant_legacy(hit: dict[str, Any], case: dict[str, Any]) -> bool:
    """历史口径：文档 + 参数类型 + 关键词子串。仅用于对比，不作门禁。"""

    if hit["source"] not in case["sources"]:
        return False
    expected_parameter = case.get("parameter_type")
    if (
        expected_parameter
        and expected_parameter != "general"
        and hit["parameter_type"] != expected_parameter
    ):
        return False

    haystack = f"{hit['title']} {hit['section']} {hit['content']}"
    keywords = case.get("keywords") or []
    return any(keyword in haystack for keyword in keywords)


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = round((len(ordered) - 1) * percentile)
    return ordered[index]


def evaluate(
    cases_path: Path,
    top_k: int,
    fail_under: float,
    pipeline=None,
) -> dict[str, Any]:
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    pipeline = pipeline or get_knowledge_pipeline()

    # Exclude one-time model/index startup from retrieval latency.
    pipeline.search("温度异常排查", top_k=top_k)

    results: list[dict[str, Any]] = []
    latencies: list[float] = []
    category_ranks: dict[str, list[int | None]] = defaultdict(list)

    for case in cases:
        started = time.perf_counter()
        retrieval = pipeline.search(case["question"], top_k=top_k)
        latency_ms = (time.perf_counter() - started) * 1000
        latencies.append(latency_ms)

        first_rank = None
        legacy_rank = None
        for rank, hit in enumerate(retrieval["hits"], start=1):
            if first_rank is None and _is_relevant(hit, case):
                first_rank = rank
            if legacy_rank is None and _is_relevant_legacy(hit, case):
                legacy_rank = rank

        category_ranks[case["category"]].append(first_rank)
        results.append({
            "id": case["id"],
            "category": case["category"],
            "question": case["question"],
            "first_relevant_rank": first_rank,
            "legacy_first_relevant_rank": legacy_rank,
            "no_match": retrieval["no_match"],
            "top_hits": [
                {
                    "chunk_id": hit["chunk_id"],
                    "source": hit["source"],
                    "section": hit["section"],
                    "parameter_type": hit["parameter_type"],
                    "score": hit["score"],
                }
                for hit in retrieval["hits"]
            ],
        })

    total = len(results)

    def recall_at(rank_key: str, k: int) -> float:
        hits = sum(
            1
            for item in results
            if item[rank_key] is not None and item[rank_key] <= k
        )
        return round(hits / total, 4)

    def mean_reciprocal_rank(rank_key: str) -> float:
        return round(
            sum(
                1 / item[rank_key]
                for item in results
                if item[rank_key] is not None
            )
            / total,
            4,
        )

    metrics = {f"recall@{k}": recall_at("first_relevant_rank", k) for k in (1, 3, 5)}
    metrics["mrr"] = mean_reciprocal_rank("first_relevant_rank")
    metrics.update(
        {f"legacy_recall@{k}": recall_at("legacy_first_relevant_rank", k) for k in (1, 3, 5)}
    )
    metrics["legacy_mrr"] = mean_reciprocal_rank("legacy_first_relevant_rank")
    metrics["no_match_rate"] = round(
        sum(1 for item in results if item["no_match"]) / total,
        4,
    )
    metrics["latency_p50_ms"] = round(statistics.median(latencies), 3)
    metrics["latency_p95_ms"] = round(
        _percentile(latencies, 0.95),
        3,
    )
    negative_matches = [
        pipeline.search(question, top_k=top_k)["no_match"]
        for question in NEGATIVE_QUESTIONS
    ]
    metrics["negative_no_match_rate"] = round(
        sum(negative_matches) / len(negative_matches),
        4,
    )
    category_recall = {
        category: round(
            sum(
                1
                for rank in ranks
                if rank is not None and rank <= 3
            )
            / len(ranks),
            4,
        )
        for category, ranks in sorted(category_ranks.items())
    }

    status = pipeline.status()
    report = {
        "dataset": str(cases_path.relative_to(PROJECT_ROOT)),
        "case_count": total,
        "top_k": top_k,
        "relevance_rule": (
            "strict: source in case.sources AND section in "
            "case.expected_sections; legacy: source + parameter_type + "
            "keyword substring (comparison only)"
        ),
        "corpus": {
            "documents": len(list((PROJECT_ROOT / "knowledge_base").glob("*.txt"))),
            "chunks": len(pipeline.index.chunks),
        },
        "embedding_model": pipeline.index.embedder.model_name,
        "strategy": "hybrid_vector_bm25",
        "negative_questions": NEGATIVE_QUESTIONS,
        "metrics": metrics,
        "category_recall@3": category_recall,
        "index_status": status,
        "results": results,
    }
    output_path = PROJECT_ROOT / "output" / "rag_evaluation.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"cases={total} top_k={top_k}")
    for key, value in metrics.items():
        print(f"{key:16s} {value}")
    print("category_recall@3")
    for category, value in category_recall.items():
        print(f"  {category:14s} {value:.4f}")
    print(f"report={output_path}")

    if metrics["recall@3"] < fail_under:
        print(
            f"RAG gate failed: recall@3 {metrics['recall@3']:.4f} "
            f"< {fail_under:.4f}"
        )
        return {"report": report, "passed": False}
    if metrics["negative_no_match_rate"] < 0.8:
        print(
            "RAG gate failed: negative no-match rate "
            f"{metrics['negative_no_match_rate']:.4f} < 0.8000"
        )
        return {"report": report, "passed": False}
    print(
        f"RAG gate passed: recall@3 >= {fail_under:.4f}"
    )
    return {"report": report, "passed": True}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cases",
        type=Path,
        default=PROJECT_ROOT / "evaluations" / "rag_questions.json",
    )
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--fail-under", type=float, default=0.85)
    parser.add_argument(
        "--embedder",
        choices=("semantic", "deterministic"),
        default="semantic",
    )
    args = parser.parse_args()

    if args.embedder == "deterministic":
        with tempfile.TemporaryDirectory() as temp_dir:
            pipeline = create_knowledge_pipeline(
                embedder=DeterministicHashEmbedder(),
                knowledge_dir=settings.knowledge_dir,
                index_dir=Path(temp_dir) / "index",
            )
            outcome = evaluate(
                args.cases,
                args.top_k,
                args.fail_under,
                pipeline,
            )
    else:
        outcome = evaluate(args.cases, args.top_k, args.fail_under)
    return 0 if outcome["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
