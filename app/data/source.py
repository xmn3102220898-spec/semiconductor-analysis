"""生产数据文件读取与校验。

后端默认读取 data/production_data.csv，也可以通过环境变量
PRODUCTION_DATA_FILE 指向其他 CSV 或 JSON 文件。数据库只是
外部数据文件的本地查询缓存，文件内容变化后会自动重新同步。
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from app.config import settings

BASE_DIR = settings.project_root
DEFAULT_DATA_FILE = settings.data_file
DATA_FILE_ENV = "PRODUCTION_DATA_FILE"

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
}


class ProductionDataError(ValueError):
    """生产数据文件缺失、格式错误或内容无效。"""


def _normalize_key(value: Any) -> str:
    """统一列名，方便识别中英文表头和大小写差异。"""
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


def resolve_data_file(path: str | Path | None = None) -> Path:
    """解析生产数据文件路径；相对路径以项目根目录为基准。"""
    configured = path or DEFAULT_DATA_FILE
    data_file = Path(configured).expanduser()

    if not data_file.is_absolute():
        data_file = BASE_DIR / data_file

    data_file = data_file.resolve()

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
    """用文件内容哈希判断外部数据是否发生变化。"""
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
        # 兼容 { "BATCH-001": {...}, "BATCH-002": {...} } 这种写法。
        if all(isinstance(item, dict) for item in payload.values()):
            records = list(payload.values())

    if not isinstance(records, list):
        raise ProductionDataError(
            "JSON 顶层必须是记录数组，或包含 records/data/items 数组的对象。"
        )

    if any(not isinstance(item, dict) for item in records):
        raise ProductionDataError("JSON 记录数组中的每一项都必须是对象。")

    return records


def _map_record(
    record: dict[str, Any],
    row_number: int,
) -> dict[str, Any]:
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

    missing = [field for field in CANONICAL_FIELDS if field not in mapped]
    if missing:
        raise ProductionDataError(
            f"第 {row_number} 条记录缺少字段：{', '.join(missing)}"
        )

    result: dict[str, Any] = {}
    for field in TEXT_FIELDS:
        value = "" if mapped[field] is None else str(mapped[field]).strip()
        if not value:
            raise ProductionDataError(
                f"第 {row_number} 条记录的 {field} 不能为空。"
            )
        result[field] = value

    for field in NUMERIC_FIELDS:
        raw_value = mapped[field]
        if raw_value is None or str(raw_value).strip() == "":
            raise ProductionDataError(
                f"第 {row_number} 条记录的 {field} 不能为空。"
            )

        numeric_text = str(raw_value).strip().replace(",", "")
        for unit in ("℃", "°C", "kPa", "kpa", "%", " ", "\t", "\u3000"):
            numeric_text = numeric_text.replace(unit, "")

        try:
            numeric_value = float(numeric_text)
        except ValueError as exc:
            raise ProductionDataError(
                f"第 {row_number} 条记录的 {field} 不是有效数字："
                f"{raw_value!r}"
            ) from exc

        if not math.isfinite(numeric_value):
            raise ProductionDataError(
                f"第 {row_number} 条记录的 {field} 必须是有限数值。"
            )

        result[field] = numeric_value

    if result["pressure_kpa"] < 0:
        raise ProductionDataError(
            f"第 {row_number} 条记录的压力不能为负数。"
        )

    if not 0 <= result["yield_pct"] <= 100:
        raise ProductionDataError(
            f"第 {row_number} 条记录的良率必须在 0～100 之间。"
        )

    return result


def load_production_records(
    path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """读取并校验 CSV/JSON，返回统一字段结构的记录列表。"""
    data_file = resolve_data_file(path)

    if data_file.suffix.lower() == ".csv":
        raw_records = _read_csv(data_file)
        first_row_number = 2
    else:
        raw_records = _read_json(data_file)
        first_row_number = 1

    if not raw_records:
        raise ProductionDataError(f"生产数据文件没有记录：{data_file}")

    records: list[dict[str, Any]] = []
    seen_batches: set[str] = set()

    for row_number, raw_record in enumerate(
        raw_records,
        start=first_row_number,
    ):
        record = _map_record(raw_record, row_number)
        batch_id = record["batch_id"]

        if batch_id in seen_batches:
            raise ProductionDataError(f"批次编号重复：{batch_id}")

        seen_batches.add(batch_id)
        records.append(record)

    return records


def summarize_source(path: str | Path | None = None) -> dict[str, Any]:
    """返回页面展示所需的数据源信息。"""
    data_file = resolve_data_file(path)

    return {
        "name": data_file.name,
        "path": str(data_file),
        "format": data_file.suffix.lstrip(".").upper(),
    }
