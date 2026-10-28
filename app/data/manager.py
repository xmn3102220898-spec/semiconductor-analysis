"""把外部 CSV/JSON 生产数据同步到 SQLite 查询缓存。"""

from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any

from app.data.source import (
    get_file_signature,
    load_production_records,
    resolve_data_file,
)
from app.config import settings
from app.observability import get_logger


BASE_DIR = settings.project_root
DB_FILE = settings.production_db

_SYNC_LOCK = threading.Lock()
logger = get_logger(__name__)


def get_connection(db_file: str | Path | None = None) -> sqlite3.Connection:
    """创建生产数据库连接。"""
    target = Path(db_file) if db_file else DB_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(target)


def create_database(db_file: str | Path | None = None) -> None:
    """创建生产数据表和外部数据源同步元数据表。"""
    with closing(get_connection(db_file)) as conn:
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS wafer_production (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    batch_id TEXT NOT NULL,
                    equipment_id TEXT NOT NULL,
                    process TEXT NOT NULL,
                    temperature_c REAL NOT NULL,
                    pressure_kpa REAL NOT NULL,
                    yield_pct REAL NOT NULL,
                    production_time TEXT
                )
                """
            )
            columns = {
                row[1]
                for row in conn.execute(
                    "PRAGMA table_info(wafer_production)"
                ).fetchall()
            }
            if "production_time" not in columns:
                conn.execute(
                    "ALTER TABLE wafer_production "
                    "ADD COLUMN production_time TEXT"
                )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS data_source_meta (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    source_path TEXT NOT NULL,
                    signature TEXT NOT NULL,
                    record_count INTEGER NOT NULL,
                    synced_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS "
                "idx_wafer_equipment "
                "ON wafer_production(equipment_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS "
                "idx_wafer_batch "
                "ON wafer_production(batch_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS "
                "idx_wafer_production_time "
                "ON wafer_production(production_time)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS "
                "idx_wafer_equipment_time "
                "ON wafer_production(equipment_id, production_time)"
            )


def _get_sync_meta(conn: sqlite3.Connection) -> tuple[str, str, int] | None:
    row = conn.execute(
        """
        SELECT source_path, signature, record_count
        FROM data_source_meta
        WHERE id = 1
        """
    ).fetchone()
    return row


def sync_production_data(
    data_file: str | Path | None = None,
    db_file: str | Path | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """在数据文件变化时原子替换生产数据表。

    返回本次是否实际写库、数据源路径和记录数，便于调用方展示状态。
    """
    started_at = time.perf_counter()
    source_path = resolve_data_file(data_file)
    signature = get_file_signature(source_path)

    with _SYNC_LOCK:
        create_database(db_file)

        with closing(get_connection(db_file)) as conn:
            meta = _get_sync_meta(conn)
            current_count = conn.execute(
                "SELECT COUNT(*) FROM wafer_production"
            ).fetchone()[0]

            metadata_matches = meta == (
                str(source_path),
                signature,
                current_count,
            )
            needs_sync = force or not metadata_matches

            if not needs_sync:
                duration_ms = round(
                    (time.perf_counter() - started_at) * 1000,
                    2,
                )
                logger.debug(
                    "production_data_sync_skipped",
                    extra={
                        "event": "production_data_sync_skipped",
                        "source_path": str(source_path),
                        "record_count": current_count,
                        "duration_ms": duration_ms,
                    },
                )
                return {
                    "synced": False,
                    "source_path": str(source_path),
                    "record_count": current_count,
                }

            try:
                records = load_production_records(source_path)
            except Exception:
                logger.exception(
                    "production_data_validation_failed",
                    extra={
                        "event": "production_data_validation_failed",
                        "source_path": str(source_path),
                    },
                )
                raise

            with conn:
                conn.execute("DELETE FROM wafer_production")
                conn.executemany(
                    """
                    INSERT INTO wafer_production (
                        batch_id,
                        equipment_id,
                        process,
                        temperature_c,
                        pressure_kpa,
                        yield_pct,
                        production_time
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            record["batch_id"],
                            record["equipment_id"],
                            record["process"],
                            record["temperature_c"],
                            record["pressure_kpa"],
                            record["yield_pct"],
                            record.get("production_time"),
                        )
                        for record in records
                    ],
                )
                conn.execute(
                    """
                    INSERT INTO data_source_meta (
                        id,
                        source_path,
                        signature,
                        record_count,
                        synced_at
                    )
                    VALUES (1, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        source_path = excluded.source_path,
                        signature = excluded.signature,
                        record_count = excluded.record_count,
                        synced_at = excluded.synced_at
                    """,
                    (
                        str(source_path),
                        signature,
                        len(records),
                        datetime.now().strftime(
                            "%Y-%m-%d %H:%M:%S"
                        ),
                    ),
                )

    duration_ms = round(
        (time.perf_counter() - started_at) * 1000,
        2,
    )
    logger.info(
        "production_data_synced",
        extra={
            "event": "production_data_synced",
            "source_path": str(source_path),
            "record_count": len(records),
            "duration_ms": duration_ms,
        },
    )

    return {
        "synced": True,
        "source_path": str(source_path),
        "record_count": len(records),
    }


def ensure_production_data_current() -> dict[str, Any]:
    """查询前调用，支持修改外部文件后自动刷新，无需重启服务。"""
    return sync_production_data()


def import_csv_data() -> None:
    """保留原脚本入口，显式强制重新导入外部数据文件。"""
    result = sync_production_data(force=True)
    print(f"成功导入 {result['record_count']} 条生产数据")


def main() -> None:
    result = sync_production_data(force=True)
    print("生产数据库初始化完成。")
    print(f"数据源：{result['source_path']}")
    print(f"记录数：{result['record_count']}")


if __name__ == "__main__":
    main()
