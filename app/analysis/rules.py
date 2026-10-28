"""External anomaly thresholds and validation policy."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.config import settings


class RuleConfigurationError(ValueError):
    """Raised when the external analysis rule file is invalid."""


@dataclass(frozen=True)
class Thresholds:
    temperature_c: float
    pressure_kpa: float
    yield_pct: float

    def as_dict(self) -> dict[str, float]:
        return {
            "temperature_c": self.temperature_c,
            "pressure_kpa": self.pressure_kpa,
            "yield_pct": self.yield_pct,
        }


@dataclass(frozen=True)
class ValidationPolicy:
    temperature_min: float
    temperature_max: float
    pressure_min: float
    pressure_max: float
    yield_min: float
    yield_max: float
    equipment_id_pattern: re.Pattern[str]
    allowed_processes: frozenset[str]


@dataclass(frozen=True)
class RuleSet:
    defaults: Thresholds
    penalties: dict[str, int]
    equipment_prefixes: dict[str, str]
    equipment_types: dict[str, Thresholds]
    equipment_overrides: dict[str, dict[str, float]]
    validation: ValidationPolicy

    def resolve(self, equipment_id: str) -> tuple[str, Thresholds]:
        equipment_type = "default"

        for prefix, mapped_type in sorted(
            self.equipment_prefixes.items(),
            key=lambda item: len(item[0]),
            reverse=True,
        ):
            if equipment_id == prefix or equipment_id.startswith(
                f"{prefix}-"
            ):
                equipment_type = mapped_type
                break

        thresholds = self.equipment_types.get(
            equipment_type,
            self.defaults,
        )
        override = self.equipment_overrides.get(equipment_id, {})
        resolved = Thresholds(
            temperature_c=override.get(
                "temperature_c",
                thresholds.temperature_c,
            ),
            pressure_kpa=override.get(
                "pressure_kpa",
                thresholds.pressure_kpa,
            ),
            yield_pct=override.get(
                "yield_pct",
                thresholds.yield_pct,
            ),
        )
        return (
            equipment_type,
            resolved,
        )


def _number(source: dict[str, Any], key: str, context: str) -> float:
    value = source.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RuleConfigurationError(f"{context}.{key} 必须是数字")
    return float(value)


def _environment_number(name: str) -> float | None:
    """Return an explicitly configured override, else ``None``.

    An unset or blank variable means "no override": the rules file stays
    the source of truth. Only a non-empty value wins over the JSON value.
    """
    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        return None
    try:
        return float(raw_value)
    except ValueError as exc:
        raise RuleConfigurationError(
            f"环境变量 {name} 必须是数字"
        ) from exc


def _apply_threshold_overrides(
    defaults_payload: dict[str, Any],
) -> None:
    """Resolve precedence as env override > rules file > settings default."""
    overrides = (
        ("TEMPERATURE_LIMIT", "temperature_c", settings.temperature_limit),
        ("PRESSURE_LIMIT", "pressure_kpa", settings.pressure_limit),
        ("YIELD_LIMIT", "yield_pct", settings.yield_limit),
    )
    for env_name, key, settings_default in overrides:
        explicit = _environment_number(env_name)
        if explicit is not None:
            defaults_payload[key] = explicit
        elif key not in defaults_payload:
            defaults_payload[key] = settings_default


def _thresholds(
    source: dict[str, Any],
    fallback: Thresholds | None = None,
) -> Thresholds:
    return Thresholds(
        temperature_c=_number(
            source,
            "temperature_c",
            "thresholds",
        )
        if "temperature_c" in source or fallback is None
        else fallback.temperature_c,
        pressure_kpa=_number(
            source,
            "pressure_kpa",
            "thresholds",
        )
        if "pressure_kpa" in source or fallback is None
        else fallback.pressure_kpa,
        yield_pct=_number(
            source,
            "yield_pct",
            "thresholds",
        )
        if "yield_pct" in source or fallback is None
        else fallback.yield_pct,
    )


@lru_cache(maxsize=4)
def load_rules(path: str | None = None) -> RuleSet:
    rules_path = Path(path).resolve() if path else settings.rules_file

    try:
        payload = json.loads(rules_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuleConfigurationError(
            f"找不到分析规则文件：{rules_path}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise RuleConfigurationError(
            f"分析规则 JSON 无效：第 {exc.lineno} 行第 {exc.colno} 列"
        ) from exc

    defaults_payload = payload.get("default_thresholds")
    if not isinstance(defaults_payload, dict):
        raise RuleConfigurationError(
            "default_thresholds 必须是对象"
        )

    _apply_threshold_overrides(defaults_payload)

    defaults = _thresholds(defaults_payload)
    penalty_payload = payload.get("health_penalties", {})
    penalties = {
        key: int(value)
        for key, value in penalty_payload.items()
    }

    equipment_types = {
        name: _thresholds(value, defaults)
        for name, value in payload.get(
            "equipment_types",
            {},
        ).items()
    }
    equipment_overrides = {
        name: {
            key: _number(value, key, f"equipment_overrides.{name}")
            for key in (
                "temperature_c",
                "pressure_kpa",
                "yield_pct",
            )
            if key in value
        }
        for name, value in payload.get(
            "equipment_overrides",
            {},
        ).items()
    }
    validation_payload = payload.get("validation", {})
    allowed_processes = frozenset(
        validation_payload.get("allowed_processes", [])
    )

    try:
        equipment_pattern = re.compile(
            validation_payload["equipment_id_pattern"]
        )
    except (KeyError, re.error) as exc:
        raise RuleConfigurationError(
            "validation.equipment_id_pattern 缺失或无效"
        ) from exc

    validation = ValidationPolicy(
        temperature_min=_number(
            validation_payload.get("temperature_c", {}),
            "min",
            "validation.temperature_c",
        ),
        temperature_max=_number(
            validation_payload.get("temperature_c", {}),
            "max",
            "validation.temperature_c",
        ),
        pressure_min=_number(
            validation_payload.get("pressure_kpa", {}),
            "min",
            "validation.pressure_kpa",
        ),
        pressure_max=_number(
            validation_payload.get("pressure_kpa", {}),
            "max",
            "validation.pressure_kpa",
        ),
        yield_min=_number(
            validation_payload.get("yield_pct", {}),
            "min",
            "validation.yield_pct",
        ),
        yield_max=_number(
            validation_payload.get("yield_pct", {}),
            "max",
            "validation.yield_pct",
        ),
        equipment_id_pattern=equipment_pattern,
        allowed_processes=allowed_processes,
    )

    return RuleSet(
        defaults=defaults,
        penalties=penalties,
        equipment_prefixes=dict(
            payload.get("equipment_prefixes", {})
        ),
        equipment_types=equipment_types,
        equipment_overrides=equipment_overrides,
        validation=validation,
    )


def resolve_equipment_rules(
    equipment_id: str,
    path: str | None = None,
) -> tuple[str, Thresholds]:
    return load_rules(path).resolve(equipment_id)


def default_thresholds() -> Thresholds:
    return load_rules().defaults
