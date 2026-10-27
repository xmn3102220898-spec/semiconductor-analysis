"""SQLite 分析练习：用 SQL 复现项目中的设备统计和异常筛选。

运行：
    python -X utf8 sql_practice.py
"""

from __future__ import annotations

from typing import Any, Sequence

from app.analysis.anomalies import (
    PRESSURE_LIMIT,
    TEMPERATURE_LIMIT,
    YIELD_LIMIT,
)
from app.data.query import execute_query


QUERIES: list[dict[str, Any]] = [
    {
        "title": "1. 按设备汇总批次、温度、压力和良率",
        "sql": """
            SELECT
                equipment_id,
                COUNT(*) AS batch_count,
                ROUND(AVG(temperature_c), 2) AS avg_temperature,
                ROUND(AVG(pressure_kpa), 2) AS avg_pressure,
                ROUND(AVG(yield_pct), 2) AS avg_yield
            FROM wafer_production
            GROUP BY equipment_id
            ORDER BY equipment_id
        """,
        "params": (),
    },
    {
        "title": "2. 按工艺汇总生产批次",
        "sql": """
            SELECT
                process,
                COUNT(*) AS batch_count,
                ROUND(AVG(yield_pct), 2) AS avg_yield
            FROM wafer_production
            GROUP BY process
            ORDER BY batch_count DESC, process
        """,
        "params": (),
    },
    {
        "title": "3. 用 UNION ALL 生成异常事件明细",
        "sql": """
            WITH anomaly_events AS (
                SELECT
                    batch_id,
                    equipment_id,
                    '温度异常' AS anomaly_type,
                    temperature_c AS measured_value,
                    '℃' AS unit
                FROM wafer_production
                WHERE temperature_c > ?

                UNION ALL

                SELECT
                    batch_id,
                    equipment_id,
                    '压力异常' AS anomaly_type,
                    pressure_kpa AS measured_value,
                    'kPa' AS unit
                FROM wafer_production
                WHERE pressure_kpa > ?

                UNION ALL

                SELECT
                    batch_id,
                    equipment_id,
                    '低良率异常' AS anomaly_type,
                    yield_pct AS measured_value,
                    '%' AS unit
                FROM wafer_production
                WHERE yield_pct < ?
            )
            SELECT
                batch_id,
                equipment_id,
                anomaly_type,
                printf('%.2f%s', measured_value, unit) AS display_value
            FROM anomaly_events
            ORDER BY batch_id, anomaly_type
        """,
        "params": (TEMPERATURE_LIMIT, PRESSURE_LIMIT, YIELD_LIMIT),
    },
    {
        "title": "4. 按异常事件数量排序设备",
        "sql": """
            WITH anomaly_events AS (
                SELECT equipment_id
                FROM wafer_production
                WHERE temperature_c > ?

                UNION ALL

                SELECT equipment_id
                FROM wafer_production
                WHERE pressure_kpa > ?

                UNION ALL

                SELECT equipment_id
                FROM wafer_production
                WHERE yield_pct < ?
            )
            SELECT
                equipment_id,
                COUNT(*) AS anomaly_event_count
            FROM anomaly_events
            GROUP BY equipment_id
            ORDER BY anomaly_event_count DESC, equipment_id
        """,
        "params": (TEMPERATURE_LIMIT, PRESSURE_LIMIT, YIELD_LIMIT),
    },
]


def print_query_result(
    title: str,
    rows: Sequence[Sequence[Any]],
) -> None:
    """简单打印查询结果，不依赖额外的表格库。"""
    print(f"\n{'=' * 20} {title} {'=' * 20}")
    print(f"返回行数：{len(rows)}")

    for row in rows:
        print(row)


def main() -> None:
    for query in QUERIES:
        rows = execute_query(query["sql"], query["params"])
        print_query_result(query["title"], rows)


if __name__ == "__main__":
    main()
