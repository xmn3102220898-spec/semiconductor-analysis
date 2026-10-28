"""设备健康评分与风险等级。"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from app.analysis.anomalies import analyze_equipment
from app.analysis.rules import load_rules


_RULE_SET = load_rules()
PENALTY = {
    "温度异常": _RULE_SET.penalties.get("temperature", 15),
    "压力异常": _RULE_SET.penalties.get("pressure", 10),
    "低良率异常": _RULE_SET.penalties.get("yield", 30),
}


def calculate_health_score_from_anomalies(
    anomalies: Iterable[Mapping[str, Any]],
) -> int:
    """根据异常事件计算 0～100 健康评分。"""
    return build_health_score_breakdown(anomalies)["final_score"]


def build_health_score_breakdown(
    anomalies: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build an auditable event-level score deduction list."""
    score = 100
    deductions: list[dict[str, Any]] = []

    for item in anomalies:
        penalty = PENALTY.get(str(item.get("type", "")), 0)
        previous_score = score
        score = max(0, score - penalty)
        deductions.append({
            "batch_id": item.get("batch_id"),
            "metric": item.get("metric"),
            "type": item.get("type"),
            "value": item.get("value"),
            "threshold": item.get("threshold"),
            "penalty": penalty,
            "effective_penalty": previous_score - score,
            "remaining_score": score,
        })

    total_penalty = sum(item["penalty"] for item in deductions)
    return {
        "base_score": 100,
        "total_penalty": total_penalty,
        "final_score": score,
        "floor_applied": total_penalty > 100,
        "deductions": deductions,
    }


def calculate_batch_health_trend(
    records: Iterable[Sequence[Any]],
    anomalies: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """按生产批次顺序计算累计健康评分。

    每个异常事件在所属批次发生时扣一次分，后续批次保留已经产生的扣分。
    因此最后一个点的评分与设备当前总评分一致。
    """
    anomaly_types_by_batch: dict[str, list[str]] = {}

    for item in anomalies:
        anomaly_types_by_batch.setdefault(
            item["batch_id"],
            [],
        ).append(item["type"])

    score = 100
    points: list[dict[str, Any]] = []

    for row in records:
        batch_id = row[1]
        event_types = anomaly_types_by_batch.get(batch_id, [])
        penalty = sum(
            PENALTY.get(event_type, 0)
            for event_type in event_types
        )
        score = max(0, score - penalty)

        points.append({
            "batch_id": batch_id,
            "score": score,
            "penalty": penalty,
            "anomaly_count": len(event_types),
        })

    return points


def risk_level_from_score(score: int | float) -> str:
    """健康评分对应的统一风险等级。"""
    if score >= 80:
        return "正常"
    if score >= 60:
        return "关注"
    return "高风险"


def calculate_health_score(equipment_id: str) -> int:
    """查询设备异常并计算健康评分。"""
    anomalies = analyze_equipment(equipment_id)
    return calculate_health_score_from_anomalies(anomalies)


if __name__ == "__main__":
    equipment_id = "ETCH-02"
    score = calculate_health_score(equipment_id)

    print("设备：", equipment_id)
    print("健康评分：", score)
    print("风险等级：", risk_level_from_score(score))
