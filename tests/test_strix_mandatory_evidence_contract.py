"""Fail-closed contract for mandatory Strix evidence inputs."""

import subprocess
from pathlib import Path


GATE = Path("scripts/ci/strix_quick_gate.sh")


def test_missing_log_report_root_and_structured_report_are_hard_errors() -> None:
    """Absent evidence must return configuration failure, never success/neutral."""
    source = GATE.read_text(encoding="utf-8")
    assert "Strix evidence log is missing or unsafe" in source
    assert "Strix evidence report root is missing or unsafe" in source
    assert "Strix structured evidence report is missing" in source
    start = source.index("sanitize_remediation_evidence_claims()")
    end = source.index("\nhas_strix_report_failure_signal()", start)
    function = source[start:end]
    assert function.count("return 2") >= 4
    assert "return 0" not in function


def test_recursive_symlinks_are_rejected_before_copy_or_sanitization() -> None:
    """Nested symlinks cannot escape either evidence boundary."""
    source = GATE.read_text(encoding="utf-8")
    assert 'reject_tree_symlinks "$report_root"' in source
    assert 'reject_tree_symlinks "$STRIX_SCAN_OUTPUT_DIR"' in source
    symlink_check = source.index('reject_tree_symlinks "$STRIX_SCAN_OUTPUT_DIR"')
    evidence_copy = source.index(
        'cp -R -- "$STRIX_SCAN_OUTPUT_DIR"/. "$ACTIVE_REPORTS_DIR"/', symlink_check
    )
    assert symlink_check < evidence_copy
    assert "-o -type f -path '*/vulnerabilities/*.md'" in source


def test_recursive_symlink_guard_rejects_nested_link_at_runtime(tmp_path) -> None:
    """The production guard returns rc=2 for a link below a regular root."""
    root = tmp_path / "reports"
    nested = root / "nested"
    nested.mkdir(parents=True)
    (nested / "escape").symlink_to(tmp_path / "outside")

    source = GATE.read_text(encoding="utf-8")
    start = source.index("reject_tree_symlinks()")
    end = source.index("\n# Issue #2168", start)
    function = source[start:end]
    harness = tmp_path / "guard.sh"
    harness.write_text(
        "set -u\n"
        + function
        + f'\nreject_tree_symlinks "{root}" "test evidence"\n',
        encoding="utf-8",
    )
    result = subprocess.run(
        ["bash", str(harness)], text=True, capture_output=True, check=False
    )
    assert result.returncode == 2
    assert "contains a symbolic link" in result.stderr
