"""Backward-compatible imports for diagnosis history persistence."""

from app.data.history import (
    DB_NAME,
    get_connection,
    get_diagnosis_detail,
    get_diagnosis_records,
    get_health_history,
    init_database,
    save_diagnosis,
)

__all__ = [
    "DB_NAME",
    "get_connection",
    "get_diagnosis_detail",
    "get_diagnosis_records",
    "get_health_history",
    "init_database",
    "save_diagnosis",
]


if __name__ == "__main__":
    init_database()
    print(f"诊断数据库初始化完成：{DB_NAME}")
