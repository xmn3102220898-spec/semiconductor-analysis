"""Backward-compatible imports for LLM report generation."""

from app.llm.report import (
    build_report_prompt,
    generate_report,
    generate_report_result,
)

__all__ = [
    "build_report_prompt",
    "generate_report",
    "generate_report_result",
]


if __name__ == "__main__":
    print(generate_report("ETCH-02"))
