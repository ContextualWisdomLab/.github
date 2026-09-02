"""Executable contract for one formal OpenCode verdict authority across workflows."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

from scripts.ci import opencode_review_receipt_gate as receipt_gate


REQUIRED_WORKFLOW_PATH = Path(".github/workflows/opencode-review.yml")
SCHEDULER_WORKFLOW_PATH = Path(".github/workflows/pr-review-merge-scheduler.yml")
HEAD_SHA = "a" * 40


def _embedded_jq_program(workflow_text: str, variable_name: str, sha_variable: str) -> str:
    """Extract one tracked jq selector so the test executes production policy text."""
    assignment_marker = f'{variable_name}="$(printf'
    assignment_tail = workflow_text.split(assignment_marker, 1)[1]
    jq_marker = f'| jq -r -s --arg sha "${sha_variable}" \'\n'
    jq_tail = assignment_tail.split(jq_marker, 1)[1]
    return jq_tail.split("\n          ')\"", 1)[0]


def _run_selector(program: str, review: dict[str, object]) -> str:
    """Execute a production jq verdict selector against one paginated review page."""
    completed = subprocess.run(
        ["jq", "-r", "-s", "--arg", "sha", HEAD_SHA, program],
        input=json.dumps([review]),
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout.strip()


def _formal_review(author: str, state: str, body: str) -> dict[str, object]:
    """Build a current-head formal review fixture shared across policy surfaces."""
    return {
        "id": 7,
        "user": {"login": author},
        "commit_id": HEAD_SHA,
        "state": state,
        "submitted_at": "2026-09-02T13:00:01Z",
        "body": body,
    }


def test_github_actions_formal_change_request_matches_all_verdict_surfaces() -> None:
    """A publisher accepted by the receipt gate must reconcile and admit the same verdict."""
    review = _formal_review(
        "github-actions[bot]",
        "CHANGES_REQUESTED",
        "## Pull request overview\nmodel-unavailable evidence fallback",
    )
    accepted, reason = receipt_gate.is_formal_receipt(review, HEAD_SHA, is_draft=False)
    assert accepted, reason

    required_text = REQUIRED_WORKFLOW_PATH.read_text(encoding="utf-8")
    scheduler_text = SCHEDULER_WORKFLOW_PATH.read_text(encoding="utf-8")
    admission_program = _embedded_jq_program(required_text, "verdict", "HEAD_SHA")
    reconciliation_program = _embedded_jq_program(
        scheduler_text, "latest_review", "PR_HEAD_SHA"
    )

    assert _run_selector(admission_program, review) == "CHANGES_REQUESTED"
    assert _run_selector(reconciliation_program, review).startswith(
        "CHANGES_REQUESTED\t"
    )


def test_fallback_marker_invalidates_approval_only_not_change_request() -> None:
    """Fallback markers reject APPROVED evidence but never erase a real change request."""
    fallback_body = "## Pull request overview\ndeterministic fallback approval"
    change_request = _formal_review("opencode-agent[bot]", "CHANGES_REQUESTED", fallback_body)
    approval = _formal_review("opencode-agent[bot]", "APPROVED", fallback_body)

    change_ok, change_reason = receipt_gate.is_formal_receipt(
        change_request, HEAD_SHA, is_draft=False
    )
    approval_ok, _approval_reason = receipt_gate.is_formal_receipt(
        approval, HEAD_SHA, is_draft=False
    )
    assert change_ok, change_reason
    assert not approval_ok

    required_text = REQUIRED_WORKFLOW_PATH.read_text(encoding="utf-8")
    scheduler_text = SCHEDULER_WORKFLOW_PATH.read_text(encoding="utf-8")
    admission_program = _embedded_jq_program(required_text, "verdict", "HEAD_SHA")
    reconciliation_program = _embedded_jq_program(
        scheduler_text, "latest_review", "PR_HEAD_SHA"
    )

    assert _run_selector(admission_program, change_request) == "CHANGES_REQUESTED"
    assert _run_selector(reconciliation_program, change_request).startswith(
        "CHANGES_REQUESTED\t"
    )
    assert _run_selector(admission_program, approval) == ""
    # _run_selector intentionally strips jq's trailing whitespace, so an empty
    # scheduler state/timestamp tuple is observed as the empty string rather
    # than a literal tab. This keeps the oracle causal instead of depending on
    # incidental transport whitespace.
    assert _run_selector(reconciliation_program, approval) == ""
