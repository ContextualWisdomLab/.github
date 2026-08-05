"""Regression tests for Strix source-directory input boundaries."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts" / "ci" / "strix_model_utils.sh"
DIAGNOSTICS_WORKFLOW = ROOT / ".github" / "workflows" / "opencode-coverage-diagnostics-ci.yml"


def run_source(raw_value: str) -> subprocess.CompletedProcess[str]:
    """Source the helper with one caller-controlled directory-list value."""

    environment = os.environ.copy()
    environment["STRIX_SOURCE_DIRS"] = raw_value
    return subprocess.run(
        [
            "bash",
            "-c",
            f'source "{HELPER}" || exit $?; printf "%s" "$STRIX_SOURCE_DIRS"',
        ],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )


def test_direct_source_directories_are_normalized_and_readonly() -> None:
    """Keep direct safe names, Unicode names, and first-occurrence order."""

    completed = run_source(". src 데이터 backend src 데이터")
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == ". src 데이터 backend"

    reassignment = subprocess.run(
        [
            "bash",
            "-c",
            (
                f'STRIX_SOURCE_DIRS="."; source "{HELPER}"; '
                'STRIX_SOURCE_DIRS="../etc"'
            ),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )
    assert reassignment.returncode != 0
    assert "readonly" in reassignment.stderr.lower()


def test_traversal_absolute_nested_glob_and_empty_values_fail_closed() -> None:
    """Reject every path shape that can escape or broaden the scan root."""

    unsafe_values = (
        "..",
        "../etc",
        "/etc",
        "src/../etc",
        "src/api",
        "*",
        "src[0-9]",
        "src]",
        "-rf",
        "   ",
        "src\nbackend",
    )
    for raw_value in unsafe_values:
        completed = run_source(raw_value)
        assert completed.returncode == 2, (
            raw_value,
            completed.stdout,
            completed.stderr,
        )
        assert "STRIX_SOURCE_DIRS" in completed.stderr


def test_unsafe_punctuation_and_oversized_lists_fail_closed() -> None:
    """Bound metacharacters, encoded size, and list cardinality."""

    for raw_value in ("src;echo", "src$HOME", "src\\api", "src?"):
        completed = run_source(raw_value)
        assert completed.returncode == 2, raw_value

    oversized_entry = "a" * 256
    assert run_source(oversized_entry).returncode == 2

    oversized_list = " ".join(f"dir{index}" for index in range(33))
    assert run_source(oversized_list).returncode == 2


def test_permanent_diagnostics_runs_for_source_boundary_changes() -> None:
    """Bind source-directory boundary edits to exact-head executable evidence."""

    workflow = DIAGNOSTICS_WORKFLOW.read_text(encoding="utf-8")

    assert workflow.count('      - "scripts/ci/strix_model_utils.sh"') == 2
    assert workflow.count('      - "tests/test_strix_model_utils_source_dirs.py"') == 2
    assert (
        "            tests/test_strix_model_utils_source_dirs.py " + chr(92)
        in workflow
    )
    assert "            tests/test_strix_model_utils_source_dirs.py" in workflow
