"""Backward-compatible imports for health scoring."""

from app.analysis.health import (
    PENALTY,
    calculate_batch_health_trend,
    calculate_health_score,
    calculate_health_score_from_anomalies,
    build_health_score_breakdown,
    risk_level_from_score,
)

__all__ = [
    "PENALTY",
    "calculate_batch_health_trend",
    "calculate_health_score",
    "calculate_health_score_from_anomalies",
    "build_health_score_breakdown",
    "risk_level_from_score",
]


if __name__ == "__main__":
    score = calculate_health_score("ETCH-02")
    print(f"ETCH-02 健康评分：{score}")
    print(f"风险等级：{risk_level_from_score(score)}")
