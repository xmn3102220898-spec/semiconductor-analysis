"""生产数据查询接口。

查询前会检查外部 CSV/JSON 是否变化，保证应用读到的是最新文件内容。
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Sequence

from database_manager import DB_FILE, ensure_production_data_current


def execute_query(
    sql: str,
    params: Sequence[Any] | None = None,
    db_file: str | Path | None = None,
) -> list[tuple[Any, ...]]:
    """执行只读查询并返回全部结果。"""
    if db_file is None:
        ensure_production_data_current()
        target = DB_FILE
    else:
        target = Path(db_file)

    with closing(sqlite3.connect(target)) as conn:
        cursor = conn.execute(sql, params or ())
        return cursor.fetchall()


def query_all_data() -> list[tuple[Any, ...]]:
    """查询全部生产记录。"""
    return execute_query(
        """
        SELECT *
        FROM wafer_production
        ORDER BY id
        """
    )


def query_equipment_ids() -> list[str]:
    """从外部数据同步结果中读取设备列表。"""
    rows = execute_query(
        """
        SELECT DISTINCT equipment_id
        FROM wafer_production
        ORDER BY equipment_id
        """
    )
    return [row[0] for row in rows]


def query_record_count() -> int:
    """返回当前生产数据表中的记录总数。"""
    rows = execute_query("SELECT COUNT(*) FROM wafer_production")
    return int(rows[0][0])


def query_equipment_data(equipment_id: str) -> list[tuple[Any, ...]]:
    """按设备编号查询生产记录。"""
    return execute_query(
        """
        SELECT *
        FROM wafer_production
        WHERE equipment_id = ?
        ORDER BY id
        """,
        (equipment_id,),
    )


def query_temperature_anomaly(
    limit: float | None = None,
) -> list[tuple[Any, ...]]:
    if limit is None:
        from anomaly_analysis import TEMPERATURE_LIMIT

        limit = TEMPERATURE_LIMIT

    return execute_query(
        """
        SELECT *
        FROM wafer_production
        WHERE temperature_c > ?
        ORDER BY id
        """,
        (limit,),
    )


def query_pressure_kpa(
    limit: float | None = None,
) -> list[tuple[Any, ...]]:
    if limit is None:
        from anomaly_analysis import PRESSURE_LIMIT

        limit = PRESSURE_LIMIT

    return execute_query(
        """
        SELECT *
        FROM wafer_production
        WHERE pressure_kpa > ?
        ORDER BY id
        """,
        (limit,),
    )


def query_yield_pct(
    limit: float | None = None,
) -> list[tuple[Any, ...]]:
    if limit is None:
        from anomaly_analysis import YIELD_LIMIT

        limit = YIELD_LIMIT

    return execute_query(
        """
        SELECT *
        FROM wafer_production
        WHERE yield_pct < ?
        ORDER BY id
        """,
        (limit,),
    )


def main() -> None:
    for equipment_id in query_equipment_ids():
        rows = query_equipment_data(equipment_id)
        print(f"{equipment_id}: {len(rows)} 条生产记录")


if __name__ == "__main__":
    main()
