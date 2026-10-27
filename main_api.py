"""ASGI entry point with backward-compatible imports."""

from app.api.main import (
    app,
    get_available_equipment,
    get_risk_level,
    get_trend_series,
    resolve_equipment_id,
    validate_equipment,
)
from app.llm.report import generate_report

__all__ = [
    "app",
    "generate_report",
    "get_available_equipment",
    "get_risk_level",
    "get_trend_series",
    "resolve_equipment_id",
    "validate_equipment",
]
