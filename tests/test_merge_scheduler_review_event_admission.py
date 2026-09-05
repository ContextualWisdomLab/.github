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


def cancellation_condition() -> str:
    """Return the normalized workflow-level cancellation expression."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    marker = "\n  cancel-in-progress: "
    raw = workflow.split(marker, 1)[1]
    if raw.startswith(">-\n"):
        condition = raw.split("\n\n", 1)[0].removeprefix(">-\n")
    else:
        condition = raw.splitlines()[0]
    normalized = " ".join(line.strip() for line in condition.splitlines())
    assert normalized.startswith("${{ ") and normalized.endswith(" }}")
    return normalized.removeprefix("${{ ").removesuffix(" }}")


def evaluate_review_expression(
    *, expression: str, action: str, state: str, event_name: str = "pull_request_review"
) -> bool:
    """Evaluate a workflow review-event expression for one trusted fixture."""
    expression = expression.replace("&&", " and ").replace("||", " or ")
    expression = re.sub(r"\btrue\b", "True", expression)
    values = {
        "github.event_name": event_name,
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


def admits_review_event(*, action: str, state: str) -> bool:
    """Evaluate the pre-runner admission condition for one review fixture."""
    return evaluate_review_expression(
        expression=scan_job_condition(), action=action, state=state
    )


def cancels_predecessor(
    *, action: str, state: str, event_name: str = "pull_request_review"
) -> bool:
    """Evaluate whether one review event cancels the prior scheduler run."""
    return evaluate_review_expression(
        expression=cancellation_condition(),
        action=action,
        state=state,
        event_name=event_name,
    )


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


def test_commented_review_does_not_cancel_approved_review_execution() -> None:
    """A later COMMENTED review must preserve an approved scheduler execution."""
    assert cancels_predecessor(action="submitted", state="approved") is True
    assert cancels_predecessor(action="submitted", state="commented") is False
    assert cancels_predecessor(action="submitted", state="changes_requested") is True
    assert cancels_predecessor(action="dismissed", state="commented") is True


@pytest.mark.parametrize(
    ("event_name", "expected"),
    [
        ("pull_request_target", True),
        ("repository_dispatch", True),
        ("push", False),
        ("schedule", False),
        ("workflow_call", False),
    ],
)
def test_review_filter_preserves_non_review_cancellation_semantics(
    event_name: str, expected: bool
) -> None:
    """Narrow only review-event cancellation, preserving other trigger behavior."""
    assert (
        cancels_predecessor(
            event_name=event_name, action="submitted", state="commented"
        )
        is expected
    )
