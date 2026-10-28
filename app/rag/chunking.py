"""Semantic-ish document chunking with stable metadata and offsets."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path


SENTENCE_BOUNDARY = re.compile(r"(?<=[。！？；\n])")


@dataclass(frozen=True)
class ChunkingConfig:
    max_chars: int = 480
    overlap_chars: int = 80


@dataclass(frozen=True)
class KnowledgeChunk:
    chunk_id: str
    source: str
    source_path: str
    title: str
    section: str
    content: str
    equipment_type: str
    parameter_type: str
    topic: str
    start_char: int
    end_char: int

    def as_dict(self) -> dict[str, object]:
        return {
            "chunk_id": self.chunk_id,
            "source": self.source,
            "source_path": self.source_path,
            "title": self.title,
            "section": self.section,
            "content": self.content,
            "equipment_type": self.equipment_type,
            "parameter_type": self.parameter_type,
            "topic": self.topic,
            "start_char": self.start_char,
            "end_char": self.end_char,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "KnowledgeChunk":
        return cls(
            chunk_id=str(payload["chunk_id"]),
            source=str(payload["source"]),
            source_path=str(payload["source_path"]),
            title=str(payload["title"]),
            section=str(payload["section"]),
            content=str(payload["content"]),
            equipment_type=str(payload["equipment_type"]),
            parameter_type=str(payload["parameter_type"]),
            topic=str(payload["topic"]),
            start_char=int(payload["start_char"]),
            end_char=int(payload["end_char"]),
        )


def _infer_parameter_type(text: str) -> str:
    if "温度" in text or "温控" in text:
        return "temperature"
    if "压力" in text or "真空" in text:
        return "pressure"
    if "良率" in text:
        return "yield"
    return "general"


EQUIPMENT_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("etch", ("etch", "刻蚀", "蚀刻")),
    ("deposition", ("cvd", "pvd", "沉积", "薄膜", "溅射")),
    ("cmp", ("cmp", "化学机械抛光", "研磨", "抛光")),
    ("litho", ("litho", "光刻", "曝光", "涂胶")),
    ("clean", ("clean", "清洗", "去胶")),
    ("diffusion", ("diffusion", "扩散", "氧化炉", "退火")),
    ("implant", ("implant", "离子注入", "注入机")),
)


def _infer_equipment_type(source: str, text: str) -> str:
    haystack = f"{source} {text}".lower()
    for equipment_type, keywords in EQUIPMENT_KEYWORDS:
        if any(keyword in haystack for keyword in keywords):
            return equipment_type
    return "general"


def _section_name(paragraph: str, fallback: str) -> str:
    first_line = paragraph.splitlines()[0].strip()
    if "：" in first_line and len(first_line.split("：", 1)[0]) <= 20:
        return first_line.split("：", 1)[0]
    return fallback


def _split_long_text(
    text: str,
    config: ChunkingConfig,
) -> list[str]:
    if len(text) <= config.max_chars:
        return [text]

    sentences = [
        item.strip()
        for item in SENTENCE_BOUNDARY.split(text)
        if item.strip()
    ]
    parts: list[str] = []
    current = ""

    for sentence in sentences:
        if len(sentence) > config.max_chars:
            if current:
                parts.append(current)
                current = ""
            step = max(1, config.max_chars - config.overlap_chars)
            for start in range(0, len(sentence), step):
                parts.append(sentence[start:start + config.max_chars])
            continue

        candidate = f"{current}{sentence}"
        if current and len(candidate) > config.max_chars:
            parts.append(current)
            available_overlap = max(
                0,
                config.max_chars - len(sentence),
            )
            overlap_size = min(
                config.overlap_chars,
                available_overlap,
            )
            overlap = (
                current[-overlap_size:]
                if overlap_size
                else ""
            )
            current = f"{overlap}{sentence}"
        else:
            current = candidate

    if current:
        parts.append(current)
    return parts


def chunk_document(
    path: Path,
    knowledge_root: Path,
    config: ChunkingConfig,
) -> list[KnowledgeChunk]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    title = lines[0].split("：", 1)[-1].strip() if lines else path.stem
    relative_path = path.relative_to(knowledge_root).as_posix()
    topic = path.stem
    chunks: list[KnowledgeChunk] = []
    cursor = 0

    paragraphs = [
        paragraph.strip()
        for paragraph in re.split(r"\n\s*\n", text)
        if paragraph.strip()
    ]
    for paragraph_index, paragraph in enumerate(paragraphs):
        start_char = text.find(paragraph, cursor)
        if start_char < 0:
            start_char = cursor
        end_char = start_char + len(paragraph)
        cursor = end_char

        if paragraph_index == 0 and paragraph.startswith("文档标题："):
            continue

        section = _section_name(
            paragraph,
            f"段落 {paragraph_index + 1}",
        )
        parameter_type = _infer_parameter_type(paragraph)
        equipment_type = _infer_equipment_type(relative_path, text)

        for content in _split_long_text(paragraph, config):
            digest = hashlib.sha256(
                f"{relative_path}:{start_char}:{content}".encode("utf-8")
            ).hexdigest()[:20]
            chunks.append(
                KnowledgeChunk(
                    chunk_id=digest,
                    source=path.name,
                    source_path=relative_path,
                    title=title,
                    section=section,
                    content=content,
                    equipment_type=equipment_type,
                    parameter_type=parameter_type,
                    topic=topic,
                    start_char=start_char,
                    end_char=end_char,
                )
            )
    return chunks


def load_and_chunk_documents(
    knowledge_root: Path,
    config: ChunkingConfig | None = None,
) -> list[KnowledgeChunk]:
    chunking_config = config or ChunkingConfig()
    if not knowledge_root.exists():
        return []

    chunks: list[KnowledgeChunk] = []
    for path in sorted(knowledge_root.glob("*.txt")):
        chunks.extend(
            chunk_document(path, knowledge_root, chunking_config)
        )
    return chunks
