"""Repeatable local latency baseline for the core data and analysis path."""

from __future__ import annotations

import os
import statistics
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("LOG_LEVEL", "CRITICAL")

from app.analysis.anomalies import build_equipment_analysis  # noqa: E402
from app.analysis.health import (  # noqa: E402
    calculate_batch_health_trend,
    calculate_health_score_from_anomalies,
)
from app.data.manager import ensure_production_data_current  # noqa: E402


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = round((len(ordered) - 1) * percentile)
    return ordered[index]


def _measure(iterations: int, operation) -> list[float]:
    durations: list[float] = []
    for _ in range(iterations):
        started_at = time.perf_counter()
        operation()
        durations.append((time.perf_counter() - started_at) * 1000)
    return durations


def main() -> int:
    iterations = 20
    sync_result = ensure_production_data_current()
    analysis = build_equipment_analysis("ETCH-02")
    anomalies = analysis["anomalies"]
    records = analysis["records"]

    operations = {
        "sync_check": ensure_production_data_current,
        "analysis": lambda: build_equipment_analysis("ETCH-02"),
        "batch_trend": lambda: calculate_batch_health_trend(
            records,
            anomalies,
        ),
        "health_score": lambda: calculate_health_score_from_anomalies(
            anomalies
        ),
    }

    print(
        f"records={sync_result['record_count']} "
        f"iterations={iterations}"
    )
    print(
        f"{'operation':20s} {'median_ms':>10s} "
        f"{'p95_ms':>10s} {'min_ms':>10s}"
    )

    for name, operation in operations.items():
        operation()
        durations = _measure(iterations, operation)
        print(
            f"{name:20s} "
            f"{statistics.median(durations):10.3f} "
            f"{_percentile(durations, 0.95):10.3f} "
            f"{min(durations):10.3f}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
