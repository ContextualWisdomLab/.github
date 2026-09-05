"""Executable admission contract for merge-scheduler review events."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "pr-review-merge-scheduler.yml"


def scan_job_condition() -> str:
    """Return the normalized pre-runner condition for ``scan-pr-queue``."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    scan_job = workflow.split("\n  scan-pr-queue:\n", 1)[1]
    condition = scan_job.split("\n    runs-on:", 1)[0].split("\n    if: >-\n", 1)[1]
    return " ".join(line.strip() for line in condition.splitlines())


def admits_review_event(*, action: str, state: str) -> bool:
    """Evaluate the workflow's review-event condition for one trusted fixture."""
    expression = scan_job_condition().replace("&&", " and ").replace("||", " or ")
    expression = re.sub(r"\btrue\b", "True", expression)
    values = {
        "github.event_name": "pull_request_review",
        "github.event.action": action,
        "github.event.review.state": state,
        "github.event.client_payload.org_sweep": False,
    }

    def evaluate(node: ast.AST) -> object:
        """Interpret only the boolean/comparison subset used by the job guard."""
        if isinstance(node, ast.Expression):
            return evaluate(node.body)
        if isinstance(node, ast.BoolOp):
            operands = [bool(evaluate(value)) for value in node.values]
            return all(operands) if isinstance(node.op, ast.And) else any(operands)
        if isinstance(node, ast.Compare) and len(node.ops) == len(node.comparators) == 1:
            left = evaluate(node.left)
            right = evaluate(node.comparators[0])
            if isinstance(node.ops[0], ast.Eq):
                return left == right
            if isinstance(node.ops[0], ast.NotEq):
                return left != right
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, (ast.Attribute, ast.Name)):
            key = ast.unparse(node)
            if key in values:
                return values[key]
        raise AssertionError(f"unsupported scheduler expression node: {ast.dump(node)}")

    return bool(evaluate(ast.parse(expression, mode="eval")))


@pytest.mark.parametrize(
    ("action", "state", "expected"),
    [
        ("submitted", "commented", False),
        ("submitted", "approved", True),
        ("submitted", "changes_requested", True),
        ("dismissed", "commented", True),
    ],
)
def test_review_event_admission_truth_table(
    action: str, state: str, expected: bool
) -> None:
    """Admit only review transitions that can change merge eligibility."""
    assert admits_review_event(action=action, state=state) is expected


def test_review_filter_preserves_exact_pr_group_and_least_privilege() -> None:
    """Filtering COMMENTED reviews must not weaken scheduler trust boundaries."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert (
        "github.event_name == 'pull_request_review' && "
        "format('pr-{0}', github.event.pull_request.number)" in workflow
    )
    assert (
        "cancel-in-progress: ${{ github.event_name == 'pull_request_target' || "
        "github.event_name == 'pull_request_review' || "
        "github.event_name == 'repository_dispatch' }}" in workflow
    )
    assert "permissions:\n  contents: read" in workflow

    scan_header = workflow.split("\n  scan-pr-queue:\n", 1)[1].split(
        "\n    env:\n", 1
    )[0]
    for permission in (
        "actions: write",
        "checks: read",
        "contents: write",
        "id-token: write",
        "pull-requests: write",
    ):
        assert permission in scan_header
