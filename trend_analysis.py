"""Backward-compatible imports for health trend analysis."""

from app.analysis.trend import analyze_health_trend

__all__ = ["analyze_health_trend"]


if __name__ == "__main__":
    print(analyze_health_trend([82, 75, 68, 55, 45]))
