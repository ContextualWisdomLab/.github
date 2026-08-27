"""Regression tests for exact coverage identity and status publication."""

from __future__ import annotations

import inspect
from pathlib import Path

from scripts.ci import opencode_coverage_identity as identity
from scripts.ci import opencode_review_receipt_gate as receipt_gate


HEAD = "a" * 40
WORKFLOW = Path(".github/workflows/opencode-review-dispatch.yml")


def step_block(workflow: str, name: str) -> str:
    """Return one named Actions step block."""
    marker = f"      - name: {name}\n"
    start = workflow.index(marker)
    end = workflow.find("\n      - name: ", start + len(marker))
    return workflow[start:] if end < 0 else workflow[start:end]


def function_block(workflow: str, name: str) -> str:
    """Return one shell function body from the workflow."""
    marker = f"          {name}() {{\n"
    start = workflow.index(marker)
    end = workflow.find("\n          }\n", start + len(marker))
    assert end >= 0
    return workflow[start : end + len("\n          }\n")]


def coverage_check(*, run_id: str, conclusion: str) -> dict[str, object]:
    """Build an otherwise indistinguishable exact-head coverage check."""
    return {
        "name": "coverage-evidence",
        "head_sha": HEAD,
        "status": "completed",
        "conclusion": conclusion,
        "details_url": (
            f"https://github.com/ContextualWisdomLab/.github/actions/runs/{run_id}/job/1"
        ),
        "check_suite": {},
        "app": {"name": "GitHub Actions"},
    }


def test_initial_overview_resolves_current_run_coverage_identity() -> None:
    """The initial overview must not default a passing coverage result to unknown."""
    step = step_block(WORKFLOW.read_text(encoding="utf-8"), "Publish bounded OpenCode review comment")

    assert (
        "COVERAGE_EVIDENCE_RESULT: "
        "${{ needs.coverage-evidence.result || 'skipped' }}" in step
    )
    assert '--run-id "$RUN_ID"' in step
    assert '--workflow-repo "$GITHUB_REPOSITORY"' in step
    assert '--pr-number "$PR_NUMBER"' in step
    assert "opencode_coverage_identity.py" in step
    assert step.index("opencode_coverage_identity.py") < step.index("build-status")


def test_all_runtime_coverage_identity_calls_use_central_dispatch_authority() -> None:
    """Every caller must bind the target head to the exact central workflow run."""
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert workflow.count('--workflow-repo "$GITHUB_REPOSITORY"') == 3
    assert workflow.count('--pr-number "$PR_NUMBER"') == 3


def test_duplicate_coverage_names_are_bound_to_the_current_dispatch_run() -> None:
    """A success stub from another run cannot shadow the real failed coverage job."""
    parameters = inspect.signature(identity.terminal_coverage_result).parameters
    assert "run_id" in parameters
    checks = [
        coverage_check(run_id="111", conclusion="success"),
        coverage_check(run_id="222", conclusion="failure"),
    ]
    assert identity.terminal_coverage_result(checks, HEAD, run_id="222") == "failure"


def test_coverage_failure_helper_does_not_render_an_unused_body() -> None:
    """Unused rendering must not abort the source-backed coverage-block review."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    helper = function_block(workflow, "request_changes_for_coverage_evidence_failure")

    assert "build_coverage_evidence_check_failure_body" not in helper
    assert "body_file" not in helper
    assert 'update_review_overview "COVERAGE_BLOCKED"' in helper


def test_receipt_gate_recognizes_the_emitted_overview_heading() -> None:
    """The receipt heuristic must recognize the English status-only surface."""
    assert "## OpenCode Review Overview" in receipt_gate.STATUS_HEADINGS


def test_outcome_publisher_does_not_query_status_comment_for_control_sentinel() -> None:
    """The status-only overview cannot be a source for the formal review control."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    outcome = workflow.split("- name: Publish OpenCode review outcome", 1)[1]
    outcome = outcome.split("- name: Enforce current-head formal OpenCode review receipt", 1)[0]

    assert "sentinel_comment_error_file" not in outcome
    assert "Review Overview sentinel comment" not in outcome
    assert 'load_selected_review_output "$selected_review_output_file"' in outcome
