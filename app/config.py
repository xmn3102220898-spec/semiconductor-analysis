"""Central application configuration.

Paths are resolved from the project root and can be overridden through
environment variables. Secrets are never logged.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(
    os.getenv(
        "APP_BASE_DIR",
        str(Path(__file__).resolve().parents[1]),
    )
).resolve()

load_dotenv(PROJECT_ROOT / ".env", override=False)


def _resolve_path(env_name: str, default: str) -> Path:
    configured = Path(os.getenv(env_name, default)).expanduser()
    if not configured.is_absolute():
        configured = PROJECT_ROOT / configured
    return configured.resolve()


def _float_env(name: str, default: float) -> float:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default

    try:
        return float(raw_value)
    except ValueError as exc:
        raise ValueError(
            f"环境变量 {name} 必须是数字，当前值为 {raw_value!r}"
        ) from exc


@dataclass(frozen=True)
class Settings:
    app_name: str
    version: str
    environment: str
    log_level: str
    project_root: Path
    templates_dir: Path
    data_file: Path
    production_db: Path
    diagnosis_db: Path
    knowledge_dir: Path
    knowledge_index_dir: Path
    output_dir: Path
    rules_file: Path
    request_id_header: str
    temperature_limit: float
    pressure_limit: float
    yield_limit: float
    embedding_model: str
    deepseek_model: str
    deepseek_base_url: str
    llm_temperature: float
    llm_prompt_template: Path
    llm_max_retries: int
    llm_input_cost_per_million: float
    llm_output_cost_per_million: float
    deepseek_api_key: str | None = field(default=None, repr=False)
    rag_top_k: int = 4
    rag_vector_weight: float = 0.65
    rag_keyword_weight: float = 0.35
    rag_chunk_max_chars: int = 480
    rag_chunk_overlap_chars: int = 80


settings = Settings(
    app_name="半导体设备AI诊断系统",
    version="1.3.0",
    environment=os.getenv("APP_ENV", "development"),
    log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
    project_root=PROJECT_ROOT,
    templates_dir=_resolve_path("TEMPLATES_DIR", "templates"),
    data_file=_resolve_path(
        "PRODUCTION_DATA_FILE",
        "data/production_data.csv",
    ),
    production_db=_resolve_path(
        "PRODUCTION_DB_FILE",
        "database/production.db",
    ),
    diagnosis_db=_resolve_path(
        "DIAGNOSIS_DB_FILE",
        "diagnosis_history.db",
    ),
    knowledge_dir=_resolve_path("KNOWLEDGE_DIR", "knowledge_base"),
    knowledge_index_dir=_resolve_path(
        "KNOWLEDGE_INDEX_DIR",
        "data/rag_index",
    ),
    output_dir=_resolve_path("OUTPUT_DIR", "output"),
    rules_file=_resolve_path(
        "ANALYSIS_RULES_FILE",
        "config/analysis_rules.json",
    ),
    request_id_header=os.getenv("REQUEST_ID_HEADER", "X-Request-ID"),
    temperature_limit=_float_env("TEMPERATURE_LIMIT", 100.0),
    pressure_limit=_float_env("PRESSURE_LIMIT", 120.0),
    yield_limit=_float_env("YIELD_LIMIT", 90.0),
    embedding_model=os.getenv(
        "EMBEDDING_MODEL",
        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    ),
    deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
    deepseek_base_url=os.getenv(
        "DEEPSEEK_BASE_URL",
        "https://api.deepseek.com",
    ),
    llm_temperature=_float_env("LLM_TEMPERATURE", 0.2),
    llm_prompt_template=_resolve_path(
        "DIAGNOSIS_PROMPT_TEMPLATE",
        "prompts/equipment_diagnosis.md",
    ),
    llm_max_retries=int(os.getenv("LLM_MAX_RETRIES", "1")),
    llm_input_cost_per_million=_float_env(
        "LLM_INPUT_COST_PER_MILLION",
        0.0,
    ),
    llm_output_cost_per_million=_float_env(
        "LLM_OUTPUT_COST_PER_MILLION",
        0.0,
    ),
    deepseek_api_key=os.getenv("DEEPSEEK_API_KEY"),
    rag_top_k=int(os.getenv("RAG_TOP_K", "4")),
    rag_vector_weight=_float_env("RAG_VECTOR_WEIGHT", 0.65),
    rag_keyword_weight=_float_env("RAG_KEYWORD_WEIGHT", 0.35),
    rag_chunk_max_chars=int(
        os.getenv("RAG_CHUNK_MAX_CHARS", "480")
    ),
    rag_chunk_overlap_chars=int(
        os.getenv("RAG_CHUNK_OVERLAP_CHARS", "80")
    ),
)

