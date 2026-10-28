"""Single production RAG pipeline: chunk, index, retrieve, context."""

from __future__ import annotations

from collections.abc import Collection
from functools import lru_cache
from typing import Any

from app.config import settings
from app.rag.chunking import ChunkingConfig
from app.rag.embeddings import (
    Embedder,
    SentenceTransformerEmbedder,
)
from app.rag.index import PersistentKnowledgeIndex
from app.rag.retrieval import HybridRetriever


class KnowledgePipeline:
    def __init__(
        self,
        index: PersistentKnowledgeIndex,
        retriever: HybridRetriever,
    ) -> None:
        self.index = index
        self.retriever = retriever

    def search(
        self,
        question: str,
        top_k: int = 4,
        filters: dict[str, str | Collection[str]] | None = None,
    ) -> dict[str, Any]:
        return self.retriever.search(
            question,
            top_k=top_k,
            filters=filters,
        )

    def status(self) -> dict[str, Any]:
        return self.index.status()

    def get_chunk(self, chunk_id: str) -> dict[str, Any] | None:
        chunk = self.index.get_chunk(chunk_id)
        return chunk.as_dict() if chunk else None

    def refresh(self) -> dict[str, Any]:
        self.index.ensure_fresh(force=True)
        return self.index.status()

    @staticmethod
    def build_context(hits: list[dict[str, Any]]) -> str:
        if not hits:
            return "无匹配知识依据。"
        blocks: list[str] = []
        for hit in hits:
            blocks.append(
                "\n".join(
                    [
                        f"[chunk_id={hit['chunk_id']}]",
                        f"来源：{hit['source']} / {hit['section']}",
                        hit["content"],
                    ]
                )
            )
        return "\n\n".join(blocks)


def create_knowledge_pipeline(
    embedder: Embedder | None = None,
    knowledge_dir=None,
    index_dir=None,
    vector_weight: float | None = None,
    keyword_weight: float | None = None,
) -> KnowledgePipeline:
    embedding = embedder or SentenceTransformerEmbedder()
    chunking = ChunkingConfig(
        max_chars=settings.rag_chunk_max_chars,
        overlap_chars=settings.rag_chunk_overlap_chars,
    )
    index = PersistentKnowledgeIndex(
        knowledge_dir=knowledge_dir or settings.knowledge_dir,
        index_dir=index_dir or settings.knowledge_index_dir,
        embedder=embedding,
        chunking=chunking,
    )
    retriever = HybridRetriever(
        index=index,
        embedder=embedding,
        vector_weight=(
            settings.rag_vector_weight
            if vector_weight is None
            else vector_weight
        ),
        keyword_weight=(
            settings.rag_keyword_weight
            if keyword_weight is None
            else keyword_weight
        ),
    )
    return KnowledgePipeline(index=index, retriever=retriever)


@lru_cache(maxsize=1)
def get_knowledge_pipeline() -> KnowledgePipeline:
    return create_knowledge_pipeline()
