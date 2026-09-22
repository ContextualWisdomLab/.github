"""Fail-closed contract for mandatory Strix evidence inputs."""

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
