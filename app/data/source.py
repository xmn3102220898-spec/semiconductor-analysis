"""External CSV/JSON reading, validation, and data-quality reporting."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from app.analysis.rules import (
    RuleConfigurationError,
    ValidationPolicy,
    load_rules,
)
from app.config import settings


BASE_DIR = settings.project_root
DEFAULT_DATA_FILE = settings.data_file
DATA_FILE_ENV = "PRODUCTION_DATA_FILE"
MAX_ERROR_DETAILS = 100

CANONICAL_FIELDS = (
    "batch_id",
    "equipment_id",
    "process",
    "temperature_c",
    "pressure_kpa",
    "yield_pct",
)
TEXT_FIELDS = ("batch_id", "equipment_id", "process")
NUMERIC_FIELDS = ("temperature_c", "pressure_kpa", "yield_pct")

FIELD_ALIASES = {
    "batch_id": {"batch_id", "batch", "批次编号", "批次号"},
    "equipment_id": {
        "equipment_id",
        "equipment",
        "device_id",
        "设备编号",
        "设备号",
    },
    "process": {"process", "工艺", "工序"},
    "temperature_c": {
        "temperature_c",
        "temperature",
        "temp_c",
        "温度",
        "温度_c",
    },
    "pressure_kpa": {
        "pressure_kpa",
        "pressure",
        "压力",
        "压力_kpa",
    },
    "yield_pct": {
        "yield_pct",
        "yield",
        "yield_percent",
        "良率",
        "良率_pct",
    },
    "production_time": {
        "production_time",
        "event_time",
        "生产时间",
        "事件时间",
    },
}


class ProductionDataError(ValueError):
    """Production data is missing, malformed, or fails validation."""


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    field: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "field": self.field,
            "message": self.message,
        }


@dataclass
class ValidationReport:
    source_path: str
    source_format: str
    total_records: int = 0
    valid_records: int = 0
    rejected_records: int = 0
    records: list[dict[str, Any]] = field(default_factory=list)
    file_errors: list[ValidationIssue] = field(default_factory=list)
    record_errors: list[dict[str, Any]] = field(default_factory=list)
    reason_counts: dict[str, int] = field(default_factory=dict)

    @property
    def healthy(self) -> bool:
        return (
            not self.file_errors
            and self.rejected_records == 0
            and self.total_records > 0
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "healthy": self.healthy,
            "source": {
                "name": Path(self.source_path).name,
                "path": self.source_path,
                "format": self.source_format,
            },
            "total_records": self.total_records,
            "valid_records": self.valid_records,
            "rejected_records": self.rejected_records,
            "reason_counts": dict(sorted(self.reason_counts.items())),
            "file_errors": [
                issue.as_dict() for issue in self.file_errors
            ],
            "record_errors": self.record_errors,
            "details_truncated": (
                self.rejected_records > len(self.record_errors)
            ),
        }


def _normalize_key(value: Any) -> str:
    return (
        str(value)
        .strip()
        .lower()
        .replace(" ", "_")
        .replace("-", "_")
    )


ALIAS_LOOKUP = {
    _normalize_key(alias): canonical
    for canonical, aliases in FIELD_ALIASES.items()
    for alias in aliases
}


def _candidate_data_file(path: str | Path | None = None) -> Path:
    configured = Path(path or DEFAULT_DATA_FILE).expanduser()
    if not configured.is_absolute():
        configured = BASE_DIR / configured
    return configured.resolve()


def resolve_data_file(path: str | Path | None = None) -> Path:
    data_file = _candidate_data_file(path)

    if data_file.suffix.lower() not in {".csv", ".json"}:
        raise ProductionDataError(
            f"不支持的数据文件格式：{data_file.suffix or '无扩展名'}；"
            "请使用 CSV 或 JSON。"
        )
    if not data_file.exists():
        raise ProductionDataError(f"找不到生产数据文件：{data_file}")
    if not data_file.is_file():
        raise ProductionDataError(f"生产数据路径不是文件：{data_file}")

    return data_file


def get_file_signature(data_file: str | Path | None = None) -> str:
    file_path = resolve_data_file(data_file)
    digest = hashlib.sha256()
    with file_path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_csv(file_path: Path) -> list[dict[str, Any]]:
    with file_path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        if not reader.fieldnames:
            raise ProductionDataError("CSV 文件没有表头。")
        return [dict(row) for row in reader]


def _read_json(file_path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(file_path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ProductionDataError(
            f"JSON 格式错误：第 {exc.lineno} 行，第 {exc.colno} 列"
        ) from exc

    if isinstance(payload, list):
        records = payload
    elif isinstance(payload, dict):
        records = next(
            (
                payload[key]
                for key in ("records", "data", "items")
                if isinstance(payload.get(key), list)
            ),
            None,
        )
    else:
        records = None

    if records is None and isinstance(payload, dict):
        if all(isinstance(item, dict) for item in payload.values()):
            records = list(payload.values())

    if not isinstance(records, list):
        raise ProductionDataError(
            "JSON 顶层必须是记录数组，或包含 records/data/items 数组的对象。"
        )
    if any(not isinstance(item, dict) for item in records):
        raise ProductionDataError("JSON 记录数组中的每一项都必须是对象。")
    return records


def _issue(code: str, field_name: str, message: str) -> ValidationIssue:
    return ValidationIssue(code, field_name, message)


def _normalize_production_time(value: Any) -> str | None:
    if value is None or str(value).strip() == "":
        return None

    text = str(value).strip()
    for format_string in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            parsed = datetime.strptime(text, format_string)
            return parsed.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    raise ValueError(text)


def _map_record_issues(
    record: dict[str, Any],
    row_number: int,
    policy: ValidationPolicy,
) -> tuple[dict[str, Any] | None, list[ValidationIssue]]:
    normalized_record = {
        _normalize_key(key): value
        for key, value in record.items()
        if key is not None
    }
    mapped: dict[str, Any] = {}
    for source_key, value in normalized_record.items():
        canonical = ALIAS_LOOKUP.get(source_key)
        if canonical and canonical not in mapped:
            mapped[canonical] = value

    issues: list[ValidationIssue] = []
    missing = [field for field in CANONICAL_FIELDS if field not in mapped]
    for field_name in missing:
        issues.append(
            _issue(
                "missing_field",
                field_name,
                f"第 {row_number} 条记录缺少字段 {field_name}",
            )
        )

    result: dict[str, Any] = {}
    for field_name in TEXT_FIELDS:
        if field_name in missing:
            continue
        value = "" if mapped[field_name] is None else str(
            mapped[field_name]
        ).strip()
        if not value:
            issues.append(
                _issue(
                    "empty_value",
                    field_name,
                    f"第 {row_number} 条记录的 {field_name} 不能为空",
                )
            )
        else:
            result[field_name] = value

    if "equipment_id" in result and not policy.equipment_id_pattern.match(
        result["equipment_id"]
    ):
        issues.append(
            _issue(
                "equipment_id_invalid",
                "equipment_id",
                "设备编号必须是大写字母/数字组成的分段编号，例如 ETCH-02",
            )
        )

    if (
        "process" in result
        and policy.allowed_processes
        and result["process"] not in policy.allowed_processes
    ):
        issues.append(
            _issue(
                "process_not_allowed",
                "process",
                f"不支持的工艺类型：{result['process']}",
            )
        )

    range_rules = {
        "temperature_c": (
            policy.temperature_min,
            policy.temperature_max,
            "temperature_out_of_range",
            "温度",
        ),
        "pressure_kpa": (
            policy.pressure_min,
            policy.pressure_max,
            "pressure_out_of_range",
            "压力",
        ),
        "yield_pct": (
            policy.yield_min,
            policy.yield_max,
            "yield_out_of_range",
            "良率",
        ),
    }

    for field_name in NUMERIC_FIELDS:
        if field_name in missing:
            continue
        raw_value = mapped[field_name]
        if raw_value is None or str(raw_value).strip() == "":
            issues.append(
                _issue(
                    "missing_value",
                    field_name,
                    f"第 {row_number} 条记录的 {field_name} 不能为空",
                )
            )
            continue

        numeric_text = str(raw_value).strip().replace(",", "")
        for unit in ("℃", "°C", "kPa", "kpa", "%", " ", "\t", "\u3000"):
            numeric_text = numeric_text.replace(unit, "")
        try:
            numeric_value = float(numeric_text)
        except ValueError:
            issues.append(
                _issue(
                    "invalid_number",
                    field_name,
                    f"第 {row_number} 条记录的 {field_name} "
                    f"不是有效数字：{raw_value!r}",
                )
            )
            continue

        if not math.isfinite(numeric_value):
            issues.append(
                _issue(
                    "invalid_number",
                    field_name,
                    f"第 {row_number} 条记录的 {field_name} 必须是有限数值",
                )
            )
            continue

        minimum, maximum, code, label = range_rules[field_name]
        if not minimum <= numeric_value <= maximum:
            issues.append(
                _issue(
                    code,
                    field_name,
                    f"第 {row_number} 条记录的{label}必须在 "
                    f"{minimum:g}～{maximum:g} 之间",
                )
            )
        result[field_name] = numeric_value

    if "production_time" in mapped:
        try:
            result["production_time"] = _normalize_production_time(
                mapped["production_time"]
            )
        except ValueError:
            issues.append(
                _issue(
                    "invalid_time",
                    "production_time",
                    "生产时间必须是 YYYY-MM-DD 或 "
                    "YYYY-MM-DD HH:MM:SS",
                )
            )

    return (None if issues else result), issues


def validate_production_file(
    path: str | Path | None = None,
) -> ValidationReport:
    candidate = _candidate_data_file(path)
    report = ValidationReport(
        source_path=str(candidate),
        source_format=candidate.suffix.lstrip(".").upper() or "UNKNOWN",
    )

    try:
        data_file = resolve_data_file(path)
        policy = load_rules().validation
    except (ProductionDataError, RuleConfigurationError) as exc:
        report.file_errors.append(
            _issue("source_invalid", "file", str(exc))
        )
        return report

    try:
        raw_records = (
            _read_csv(data_file)
            if data_file.suffix.lower() == ".csv"
            else _read_json(data_file)
        )
    except ProductionDataError as exc:
        report.file_errors.append(
            _issue("file_format_invalid", "file", str(exc))
        )
        return report

    report.total_records = len(raw_records)
    if not raw_records:
        report.file_errors.append(
            _issue("empty_file", "file", "生产数据文件没有记录")
        )
        return report

    first_row_number = 2 if data_file.suffix.lower() == ".csv" else 1
    seen_batches: set[str] = set()

    for row_number, raw_record in enumerate(
        raw_records,
        start=first_row_number,
    ):
        record, issues = _map_record_issues(
            raw_record,
            row_number,
            policy,
        )
        batch_id = record["batch_id"] if record else None

        if record and record["batch_id"] in seen_batches:
            issues.append(
                _issue(
                    "duplicate_batch",
                    "batch_id",
                    f"批次编号重复：{record['batch_id']}",
                )
            )
            record = None

        if issues:
            report.rejected_records += 1
            for issue in issues:
                report.reason_counts[issue.code] = (
                    report.reason_counts.get(issue.code, 0) + 1
                )
            if len(report.record_errors) < MAX_ERROR_DETAILS:
                report.record_errors.append({
                    "row_number": row_number,
                    "batch_id": batch_id,
                    "issues": [issue.as_dict() for issue in issues],
                })
            continue

        seen_batches.add(record["batch_id"])
        report.records.append(record)

    report.valid_records = len(report.records)
    return report


def load_production_records(
    path: str | Path | None = None,
) -> list[dict[str, Any]]:
    report = validate_production_file(path)
    if not report.healthy:
        messages = [
            issue.message
            for issue in report.file_errors
        ]
        for row in report.record_errors[:3]:
            messages.extend(
                issue["message"] for issue in row["issues"]
            )
        detail = "；".join(messages[:5]) or "生产数据校验失败"
        raise ProductionDataError(
            f"生产数据校验失败（{report.rejected_records} 条被拒绝）："
            f"{detail}"
        )
    return report.records


def summarize_source(path: str | Path | None = None) -> dict[str, Any]:
    data_file = resolve_data_file(path)
    return {
        "name": data_file.name,
        "path": str(data_file),
        "format": data_file.suffix.lstrip(".").upper(),
    }
