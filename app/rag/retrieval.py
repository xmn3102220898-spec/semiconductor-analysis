"""Hybrid vector and BM25 retrieval over the persistent chunk index."""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Collection
from typing import Any

import jieba
import numpy as np

from app.rag.chunking import KnowledgeChunk
from app.rag.embeddings import Embedder
from app.rag.index import PersistentKnowledgeIndex


TOKEN_PATTERN = re.compile(r"[\u4e00-\u9fffA-Za-z0-9_]+")
STOPWORDS = {
    "的",
    "了",
    "是",
    "和",
    "与",
    "及",
    "在",
    "对",
    "有",
    "可能",
    "需要",
    "怎么",
    "什么",
    "哪些",
    "如何",
    "应该",
    "是否",
    "一个",
    "进行",
    "时间",
}


def _tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for raw_token in jieba.lcut_for_search(text.lower()):
        token = raw_token.strip()
        if (
            token
            and token not in STOPWORDS
            and (
                len(token) > 1
                or token.isascii()
                or token.isdigit()
            )
            and TOKEN_PATTERN.fullmatch(token)
        ):
            tokens.append(token)
    return tokens


def _matches_filters(
    chunk: KnowledgeChunk,
    filters: dict[str, str | Collection[str]] | None,
) -> bool:
    """Match chunk metadata against filters.

    A filter value may be a single expected string or a collection of
    acceptable values, so a caller can say "etch or通用" without issuing
    two searches and merging the results by hand.
    """
    if not filters:
        return True
    for key, expected in filters.items():
        if not expected:
            continue
        actual = getattr(chunk, key, None)
        if isinstance(expected, str):
            if actual != expected:
                return False
        elif actual not in expected:
            return False
    return True


class HybridRetriever:
    def __init__(
        self,
        index: PersistentKnowledgeIndex,
        embedder: Embedder,
        vector_weight: float = 0.65,
        keyword_weight: float = 0.35,
        semantic_only_min_score: float = 0.5,
        min_hybrid_score: float = 0.12,
        min_keyword_coverage: float = 0.25,
    ) -> None:
        total_weight = vector_weight + keyword_weight
        if total_weight <= 0:
            raise ValueError("检索权重之和必须大于 0")
        self.index = index
        self.embedder = embedder
        self.vector_weight = vector_weight / total_weight
        self.keyword_weight = keyword_weight / total_weight
        self.semantic_only_min_score = semantic_only_min_score
        self.min_hybrid_score = min_hybrid_score
        self.min_keyword_coverage = min_keyword_coverage

    def _keyword_scores(
        self,
        question: str,
        chunks: list[KnowledgeChunk],
    ) -> tuple[np.ndarray, np.ndarray]:
        """Return (BM25 scores, idf-weighted query coverage per chunk).

        覆盖度 = 片段命中的查询词 idf 之和 / 查询词 idf 之和。它是尺度无关的：
        语料从 3 篇扩到 20 篇时，绝对 BM25 分会整体变小，但覆盖度不变，
        因此适合做「是否拒答」的判据，而绝对阈值不适合。
        """

        query_tokens = _tokens(question)
        if not query_tokens or not chunks:
            empty = np.zeros(len(chunks), dtype=np.float32)
            return empty, empty.copy()

        documents = [
            _tokens(
                f"{chunk.title} {chunk.section} "
                f"{chunk.content} {chunk.parameter_type} "
                f"{chunk.equipment_type}"
            )
            for chunk in chunks
        ]
        document_frequency: Counter[str] = Counter()
        for document in documents:
            document_frequency.update(set(document))

        average_length = sum(map(len, documents)) / max(len(documents), 1)
        k1 = 1.5
        b = 0.75
        scores = np.zeros(len(chunks), dtype=np.float32)
        coverage = np.zeros(len(chunks), dtype=np.float32)
        corpus_size = len(documents)

        def idf_of(token: str) -> float:
            return math.log(
                1
                + (corpus_size - document_frequency[token] + 0.5)
                / (document_frequency[token] + 0.5)
            )

        # 未出现在任何片段里的查询词按“最稀有”计权，这样无关问题
        # 的覆盖度不会被大量缺词稀释成高分。
        query_weight = sum(idf_of(token) for token in set(query_tokens))
        unique_query_tokens = list(dict.fromkeys(query_tokens))

        for index, document in enumerate(documents):
            frequencies = Counter(document)
            score = 0.0
            matched_weight = 0.0
            for token in unique_query_tokens:
                frequency = frequencies.get(token, 0)
                if not frequency:
                    continue
                idf = idf_of(token)
                matched_weight += idf
                denominator = frequency + k1 * (
                    1 - b + b * len(document) / max(average_length, 1)
                )
                score += idf * (
                    frequency * (k1 + 1) / denominator
                )
            scores[index] = score
            coverage[index] = (
                matched_weight / query_weight if query_weight else 0.0
            )
        return scores, coverage

    def search(
        self,
        question: str,
        top_k: int = 4,
        filters: dict[str, str | Collection[str]] | None = None,
    ) -> dict[str, Any]:
        self.index.ensure_fresh()
        chunks = self.index.chunks
        vectors = self.index.vectors

        candidate_indexes = [
            index
            for index, chunk in enumerate(chunks)
            if _matches_filters(chunk, filters)
        ]
        if not candidate_indexes or vectors.size == 0:
            return {
                "question": question,
                "strategy": "hybrid_vector_bm25",
                "hits": [],
                "no_match": True,
                "filters": filters or {},
                "score_distribution": [],
            }

        query_vector = self.embedder.encode([question])[0].astype(
            np.float32,
            copy=False,
        )
        candidate_vectors = vectors[candidate_indexes]
        vector_norms = np.linalg.norm(
            candidate_vectors,
            axis=1,
        )
        query_norm = float(np.linalg.norm(query_vector))
        vector_scores = np.divide(
            candidate_vectors @ query_vector,
            vector_norms * query_norm,
            out=np.zeros(len(candidate_indexes), dtype=np.float32),
            where=(vector_norms * query_norm) != 0,
        )
        vector_scores = np.clip(vector_scores, 0, 1)

        candidate_chunks = [chunks[index] for index in candidate_indexes]
        keyword_scores, keyword_coverage = self._keyword_scores(
            question,
            candidate_chunks,
        )
        max_keyword = float(keyword_scores.max()) if len(keyword_scores) else 0
        # 排序仍用最大归一化（保持与历史一致的相对次序），拒答判据改用
        # 覆盖度：命中一个偶然词只能拿到很低的覆盖度，不会被当成满分。
        normalized_keywords = (
            keyword_scores / max_keyword
            if max_keyword > 0
            else keyword_scores
        )
        hybrid_scores = (
            self.vector_weight * vector_scores
            + self.keyword_weight * normalized_keywords
        )

        ranked = sorted(
            range(len(candidate_indexes)),
            key=lambda index: (
                float(hybrid_scores[index]),
                float(vector_scores[index]),
            ),
            reverse=True,
        )
        hits: list[dict[str, Any]] = []
        for candidate_position in ranked:
            if len(hits) >= top_k:
                break
            vector_score = float(vector_scores[candidate_position])
            hybrid_score = float(hybrid_scores[candidate_position])
            coverage = float(keyword_coverage[candidate_position])
            # 关键词覆盖不足时，只有向量相似度足够高才保留（改写问法走这条路）
            if (
                coverage < self.min_keyword_coverage
                and vector_score < self.semantic_only_min_score
            ):
                continue
            if hybrid_score < self.min_hybrid_score:
                continue

            chunk = candidate_chunks[candidate_position]
            hits.append({
                **chunk.as_dict(),
                "vector_score": round(vector_score, 4),
                "keyword_score": round(
                    float(normalized_keywords[candidate_position]),
                    4,
                ),
                "keyword_coverage": round(coverage, 4),
                "score": round(hybrid_score, 4),
            })

        return {
            "question": question,
            "strategy": "hybrid_vector_bm25",
            "hits": hits,
            "no_match": not hits,
            "filters": filters or {},
            "score_distribution": [
                hit["score"] for hit in hits
            ],
            "candidate_count": len(candidate_indexes),
        }
