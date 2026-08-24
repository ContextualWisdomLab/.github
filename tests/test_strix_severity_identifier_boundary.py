"""Regression contracts for Strix severity marker identity boundaries."""

from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "scripts" / "ci" / "strix_quick_gate.sh"


def _function(source: str, name: str) -> str:
    start = source.index(f"{name}() {{")
    cursor = start
    depth = 0
    while cursor < len(source):
        line_end = source.find("\n", cursor)
        if line_end < 0:
            line_end = len(source)
        line = source[cursor:line_end]
        depth += line.count("{") - line.count("}")
        if depth == 0:
            return source[start:line_end] + "\n"
        cursor = line_end + 1
    raise AssertionError(f"unterminated shell function: {name}")


def _extract_rank(report: Path) -> int:
    source = GATE.read_text(encoding="utf-8")
    script = "set -euo pipefail\n" + _function(source, "severity_rank")
    script += _function(source, "extract_max_severity_rank")
    script += 'extract_max_severity_rank "$1"\n'
    completed = subprocess.run(
        ["bash", "-c", script, "bash", str(report)],
        check=True,
        capture_output=True,
        text=True,
    )
    return int(completed.stdout.strip())


def test_severity_identifier_suffix_does_not_promote_low_finding(tmp_path: Path) -> None:
    report = tmp_path / "report.md"
    report.write_text(
        "STRIX_FAIL_ON_MIN_SEVERITY: CRITICAL\nSeverity: LOW\n",
        encoding="utf-8",
    )

    assert _extract_rank(report) == 1


def test_severity_identifier_suffix_is_not_authoritative_finding(tmp_path: Path) -> None:
    report = tmp_path / "report.md"
    report.write_text("STRIX_FAIL_ON_MIN_SEVERITY: CRITICAL\n", encoding="utf-8")

    assert _extract_rank(report) == -1


def test_all_severity_marker_paths_share_identifier_boundary() -> None:
    source = GATE.read_text(encoding="utf-8")

    assert '[[ "${line^^}" =~ (^|[^A-Za-z0-9_])SEVERITY' in source
    assert "grep -Ei '(^|[^A-Za-z0-9_])severity[[:space:][:punct:]]*:'" in source
    assert (
        source.count(
            "grep -Eiq '(^|[^A-Za-z0-9_])severity[[:space:][:punct:]]*:'"
        )
        >= 2
    )
