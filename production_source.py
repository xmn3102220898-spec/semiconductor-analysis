"""Backward-compatible imports for the data source module."""

from app.data.source import (
    DATA_FILE_ENV,
    DEFAULT_DATA_FILE,
    ProductionDataError,
    ValidationIssue,
    ValidationReport,
    get_file_signature,
    load_production_records,
    resolve_data_file,
    summarize_source,
    validate_production_file,
)

__all__ = [
    "DATA_FILE_ENV",
    "DEFAULT_DATA_FILE",
    "ProductionDataError",
    "ValidationIssue",
    "ValidationReport",
    "get_file_signature",
    "load_production_records",
    "resolve_data_file",
    "summarize_source",
    "validate_production_file",
]
