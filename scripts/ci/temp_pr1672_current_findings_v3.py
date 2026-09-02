#!/usr/bin/env python3
"""Align PR #1672 regression fixtures with the reviewed timeout and telemetry semantics."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TELEMETRY = ROOT / "tests/test_noema_repair_attempt_telemetry.py"
FAILURE = ROOT / "tests/test_noema_model_output_failure_classification.py"
SELF = Path(__file__).resolve()


def replace_exact(text: str, old: str, new: str, *, count: int, label: str) -> str:
    """Replace an exact expected number of fragments and fail closed on drift."""
    observed = text.count(old)
    if observed != count:
        raise RuntimeError(f"{label}: expected {count} matches, found {observed}")
    return text.replace(old, new)


def repair_telemetry_tests() -> None:
    """Make old syntax-repair and new citation tests assert the same truthful contract."""
    text = TELEMETRY.read_text(encoding="utf-8")
    text = replace_exact(
        text,
        '    assert "no network repair retry was needed" in notice\n',
        '    assert "before verdict validation" in notice\n'
        '    assert "semantic validation may still require" in notice\n'
        '    assert "no network repair retry was needed" not in notice\n',
        count=1,
        label="legacy local-repair notice assertion",
    )
    text = replace_exact(
        text,
        '    assert "nearest changed lines for README.md: README.md:1 (RIGHT)" in reviewed\n',
        '    assert "nearest changed lines for README.md:" in reviewed\n'
        '    assert "README.md:1 (RIGHT)" in reviewed\n',
        count=1,
        label="reviewed-line nearest-location assertion",
    )
    text = replace_exact(
        text,
        '    assert "nearest changed lines for README.md: README.md:1 (RIGHT)" in probe\n',
        '    assert "nearest changed lines for README.md:" in probe\n'
        '    assert "README.md:1 (RIGHT)" in probe\n',
        count=1,
        label="probe nearest-location assertion",
    )
    TELEMETRY.write_text(text, encoding="utf-8")


def remove_retired_deadline_tests() -> None:
    """Remove tests for the fixed SIGALRM deadline that the reviewed repair intentionally retires."""
    text = FAILURE.read_text(encoding="utf-8")
    tree = ast.parse(text)
    spans: list[tuple[int, int]] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith(
            "test_repair_deadline_"
        ):
            start = min([node.lineno, *(decorator.lineno for decorator in node.decorator_list)])
            if node.end_lineno is None:
                raise RuntimeError(f"missing end line for {node.name}")
            spans.append((start, node.end_lineno))
    expected = {
        "test_repair_deadline_rejects_nonpositive_budget",
        "test_repair_deadline_requires_setitimer",
        "test_repair_deadline_requires_itimer_real",
        "test_repair_deadline_refuses_existing_process_alarm",
        "test_repair_deadline_requires_main_thread_signal_registration",
    }
    observed = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_repair_deadline_")
    }
    if observed != expected:
        raise RuntimeError(f"retired deadline test set drifted: {sorted(observed)}")
    lines = text.splitlines(keepends=True)
    for start, end in sorted(spans, reverse=True):
        del lines[start - 1 : end]
    FAILURE.write_text("".join(lines), encoding="utf-8")


def main() -> int:
    """Align tests with the source contract and retire this one-shot helper."""
    repair_telemetry_tests()
    remove_retired_deadline_tests()
    SELF.unlink()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
