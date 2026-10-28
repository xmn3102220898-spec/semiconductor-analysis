"""Backward-compatible imports for production data queries."""

from app.data.query import (
    execute_query,
    main,
    query_all_data,
    query_equipment_data,
    query_equipment_ids,
    query_pressure_kpa,
    query_production_records,
    query_record_count,
    query_temperature_anomaly,
    query_yield_pct,
)

__all__ = [
    "execute_query",
    "main",
    "query_all_data",
    "query_equipment_data",
    "query_equipment_ids",
    "query_pressure_kpa",
    "query_production_records",
    "query_record_count",
    "query_temperature_anomaly",
    "query_yield_pct",
]


if __name__ == "__main__":
    main()
