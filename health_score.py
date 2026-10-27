"""设备健康评分与风险等级。"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from anomaly_analysis import analyze_equipment


PENALTY = {
    "温度异常": 15,
    "压力异常": 10,
    "低良率异常": 30,
}


def calculate_health_score_from_anomalies(
    anomalies: Iterable[Mapping[str, str]],
) -> int:
    """根据异常事件计算 0～100 健康评分。"""
    score = 100

    for item in anomalies:
        score -= PENALTY.get(item.get("type", ""), 0)

    return max(0, score)


def calculate_batch_health_trend(
    records: Iterable[Sequence[Any]],
    anomalies: Iterable[Mapping[str, str]],
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
