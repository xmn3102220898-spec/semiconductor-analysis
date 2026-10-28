"""Prompt template rendering without embedding business facts in code."""

from __future__ import annotations

import json
from functools import lru_cache
from string import Template
from typing import Any

from app.config import settings
from app.llm.schema import report_json_schema


@lru_cache(maxsize=1)
def load_prompt_template() -> Template:
    return Template(
        settings.llm_prompt_template.read_text(encoding="utf-8")
    )


def render_prompt(
    facts: dict[str, Any],
    retrieval_context: str,
    validation_feedback: str = "",
) -> str:
    return load_prompt_template().substitute(
        facts_json=json.dumps(
            facts,
            ensure_ascii=False,
            indent=2,
        ),
        contexts=retrieval_context,
        schema_json=json.dumps(
            report_json_schema(),
            ensure_ascii=False,
            indent=2,
        ),
        validation_feedback=(
            validation_feedback or "无。"
        ),
    )
