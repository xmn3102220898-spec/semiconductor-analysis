"""Run tests and report line coverage using Python's standard library."""

from __future__ import annotations

import argparse
import ast
import os
import sys
import time
import unittest
from pathlib import Path
from trace import Trace


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _executable_lines(source_path: Path) -> set[int]:
    tree = ast.parse(
        source_path.read_text(encoding="utf-8"),
        filename=str(source_path),
    )
    statement_types = (
        ast.Return,
        ast.Assign,
        ast.AnnAssign,
        ast.AugAssign,
        ast.Expr,
        ast.If,
        ast.For,
        ast.AsyncFor,
        ast.While,
        ast.Try,
        ast.With,
        ast.AsyncWith,
        ast.Raise,
        ast.Assert,
        ast.Delete,
        ast.Break,
        ast.Continue,
        ast.Pass,
        ast.ExceptHandler,
    )
    ignored_lines: set[int] = set()

    for node in tree.body:
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if (
            isinstance(test, ast.Compare)
            and isinstance(test.left, ast.Name)
            and test.left.id == "__name__"
        ):
            ignored_lines.update(
                child.lineno
                for statement in node.body
                for child in ast.walk(statement)
                if hasattr(child, "lineno")
            )
            ignored_lines.add(node.lineno)

    lines = {
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, statement_types)
        and not (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        )
        and not (
            isinstance(node, ast.AnnAssign)
            and node.value is None
        )
        and node.lineno not in ignored_lines
    }
    return lines


def _coverage_for_file(
    source_path: Path,
    counts: dict[tuple[str, int], int],
) -> tuple[int, int]:
    executable = _executable_lines(source_path)
    resolved = str(source_path.resolve()).lower()
    executed = {
        line_number
        for (filename, line_number), count in counts.items()
        if count > 0
        and str(Path(filename).resolve()).lower() == resolved
    }
    return len(executable & executed), len(executable)


def _percentage(hit: int, total: int) -> float:
    return (hit / total * 100) if total else 100.0


def run(verbosity: int, fail_under: float) -> int:
    os.environ.setdefault("LOG_LEVEL", "CRITICAL")
    project_root_text = str(PROJECT_ROOT)
    if project_root_text not in sys.path:
        sys.path.insert(0, project_root_text)

    suite = unittest.defaultTestLoader.discover(
        str(PROJECT_ROOT / "tests"),
        pattern="test*.py",
    )
    runner = unittest.TextTestRunner(verbosity=verbosity)
    tracer = Trace(
        count=True,
        trace=False,
        ignoredirs=[sys.prefix, sys.exec_prefix],
    )

    started_at = time.perf_counter()
    result = tracer.runfunc(runner.run, suite)
    elapsed = time.perf_counter() - started_at
    counts = tracer.results().counts

    analysis_files = sorted(
        (PROJECT_ROOT / "app" / "analysis").glob("*.py")
    )
    app_files = sorted(
        path
        for path in (PROJECT_ROOT / "app").rglob("*.py")
        if "__pycache__" not in path.parts
    )

    print("\nLine coverage (standard-library trace):")
    core_hit = 0
    core_total = 0

    for source_path in app_files:
        hit, total = _coverage_for_file(source_path, counts)
        relative = source_path.relative_to(PROJECT_ROOT)
        print(
            f"  {relative.as_posix():38s} "
            f"{_percentage(hit, total):6.2f}%  ({hit}/{total})"
        )
        if source_path in analysis_files:
            core_hit += hit
            core_total += total

    core_percentage = _percentage(core_hit, core_total)
    print(
        f"\nCore analysis coverage: {core_percentage:.2f}% "
        f"({core_hit}/{core_total})"
    )
    print(f"Test duration: {elapsed:.3f}s")

    if not result.wasSuccessful():
        return 1
    if core_percentage < fail_under:
        print(
            f"Coverage gate failed: {core_percentage:.2f}% "
            f"< {fail_under:.2f}%"
        )
        return 1

    print(f"Coverage gate passed: >= {fail_under:.2f}%")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fail-under", type=float, default=80.0)
    parser.add_argument("--verbosity", type=int, default=1)
    args = parser.parse_args()
    return run(args.verbosity, args.fail_under)


if __name__ == "__main__":
    raise SystemExit(main())
