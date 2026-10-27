"""Backward-compatible imports for anomaly analysis."""

from app.analysis.anomalies import (
    ANOMALY_LABELS,
    PRESSURE_LIMIT,
    TEMPERATURE_LIMIT,
    YIELD_LIMIT,
    analyze_equipment,
    build_equipment_analysis,
    calculate_risk,
    format_anomaly_result,
)

__all__ = [
    "ANOMALY_LABELS",
    "PRESSURE_LIMIT",
    "TEMPERATURE_LIMIT",
    "YIELD_LIMIT",
    "analyze_equipment",
    "build_equipment_analysis",
    "calculate_risk",
    "format_anomaly_result",
]


if __name__ == "__main__":
    print(format_anomaly_result("ETCH-02"))
