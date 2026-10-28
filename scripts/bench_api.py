"""Measure deterministic API latency without calling the LLM."""

from __future__ import annotations

import os
import statistics
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("LOG_LEVEL", "CRITICAL")

from fastapi.testclient import TestClient  # noqa: E402
import main_api  # noqa: E402


def _percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[round((len(ordered) - 1) * p)]


def main() -> int:
    client = TestClient(main_api.app)
    endpoints = {
        "health": "/health/ETCH-02",
        "analysis": "/api/equipment/ETCH-02/analysis",
        "records": "/api/production/records?page_size=50",
        "data_quality": "/api/data-quality",
    }
    iterations = 30

    print(
        f"{'endpoint':16s} {'status':>6s} {'p50_ms':>10s} "
        f"{'p95_ms':>10s} {'max_ms':>10s}"
    )
    for name, url in endpoints.items():
        response = client.get(url)
        if response.status_code != 200:
            raise RuntimeError(
                f"{url} returned {response.status_code}"
            )
        durations: list[float] = []
        for _ in range(iterations):
            started = time.perf_counter()
            response = client.get(url)
            durations.append((time.perf_counter() - started) * 1000)
            if response.status_code != 200:
                raise RuntimeError(
                    f"{url} returned {response.status_code}"
                )
        print(
            f"{name:16s} {200:6d} "
            f"{statistics.median(durations):10.3f} "
            f"{_percentile(durations, 0.95):10.3f} "
            f"{max(durations):10.3f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
