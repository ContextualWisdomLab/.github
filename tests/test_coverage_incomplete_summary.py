"""Execute the actual decision block: missing evidence must not be called PASS."""

from pathlib import Path
import subprocess

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/opencode-review-dispatch.yml"


def summary(failures: int, not_measured: int) -> str:
    text = WORKFLOW.read_text(encoding="utf-8")
    start = text.index('          append "## Coverage Decision"')
    end = text.index('          coverage_output_file=', start)
    block = "\n".join(line[10:] for line in text[start:end].splitlines())
    script = (
        f"set -eu\nfailures={failures}; not_measured={not_measured}; "
        "measured_any=1; r_peer_check_required=0\n"
        'append(){ printf "%s\\n" "$*"; }\n' + block
    )
    return subprocess.run(["bash", "-c", script], check=True, capture_output=True, text=True).stdout


def test_timeout_is_incomplete_not_success_evidence() -> None:
    output = summary(0, 1)
    assert "- Result: NOT MEASURED" in output
    assert "- Result: PASS" not in output
    assert "supported repository test suites passed" not in output
    assert "does not replace required verification" in output


def test_real_failure_wins_over_incomplete_measurements() -> None:
    assert "- Result: FAIL" in summary(1, 1)


def test_complete_success_still_passes() -> None:
    assert "- Result: PASS" in summary(0, 0)


def approval_prefix(decision: str) -> subprocess.CompletedProcess[str]:
    """Run the real APPROVE preconditions with a successful advisory job."""
    text = WORKFLOW.read_text(encoding="utf-8")
    helper_start = text.index("          coverage_decision_is_pass() {")
    helper_end = text.index("\n          }", helper_start) + len("\n          }")
    helper = "\n".join(
        line[10:] for line in text[helper_start:helper_end].splitlines()
    )
    start = text.index("            APPROVE)") + len("            APPROVE)")
    end = text.index("              if request_changes_for_merge_conflict_if_present", start)
    block = "\n".join(line[14:] for line in text[start:end].splitlines())
    script = (
        "set -eu\nCOVERAGE_EVIDENCE_RESULT=success\n"
        'COVERAGE_EVIDENCE_SUMMARY="$1"\n'
        'stop_approval_without_review(){ printf "%s\\n" "$1"; exit 1; }\n'
        + helper
        + "\n"
        + block
        + '\nprintf "approval_allowed\\n"\n'
    )
    return subprocess.run(["bash", "-c", script, "test", decision], capture_output=True, text=True)


def test_successful_advisory_job_cannot_approve_unmeasured_coverage() -> None:
    result = approval_prefix(summary(0, 1))
    assert result.returncode == 1
    assert "COVERAGE_NOT_MEASURED" in result.stdout
    assert "approval_allowed" not in result.stdout


def test_missing_or_ambiguous_decision_fails_closed_before_approval() -> None:
    for decision in (
        "",
        "- Result: UNKNOWN",
        "prefix - Result: PASS",
        "- Result: PASS (assumed)",
        "- Result: PASS\n- Result: NOT MEASURED",
        "- Result: PASS\n- Result: PASS",
    ):
        assert approval_prefix(decision).returncode == 1, decision


def test_complete_decision_can_reach_remaining_approval_checks() -> None:
    result = approval_prefix(summary(0, 0))
    assert result.returncode == 0
    assert "approval_allowed" in result.stdout
