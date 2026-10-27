"""设备健康评分趋势分析。"""

from __future__ import annotations

import math
from typing import Iterable

from health_score import risk_level_from_score


def _insufficient(message: str) -> dict[str, object]:
    return {
        "trend": "数据不足",
        "level": "暂无数据",
        "message": message,
    }


def analyze_health_trend(scores: Iterable[float]) -> dict[str, object]:
    """根据按时间排列的健康评分判断趋势与当前风险。

    趋势方向沿用项目原有口径：比较首尾评分。
    风险等级使用与仪表盘、报告一致的评分阈值。
    """
    score_list = list(scores)

    if len(score_list) < 2:
        return _insufficient(
            "历史诊断记录不足，暂时无法判断设备健康趋势。"
        )

    try:
        values = [float(score) for score in score_list]
    except (TypeError, ValueError):
        return _insufficient("历史评分中存在无效数据，暂时无法分析趋势。")

    if any(
        not math.isfinite(score) or score < 0 or score > 100
        for score in values
    ):
        return _insufficient(
            "历史评分超出 0～100 的有效范围，请检查数据。"
        )

    first = values[0]
    current = values[-1]
    change = current - first
    current_risk = risk_level_from_score(current)

    if change <= -20:
        risk_level = "高风险"
        trend = "持续下降"
        message = (
            f"健康评分从{first:g}下降到{current:g}，"
            "首尾评分下降20分或以上，设备状态可能明显恶化。"
        )
    elif change < 0:
        trend = "轻微下降"
        risk_level = (
            "高风险" if current_risk == "高风险" else "关注"
        )
        message = (
            f"健康评分从{first:g}下降到{current:g}，"
            f"当前风险等级为{current_risk}，需要持续观察。"
        )
    elif change == 0:
        trend = "稳定"
        risk_level = current_risk

        if current_risk == "高风险":
            message = (
                f"最近评分保持在{current:g}分附近，"
                "但当前仍处于高风险区间，不能仅凭趋势平稳排除风险。"
            )
        elif current_risk == "关注":
            message = (
                f"最近评分保持在{current:g}分附近，"
                "当前处于关注区间，建议继续监测。"
            )
        else:
            message = (
                f"最近评分保持在{current:g}分附近，"
                "当前状态正常，暂无明显恶化迹象。"
            )
    else:
        trend = "回升"
        risk_level = current_risk
        message = (
            f"健康评分从{first:g}回升到{current:g}，"
            f"当前风险等级为{current_risk}，建议继续保持监测。"
        )

    return {
        "trend": trend,
        "level": risk_level,
        "message": message,
        "start_score": first,
        "current_score": current,
        "change": change,
    }


if __name__ == "__main__":
    test_cases = {
        "持续下降": [82, 75, 68, 55, 45],
        "轻微下降": [82, 80, 79],
        "高风险但稳定": [45, 45, 45, 45, 45],
        "稳定": [82, 85, 90],
        "数据不足": [82],
        "空数据": [],
    }

    for name, scores in test_cases.items():
        print(f"\n测试：{name}")
        print("评分：", scores)
        print("结果：", analyze_health_trend(scores))
