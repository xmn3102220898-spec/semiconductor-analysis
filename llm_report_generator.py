"""Backward-compatible imports for LLM report generation."""

from app.llm.report import build_report_prompt, generate_report

__all__ = ["build_report_prompt", "generate_report"]


if __name__ == "__main__":
    print(generate_report("ETCH-02"))
