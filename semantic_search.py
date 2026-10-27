"""Backward-compatible imports for semantic retrieval."""

from app.rag.semantic import (
    KNOWLEDGE_DIR,
    MODEL_NAME,
    build_embeddings,
    load_documents,
    main,
    search_knowledge,
)

__all__ = [
    "KNOWLEDGE_DIR",
    "MODEL_NAME",
    "build_embeddings",
    "load_documents",
    "main",
    "search_knowledge",
]


if __name__ == "__main__":
    main()
