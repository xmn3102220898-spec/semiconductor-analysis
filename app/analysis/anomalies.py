"""设备异常识别与统计。

所有生产数据分析入口共用这里的阈值，避免报告、仪表盘和导出脚本
使用不同标准。
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

from app.analysis.rules import (
    Thresholds,
    default_thresholds,
    resolve_equipment_rules,
)
from app.data.query import query_equipment_data


DEFAULT_THRESHOLDS = default_thresholds()
TEMPERATURE_LIMIT = DEFAULT_THRESHOLDS.temperature_c
PRESSURE_LIMIT = DEFAULT_THRESHOLDS.pressure_kpa
YIELD_LIMIT = DEFAULT_THRESHOLDS.yield_pct

ANOMALY_LABELS = {
    "temperature": "温度异常",
    "pressure": "压力异常",
    "yield": "低良率异常",
}


def _detect_anomalies(
    rows: Iterable[Sequence[Any]],
    thresholds: Thresholds,
) -> list[dict[str, Any]]:
    """从查询结果中识别异常事件。"""
    anomalies: list[dict[str, str]] = []

    for row in rows:
        batch_id = row[1]
        temperature = row[4]
        pressure = row[5]
        yield_pct = row[6]

        if temperature > thresholds.temperature_c:
            anomalies.append(
                {
                    "batch_id": batch_id,
                    "metric": "temperature",
                    "type": ANOMALY_LABELS["temperature"],
                    "value": f"{temperature:g}℃",
                    "raw_value": float(temperature),
                    "threshold": thresholds.temperature_c,
                }
            )

        if pressure > thresholds.pressure_kpa:
            anomalies.append(
                {
                    "batch_id": batch_id,
                    "metric": "pressure",
                    "type": ANOMALY_LABELS["pressure"],
                    "value": f"{pressure:g}kPa",
                    "raw_value": float(pressure),
                    "threshold": thresholds.pressure_kpa,
                }
            )

        if yield_pct < thresholds.yield_pct:
            anomalies.append(
                {
                    "batch_id": batch_id,
                    "metric": "yield",
                    "type": ANOMALY_LABELS["yield"],
                    "value": f"{yield_pct:g}%",
                    "raw_value": float(yield_pct),
                    "threshold": thresholds.yield_pct,
                }
            )

    return anomalies


def analyze_equipment(equipment_id: str) -> list[dict[str, Any]]:
    """分析指定设备的异常事件。"""
    _, thresholds = resolve_equipment_rules(equipment_id)
    return _detect_anomalies(
        query_equipment_data(equipment_id),
        thresholds,
    )


def build_equipment_analysis(equipment_id: str) -> dict[str, Any]:
    """一次查询生成仪表盘所需的异常事件和生产统计。"""
    rows = query_equipment_data(equipment_id)
    equipment_type, thresholds = resolve_equipment_rules(equipment_id)
    anomalies = _detect_anomalies(rows, thresholds)

    affected_batches = {item["batch_id"] for item in anomalies}
    temperatures = [float(row[4]) for row in rows]
    pressures = [float(row[5]) for row in rows]
    yields = [float(row[6]) for row in rows]

    stats = {
        "record_count": len(rows),
        "total": len(anomalies),
        "temperature": sum(
            item["type"] == ANOMALY_LABELS["temperature"]
            for item in anomalies
        ),
        "pressure": sum(
            item["type"] == ANOMALY_LABELS["pressure"]
            for item in anomalies
        ),
        "yield": sum(
            item["type"] == ANOMALY_LABELS["yield"]
            for item in anomalies
        ),
        "affected_batches": len(affected_batches),
        "normal_batches": len(rows) - len(affected_batches),
        "average_temperature": (
            round(sum(temperatures) / len(temperatures), 2)
            if temperatures
            else None
        ),
        "average_pressure": (
            round(sum(pressures) / len(pressures), 2)
            if pressures
            else None
        ),
        "average_yield": (
            round(sum(yields) / len(yields), 2)
            if yields
            else None
        ),
        "equipment_type": equipment_type,
        "thresholds": thresholds.as_dict(),
    }

    return {
        "records": rows,
        "anomalies": anomalies,
        "stats": stats,
    }


def calculate_risk(anomalies: list[dict[str, Any]]) -> tuple[int, str]:
    """保留原有风险评分接口，用于异常分析教学示例。"""
    score = 0

    for item in anomalies:
        if item["type"] == ANOMALY_LABELS["yield"]:
            score += 50
        elif item["type"] == ANOMALY_LABELS["temperature"]:
            score += 30
        elif item["type"] == ANOMALY_LABELS["pressure"]:
            score += 20

    if score >= 70:
        level = "高风险"
    elif score >= 40:
        level = "中风险"
    else:
        level = "低风险"

    return score, level


def format_anomaly_result(equipment_id: str) -> str:
    analysis = build_equipment_analysis(equipment_id)
    anomalies = analysis["anomalies"]
    score, level = calculate_risk(anomalies)

    text = (
        "异常分析结果：\n\n"
        f"设备：\n{equipment_id}\n\n"
        f"风险评分：\n{score}\n\n"
        f"风险等级：\n{level}\n\n"
        "异常记录：\n"
    )

    for item in anomalies:
        text += (
            f"\n批次：\n{item['batch_id']}\n\n"
            f"异常类型：\n{item['type']}\n\n"
            f"异常值：\n{item['value']}\n"
            "----------------\n"
        )

    return text


if __name__ == "__main__":
    result = build_equipment_analysis("ETCH-02")
    print(format_anomaly_result("ETCH-02"))
    print("统计：", result["stats"])
