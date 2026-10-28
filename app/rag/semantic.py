"""Compatibility facade for the unified knowledge pipeline."""

from __future__ import annotations

from typing import Any

import numpy as np

from app.config import settings
from app.rag.chunking import ChunkingConfig, load_and_chunk_documents
from app.rag.pipeline import get_knowledge_pipeline


MODEL_NAME = settings.embedding_model
KNOWLEDGE_DIR = settings.knowledge_dir


def load_documents() -> list[dict[str, Any]]:
    chunks = load_and_chunk_documents(
        settings.knowledge_dir,
        ChunkingConfig(
            max_chars=settings.rag_chunk_max_chars,
            overlap_chars=settings.rag_chunk_overlap_chars,
        ),
    )
    return [chunk.as_dict() for chunk in chunks]


def build_embeddings(documents: list[dict[str, Any]], model) -> np.ndarray:
    texts = [
        f"{item.get('title', '')} {item.get('section', '')} "
        f"{item['content']}"
        for item in documents
    ]
    return np.asarray(
        model.encode(texts, normalize_embeddings=True),
        dtype=np.float32,
    )


def search_knowledge(
    question: str,
    documents=None,
    embeddings=None,
    model=None,
    top_k: int = 3,
) -> list[dict[str, Any]]:
    result = get_knowledge_pipeline().search(question, top_k=top_k)
    return result["hits"]


def main() -> None:
    while True:
        question = input("\n请输入问题（输入 q 退出）：").strip()
        if question.lower() == "q":
            break
        if not question:
            continue
        result = get_knowledge_pipeline().search(question, top_k=3)
        for number, hit in enumerate(result["hits"], start=1):
            print(
                f"\n结果 {number} | score={hit['score']:.4f} "
                f"| {hit['source']} / {hit['section']}"
            )
            print(hit["content"])
        if not result["hits"]:
            print("没有匹配的知识片段。")


if __name__ == "__main__":
    main()
