"""Contract: central Strix releases no-progress, never elapsed-time work."""

from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "strix.yml"
COMPAT = ROOT / "scripts" / "ci" / "strix_timeout_compat.py"
DOCTORING = ROOT / "docs" / "doctoring" / "strix-unbounded-agentic-occupancy-20260918.md"
ADR = ROOT / "docs" / "adr" / "0034-review-runner-occupancy-progress-bound.md"


def _strix_job_header() -> str:
    """Return the strix job header up to its first steps: block."""
    text = WORKFLOW.read_text(encoding="utf-8")
    match = re.search(r"^  strix:\n(.*?)(?=^    steps:\n)", text, flags=re.MULTILINE | re.DOTALL)
    assert match is not None, "strix job header not found"
    return match.group(0)


def test_strix_job_has_no_elapsed_occupancy_timeout() -> None:
    """Active reasoning or streaming must not end because wall time elapsed."""
    header = _strix_job_header()
    assert "timeout-minutes:" not in header
    workflow = WORKFLOW.read_text(encoding="utf-8")
    compat = COMPAT.read_text(encoding="utf-8")
    assert 'STREAM_IDLE_OCCUPANCY_SECONDS = "90"' in compat
    assert 'environment["LLM_STREAM_IDLE_TIMEOUT"] = STREAM_IDLE_OCCUPANCY_SECONDS' in compat
    assert "export STRIX_PROCESS_TIMEOUT_SECONDS=0" in workflow
    assert "export STRIX_TOTAL_TIMEOUT_SECONDS=0" in workflow
    assert "35263416380" in workflow
    assert DOCTORING.is_file()
    assert "35263416380" in DOCTORING.read_text(encoding="utf-8")
    assert ADR.is_file()
    assert "elapsed inference" in ADR.read_text(encoding="utf-8").lower()


def test_required_strix_job_id_stays_stable() -> None:
    """Keep the required check context name `strix` unchanged."""
    text = WORKFLOW.read_text(encoding="utf-8")
    assert re.search(r"^  strix:\n", text, flags=re.MULTILINE)
