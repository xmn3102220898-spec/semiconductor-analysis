"""Backward-compatible imports for the equipment catalog."""

from app.data.equipment import (
    get_equipment_catalog,
    get_equipment_ids,
)

__all__ = [
    "get_equipment_catalog",
    "get_equipment_ids",
]
