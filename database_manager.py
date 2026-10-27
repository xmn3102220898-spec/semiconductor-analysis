"""Backward-compatible imports for the production data manager."""

from app.data.manager import (
    DB_FILE,
    create_database,
    ensure_production_data_current,
    get_connection,
    import_csv_data,
    main,
    sync_production_data,
)

__all__ = [
    "DB_FILE",
    "create_database",
    "ensure_production_data_current",
    "get_connection",
    "import_csv_data",
    "main",
    "sync_production_data",
]


if __name__ == "__main__":
    main()
