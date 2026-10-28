"""Generate temporary 10k/100k datasets and measure indexed queries."""

from __future__ import annotations

import statistics
import sys
import tempfile
import time
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.data.manager import create_database, get_connection  # noqa: E402
from app.data.query import query_production_records  # noqa: E402


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = round((len(ordered) - 1) * percentile)
    return ordered[index]


def _fill_database(database_file: Path, row_count: int) -> None:
    create_database(database_file)
    started = datetime(2026, 1, 1, 0, 0, 0)
    records = [
        (
            f"SCALE-{index:06d}",
            f"ETCH-0{index % 3 + 1}",
            "Etching" if index % 2 == 0 else "Deposition",
            80.0 + index % 15,
            100.0 + index % 25,
            92.0 + index % 7,
            (started + timedelta(minutes=index)).strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
        )
        for index in range(row_count)
    ]

    with closing(get_connection(database_file)) as conn:
        conn.executemany(
            """
            INSERT INTO wafer_production (
                batch_id, equipment_id, process,
                temperature_c, pressure_kpa, yield_pct,
                production_time
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            records,
        )
        conn.commit()


def _measure(operation, iterations: int = 12) -> list[float]:
    operation()
    durations: list[float] = []
    for _ in range(iterations):
        started = time.perf_counter()
        operation()
        durations.append((time.perf_counter() - started) * 1000)
    return durations


def main() -> int:
    print(
        f"{'rows':>8s} {'equipment_p50':>15s} "
        f"{'equipment_p95':>15s} {'time_p50':>12s} {'time_p95':>12s}"
    )

    for row_count in (10_000, 100_000):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_file = Path(temp_dir) / "scale.db"
            _fill_database(database_file, row_count)

            equipment_durations = _measure(
                lambda: query_production_records(
                    equipment_id="ETCH-02",
                    page=2,
                    page_size=50,
                    sort_by="production_time",
                    order="desc",
                    db_file=database_file,
                )
            )
            time_durations = _measure(
                lambda: query_production_records(
                    start_time="2026-02-15 00:00:00",
                    end_time="2026-03-16 23:59:59",
                    page=1,
                    page_size=50,
                    sort_by="production_time",
                    order="desc",
                    db_file=database_file,
                )
            )
            print(
                f"{row_count:8d} "
                f"{statistics.median(equipment_durations):15.3f} "
                f"{_percentile(equipment_durations, 0.95):15.3f} "
                f"{statistics.median(time_durations):12.3f} "
                f"{_percentile(time_durations, 0.95):12.3f}"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
