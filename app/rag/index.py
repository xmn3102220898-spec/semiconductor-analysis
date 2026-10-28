"""Persistent on-disk knowledge index with file-hash refresh."""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from app.observability import get_logger
from app.rag.chunking import (
    ChunkingConfig,
    KnowledgeChunk,
    load_and_chunk_documents,
)
from app.rag.embeddings import Embedder


INDEX_SCHEMA_VERSION = 2
logger = get_logger(__name__)


def _source_signature(root: Path) -> dict[str, list[int]]:
    """Cheap change detector: (mtime_ns, size) per knowledge file.

    Hashing every document on every query is unnecessary; the signature
    catches the realistic edit paths (editor save, git checkout, file copy)
    at one ``stat`` call per file. Content hashes remain in the manifest as
    the authoritative record, they are just not recomputed on the hot path.
    """
    signature: dict[str, list[int]] = {}
    if not root.exists():
        return signature

    for path in sorted(root.glob("*.txt")):
        stat = path.stat()
        signature[path.relative_to(root).as_posix()] = [
            stat.st_mtime_ns,
            stat.st_size,
        ]
    return signature


def _file_hashes(root: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    if not root.exists():
        return hashes

    for path in sorted(root.glob("*.txt")):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        hashes[path.relative_to(root).as_posix()] = digest
    return hashes


class PersistentKnowledgeIndex:
    def __init__(
        self,
        knowledge_dir: Path,
        index_dir: Path,
        embedder: Embedder,
        chunking: ChunkingConfig | None = None,
    ) -> None:
        self.knowledge_dir = knowledge_dir
        self.index_dir = index_dir
        self.embedder = embedder
        self.chunking = chunking or ChunkingConfig()
        self.chunks_path = index_dir / "chunks.json"
        self.vectors_path = index_dir / "vectors.npy"
        self.manifest_path = index_dir / "manifest.json"
        self._chunks: list[KnowledgeChunk] = []
        self._vectors = np.zeros((0, 0), dtype=np.float32)
        self._manifest: dict[str, Any] = {}
        self._loaded = False
        self._lock = threading.Lock()

    @property
    def chunks(self) -> list[KnowledgeChunk]:
        return self._chunks

    @property
    def vectors(self) -> np.ndarray:
        return self._vectors

    def status(self) -> dict[str, Any]:
        self.ensure_fresh()
        return dict(self._manifest)

    def get_chunk(self, chunk_id: str) -> KnowledgeChunk | None:
        self.ensure_fresh()
        return next(
            (
                chunk
                for chunk in self._chunks
                if chunk.chunk_id == chunk_id
            ),
            None,
        )

    def _expected_manifest(self) -> dict[str, Any]:
        return {
            "schema_version": INDEX_SCHEMA_VERSION,
            "embedding_model": self.embedder.model_name,
            "source_signature": _source_signature(self.knowledge_dir),
            "source_hashes": _file_hashes(self.knowledge_dir),
            "chunk_max_chars": self.chunking.max_chars,
            "chunk_overlap_chars": self.chunking.overlap_chars,
        }

    def _manifest_matches_current_files(self) -> bool:
        """Fast freshness check: stat the corpus, never hash it."""
        if not self._manifest:
            return False

        if (
            self._manifest.get("source_signature")
            != _source_signature(self.knowledge_dir)
        ):
            return False

        expected = {
            "schema_version": INDEX_SCHEMA_VERSION,
            "embedding_model": self.embedder.model_name,
            "chunk_max_chars": self.chunking.max_chars,
            "chunk_overlap_chars": self.chunking.overlap_chars,
        }
        for key, value in expected.items():
            if self._manifest.get(key) != value:
                return False
        return True

    def _load_from_disk(self) -> bool:
        if not (
            self.chunks_path.exists()
            and self.vectors_path.exists()
            and self.manifest_path.exists()
        ):
            return False

        try:
            manifest = json.loads(
                self.manifest_path.read_text(encoding="utf-8")
            )
            chunk_payloads = json.loads(
                self.chunks_path.read_text(encoding="utf-8")
            )
            vectors = np.load(self.vectors_path, allow_pickle=False)
            chunks = [
                KnowledgeChunk.from_dict(payload)
                for payload in chunk_payloads
            ]
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            logger.exception(
                "rag_index_load_failed",
                extra={"event": "rag_index_load_failed"},
            )
            return False

        if vectors.ndim != 2 or len(chunks) != vectors.shape[0]:
            logger.error(
                "rag_index_shape_mismatch",
                extra={
                    "event": "rag_index_shape_mismatch",
                    "chunk_count": len(chunks),
                    "vector_shape": list(vectors.shape),
                },
            )
            return False

        self._manifest = manifest
        self._chunks = chunks
        self._vectors = vectors.astype(np.float32, copy=False)
        self._loaded = True
        return True

    def ensure_fresh(self, force: bool = False) -> None:
        with self._lock:
            if not force and self._loaded:
                if self._manifest_matches_current_files():
                    return

            if not force and self._load_from_disk():
                if self._manifest_matches_current_files():
                    return

            self._build_and_save()

    def _build_and_save(self) -> None:
        started = time.perf_counter()
        chunks = load_and_chunk_documents(
            self.knowledge_dir,
            self.chunking,
        )
        texts = [
            f"{chunk.title} {chunk.section} {chunk.content}"
            for chunk in chunks
        ]
        if texts:
            vectors = self.embedder.encode(texts).astype(
                np.float32,
                copy=False,
            )
        else:
            vectors = np.zeros((0, 0), dtype=np.float32)

        if vectors.ndim != 2 or len(chunks) != vectors.shape[0]:
            raise RuntimeError(
                "向量数量与知识片段数量不一致"
            )

        self.index_dir.mkdir(parents=True, exist_ok=True)
        manifest = {
            **self._expected_manifest(),
            "chunk_count": len(chunks),
            "vector_dimension": (
                int(vectors.shape[1]) if vectors.size else 0
            ),
            "built_at": datetime.now(timezone.utc).isoformat(),
        }

        temp_chunks = self.chunks_path.with_suffix(".json.tmp")
        temp_vectors = self.vectors_path.with_suffix(".npy.tmp")
        temp_manifest = self.manifest_path.with_suffix(".json.tmp")

        temp_chunks.write_text(
            json.dumps(
                [chunk.as_dict() for chunk in chunks],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        with temp_vectors.open("wb") as file:
            np.save(file, vectors, allow_pickle=False)
        temp_manifest.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        os.replace(temp_chunks, self.chunks_path)
        os.replace(temp_vectors, self.vectors_path)
        os.replace(temp_manifest, self.manifest_path)

        self._chunks = chunks
        self._vectors = vectors
        self._manifest = manifest
        self._loaded = True
        logger.info(
            "rag_index_built",
            extra={
                "event": "rag_index_built",
                "chunk_count": len(chunks),
                "vector_dimension": manifest["vector_dimension"],
                "duration_ms": round(
                    (time.perf_counter() - started) * 1000,
                    2,
                ),
            },
        )
