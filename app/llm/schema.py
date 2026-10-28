"""Strict diagnostic-report schema and fact consistency validation."""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError


BATCH_ID_PATTERN = re.compile(
    r"\b(?:BATCH|LOT|WAFER)-[A-Z0-9_-]+\b"
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReportFinding(StrictModel):
    category: Literal[
        "temperature",
        "pressure",
        "yield",
        "maintenance",
        "process",
    ]
    summary: str = Field(min_length=4, max_length=600)
    batch_ids: list[str] = Field(default_factory=list)
    chunk_ids: list[str] = Field(default_factory=list)


class RecommendedCheck(StrictModel):
    action: str = Field(min_length=4, max_length=600)
    priority: Literal["high", "medium", "low"]
    batch_ids: list[str] = Field(default_factory=list)
    chunk_ids: list[str] = Field(default_factory=list)


class DiagnosticReportOutput(StrictModel):
    equipment_id: str
    health_score: int = Field(ge=0, le=100)
    risk_level: Literal["正常", "关注", "高风险"]
    simulated_data: Literal[True]
    summary: str = Field(min_length=4, max_length=1000)
    findings: list[ReportFinding] = Field(min_length=1)
    recommended_checks: list[RecommendedCheck] = Field(min_length=1)
    limitations: list[str] = Field(min_length=1)


class ReportValidationError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


def extract_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end < start:
        raise ReportValidationError(["模型输出中没有 JSON 对象"])

    try:
        payload = json.loads(cleaned[start:end + 1])
    except json.JSONDecodeError as exc:
        raise ReportValidationError([
            f"模型输出 JSON 无效：第 {exc.lineno} 行第 {exc.colno} 列"
        ]) from exc
    if not isinstance(payload, dict):
        raise ReportValidationError(["模型输出顶层必须是 JSON 对象"])
    return payload


def _referenced_batch_ids(report: DiagnosticReportOutput) -> set[str]:
    values: list[str] = []
    for finding in report.findings:
        values.extend(finding.batch_ids)
    for check in report.recommended_checks:
        values.extend(check.batch_ids)
    return set(values)


def _referenced_chunk_ids(report: DiagnosticReportOutput) -> set[str]:
    values: list[str] = []
    for finding in report.findings:
        values.extend(finding.chunk_ids)
    for check in report.recommended_checks:
        values.extend(check.chunk_ids)
    return set(values)


def validate_diagnostic_report(
    raw_output: str,
    facts: dict[str, Any],
) -> DiagnosticReportOutput:
    payload = extract_json_object(raw_output)

    try:
        report = DiagnosticReportOutput.model_validate(payload)
    except ValidationError as exc:
        errors = [
            f"{'.'.join(map(str, error['loc']))}: {error['msg']}"
            for error in exc.errors()
        ]
        raise ReportValidationError(errors) from exc

    errors: list[str] = []
    allowed_batches = set(facts["allowed_batch_ids"])
    allowed_chunks = set(facts["allowed_chunk_ids"])

    if report.equipment_id != facts["equipment_id"]:
        errors.append(
            f"equipment_id 不一致：{report.equipment_id}"
        )
    if report.health_score != facts["health_score"]:
        errors.append(
            f"health_score 不一致：{report.health_score}"
        )
    if report.risk_level != facts["risk_level"]:
        errors.append(
            f"risk_level 不一致：{report.risk_level}"
        )
    if not report.simulated_data:
        errors.append("simulated_data 必须为 true")

    unknown_batches = _referenced_batch_ids(report) - allowed_batches
    if unknown_batches:
        errors.append(
            "包含不存在的批次："
            + ", ".join(sorted(unknown_batches))
        )

    unknown_chunks = _referenced_chunk_ids(report) - allowed_chunks
    if unknown_chunks:
        errors.append(
            "包含未检索到的 chunk_id："
            + ", ".join(sorted(unknown_chunks))
        )

    if allowed_chunks:
        for index, finding in enumerate(report.findings):
            if not finding.chunk_ids:
                errors.append(
                    f"findings[{index}] 未引用 chunk_id"
                )

    all_text = json.dumps(
        report.model_dump(),
        ensure_ascii=False,
    )
    text_batch_ids = set(BATCH_ID_PATTERN.findall(all_text))
    unknown_text_batches = text_batch_ids - allowed_batches
    if unknown_text_batches:
        errors.append(
            "正文包含不存在的批次："
            + ", ".join(sorted(unknown_text_batches))
        )

    if errors:
        raise ReportValidationError(errors)
    return report


def report_json_schema() -> dict[str, Any]:
    return DiagnosticReportOutput.model_json_schema()
