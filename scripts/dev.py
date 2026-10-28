"""Cross-platform development commands mirroring the Makefile."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def run_command(arguments: list[str]) -> int:
    print("+", " ".join(arguments))
    return subprocess.call(arguments, cwd=PROJECT_ROOT)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=(
            "install",
            "run",
            "test",
            "lint",
            "bench",
            "rag-eval",
            "rag-regression",
            "check",
        ),
    )
    args = parser.parse_args()

    if args.command == "install":
        return run_command(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "-r",
                "requirements-dev.txt",
            ]
        )
    if args.command == "run":
        return run_command(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "main_api:app",
                "--host",
                "0.0.0.0",
                "--port",
                "8000",
            ]
        )
    if args.command == "test":
        return run_command(
            [
                sys.executable,
                "-X",
                "utf8",
                "scripts/coverage_check.py",
                "--fail-under",
                "80",
                "--verbosity",
                "2",
            ]
        )
    if args.command == "bench":
        first = run_command(
            [
                sys.executable,
                "-X",
                "utf8",
                "scripts/bench.py",
            ]
        )
        if first:
            return first
        second = run_command(
            [
                sys.executable,
                "-X",
                "utf8",
                "scripts/bench_scale.py",
            ]
        )
        if second:
            return second
        return run_command(
            [
                sys.executable,
                "-X",
                "utf8",
                "scripts/bench_api.py",
            ]
        )
    if args.command == "rag-eval":
        return run_command(
            [
                sys.executable,
                "-X",
                "utf8",
                "scripts/evaluate_rag.py",
                "--fail-under",
                "0.85",
            ]
        )
    if args.command == "rag-regression":
        return run_command(
            [
                sys.executable,
                "-X",
                "utf8",
                "scripts/evaluate_rag.py",
                "--embedder",
                "deterministic",
                "--fail-under",
                "0.85",
            ]
        )

    lint_commands = [
        [
            sys.executable,
            "-m",
            "compileall",
            "-q",
            "app",
            "scripts",
            "tests",
            "main.py",
            "main_api.py",
        ],
        [
            sys.executable,
            "-m",
            "pyflakes",
            "app",
            "scripts",
            "tests",
            "main.py",
            "main_api.py",
        ],
    ]
    for command in lint_commands:
        exit_code = run_command(command)
        if exit_code:
            return exit_code

    if args.command == "lint":
        return 0

    return run_command(
        [
            sys.executable,
            "-X",
            "utf8",
            "scripts/coverage_check.py",
            "--fail-under",
            "80",
            "--verbosity",
            "2",
        ]
    )


if __name__ == "__main__":
    raise SystemExit(main())
