"""Backward-compatible production analysis CLI entry point."""

from scripts.tools.analyze_production import (
    analyze_production_data,
    cli,
    detect_anomalies,
    generate_production_data,
    load_production_data,
    main,
)

__all__ = [
    "analyze_production_data",
    "cli",
    "detect_anomalies",
    "generate_production_data",
    "load_production_data",
    "main",
]


if __name__ == "__main__":
    cli()
