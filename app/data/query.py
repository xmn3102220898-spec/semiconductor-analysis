"""生产数据查询接口。

查询前会检查外部 CSV/JSON 是否变化，保证应用读到的是最新文件内容。
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Sequence

from app.analysis.rules import default_thresholds
from app.data.manager import DB_FILE, ensure_production_data_current

SORT_COLUMNS = {
    "production_time": "production_time",
    "batch_id": "batch_id",
    "equipment_id": "equipment_id",
    "temperature_c": "temperature_c",
    "pressure_kpa": "pressure_kpa",
    "yield_pct": "yield_pct",
}


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


def query_production_records(
    equipment_id: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    sort_by: str = "production_time",
    order: str = "desc",
    page: int = 1,
    page_size: int = 20,
    db_file: str | Path | None = None,
) -> dict[str, Any]:
    """Return a filtered and paginated production-record page."""
    if sort_by not in SORT_COLUMNS:
        raise ValueError(f"不支持的排序字段：{sort_by}")
    if order.lower() not in {"asc", "desc"}:
        raise ValueError(f"不支持的排序方向：{order}")

    where_clauses: list[str] = []
    parameters: list[Any] = []
    if equipment_id:
        where_clauses.append("equipment_id = ?")
        parameters.append(equipment_id)
    if start_time:
        where_clauses.append("production_time >= ?")
        parameters.append(start_time)
    if end_time:
        where_clauses.append("production_time <= ?")
        parameters.append(end_time)

    where_sql = (
        f"WHERE {' AND '.join(where_clauses)}"
        if where_clauses
        else ""
    )
    sort_column = SORT_COLUMNS[sort_by]
    direction = order.upper()
    order_sql = (
        f"({sort_column} IS NULL) ASC, "
        f"{sort_column} {direction}, id {direction}"
        if sort_by == "production_time"
        else f"{sort_column} {direction}, id {direction}"
    )
    offset = (page - 1) * page_size

    if db_file is None:
        ensure_production_data_current()
        target = DB_FILE
    else:
        target = Path(db_file)

    with closing(sqlite3.connect(target)) as conn:
        total = conn.execute(
            f"SELECT COUNT(*) FROM wafer_production {where_sql}",
            parameters,
        ).fetchone()[0]
        rows = conn.execute(
            f"""
            SELECT
                id,
                batch_id,
                equipment_id,
                process,
                temperature_c,
                pressure_kpa,
                yield_pct,
                production_time
            FROM wafer_production
            {where_sql}
            ORDER BY {order_sql}
            LIMIT ? OFFSET ?
            """,
            [*parameters, page_size, offset],
        ).fetchall()

    items = [
        {
            "id": row[0],
            "batch_id": row[1],
            "equipment_id": row[2],
            "process": row[3],
            "temperature_c": row[4],
            "pressure_kpa": row[5],
            "yield_pct": row[6],
            "production_time": row[7],
        }
        for row in rows
    ]
    return {
        "items": items,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": (
                (total + page_size - 1) // page_size
                if page_size
                else 0
            ),
        },
        "filters": {
            "equipment_id": equipment_id,
            "start_time": start_time,
            "end_time": end_time,
        },
        "sort": {
            "sort_by": sort_by,
            "order": order.lower(),
        },
    }


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
        limit = default_thresholds().temperature_c

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
        limit = default_thresholds().pressure_kpa

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
        limit = default_thresholds().yield_pct

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
