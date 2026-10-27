"""设备目录。

设备列表从当前外部生产数据文件同步后的数据库中读取，不再写死
ETCH-01/02/03。
"""

from __future__ import annotations

from database_query import query_equipment_ids


def get_equipment_ids() -> list[str]:
    """返回当前数据源中实际存在的设备编号。"""
    return query_equipment_ids()


def get_equipment_catalog() -> list[dict[str, str]]:
    """返回页面下拉框使用的设备目录。"""
    return [
        {
            "id": equipment_id,
            "label": equipment_id,
        }
        for equipment_id in get_equipment_ids()
    ]
