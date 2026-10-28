"""Embedding adapters used by the persistent knowledge index."""

from __future__ import annotations

import hashlib
from typing import Protocol

import jieba
import numpy as np

from app.config import settings


class Embedder(Protocol):
    model_name: str

    def encode(self, texts: list[str]) -> np.ndarray:
        ...


class SentenceTransformerEmbedder:
    def __init__(self, model_name: str | None = None) -> None:
        self.model_name = model_name or settings.embedding_model
        self._model = None

    def encode(self, texts: list[str]) -> np.ndarray:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name)

        vectors = self._model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return np.asarray(vectors, dtype=np.float32)


class DeterministicHashEmbedder:
    """Dependency-light embedding used by CI retrieval regression tests."""

    model_name = "deterministic-token-hash-v1"

    def __init__(self, dimension: int = 128) -> None:
        self.dimension = dimension

    def encode(self, texts: list[str]) -> np.ndarray:
        vectors = np.zeros(
            (len(texts), self.dimension),
            dtype=np.float32,
        )
        for row, text in enumerate(texts):
            tokens = [
                token.strip().lower()
                for token in jieba.lcut_for_search(text)
                if token.strip()
            ]
            for token in tokens:
                digest = hashlib.blake2b(
                    token.encode("utf-8"),
                    digest_size=8,
                ).digest()
                bucket = int.from_bytes(digest, "big") % self.dimension
                vectors[row, bucket] += 1.0
            norm = np.linalg.norm(vectors[row])
            if norm:
                vectors[row] /= norm
        return vectors
