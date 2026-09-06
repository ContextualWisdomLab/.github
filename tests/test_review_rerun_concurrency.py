"""Evaluate the real review group expressions without executing workflow code."""

import ast
import re
from pathlib import Path

import pytest


WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"
REVIEW_GROUPS = (
    ("strix.yml", None, "strix-security-scan"),
    ("noema-review.yml", None, "required-noema-review"),
    ("opencode-review.yml", None, "required-opencode-review"),
    ("strix.yml", "cancel-superseded-pr-runs", "cancel-superseded-pr-runs"),
    ("opencode-review-dispatch.yml", "opencode-review-target", "opencode-review"),
)


def expression_value(node: ast.AST, context: dict):
    """Interpret only this contract's literals, lookups, booleans, > and format."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return context[node.id]
    if isinstance(node, ast.Attribute):
        parent = expression_value(node.value, context)
        return parent.get(node.attr, "") if isinstance(parent, dict) else ""
    if isinstance(node, ast.BoolOp):
        for operand in node.values:
            value = expression_value(operand, context)
            if isinstance(node.op, ast.Or) and value:
                return value
            if isinstance(node.op, ast.And) and not value:
                return value
        return value
    if isinstance(node, ast.Compare) and len(node.ops) == 1:
        left = expression_value(node.left, context)
        right = expression_value(node.comparators[0], context)
        if isinstance(node.ops[0], ast.Gt):
            # GitHub coerces numeric strings for relational comparisons.
            return float(left) > float(right)
        if isinstance(node.ops[0], ast.Eq):
            assert isinstance(left, str) and isinstance(right, str)
            return left.casefold() == right.casefold()
        raise AssertionError("unsupported comparison")
    if isinstance(node, ast.Call):
        assert isinstance(node.func, ast.Name) and node.func.id == "format"
        assert not node.keywords and isinstance(node.args[0], ast.Constant)
        return node.args[0].value.format(
            *(expression_value(argument, context) for argument in node.args[1:])
        )
    raise AssertionError(f"unsupported group expression: {ast.dump(node)}")


def review_group(filename, job, *, run_id, attempt=1, pr=7,
                 repository="ContextualWisdomLab/example", dispatched=False,
                 event_name=None, ref="", ref_type=""):
    """Render the declared YAML group using an explicit event/needs snapshot."""
    source = (WORKFLOWS / filename).read_text(encoding="utf-8")
    if job:
        source = source.split(f"\n  {job}:\n", 1)[1]
        marker = "\n    concurrency:\n"
    else:
        marker = "\nconcurrency:\n"
    policy = source.split(marker, 1)[1]
    group, cancellation = policy.split("group: >-\n", 1)[1].split(
        "cancel-in-progress:", 1
    )
    assert cancellation.splitlines()[0].strip() == "true"
    event = (
        {"client_payload": {"target_repository": repository, "pr_number": str(pr)}}
        if dispatched else
        {"pull_request": {"base": {"repo": {"full_name": repository}}, "number": pr}}
    ) if pr else {}
    context = {
        "github": {"repository": repository, "run_id": str(run_id),
                   "run_attempt": attempt, "event": event,
                   "event_name": event_name or ("repository_dispatch" if dispatched else (
                       "pull_request_target" if pr else "unknown"
                   )), "ref": ref, "ref_type": ref_type},
        "needs": {"validate-pr-metadata": {"outputs": {
            "target_repository": repository, "pr_number": str(pr) if pr else "",
        }}},
    }

    def render(match):
        expression = match[1].strip().replace("&&", " and ").replace("||", " or ")
        # Hyphens in GitHub property names are dictionary keys, not subtraction.
        expression = expression.replace("needs.validate-pr-metadata", "metadata")
        tree = ast.parse(expression, mode="eval")
        return str(expression_value(tree.body, {
            **context, "metadata": context["needs"]["validate-pr-metadata"],
        }))

    return re.sub(r"\$\{\{(.*?)\}\}", render, " ".join(group.split()))


@pytest.mark.parametrize("filename,job,prefix", REVIEW_GROUPS)
@pytest.mark.parametrize("attempt", [2, "2", 3])
def test_old_rerun_cannot_cancel_current_pr_run(filename, job, prefix, attempt):
    """An older run retry must not share the current run's cancellation group."""
    current = review_group(filename, job, run_id=202)
    old_retry = review_group(filename, job, run_id=101, attempt=attempt)
    assert current == f"{prefix}-ContextualWisdomLab/example-7"
    assert old_retry == f"{prefix}-ContextualWisdomLab/example-rerun-101"
    assert old_retry != current
    assert old_retry != review_group(filename, job, run_id=202, attempt=2)


@pytest.mark.parametrize("filename,job,prefix", REVIEW_GROUPS)
def test_new_push_still_coalesces_only_its_pr(filename, job, prefix):
    """Run-ID isolation must not disable normal same-PR first-attempt cleanup."""
    current = review_group(filename, job, run_id=202)
    assert current == review_group(filename, job, run_id=101, attempt="1")
    assert current != review_group(filename, job, run_id=203, pr=8)
    assert current != review_group(
        filename, job, run_id=204, repository="ContextualWisdomLab/other"
    )
    assert review_group(filename, job, run_id=205, pr=None) != review_group(
        filename, job, run_id=206, pr=None
    )


@pytest.mark.parametrize("filename,prefix", [
    ("strix.yml", "strix-security-scan"),
    ("noema-review.yml", "required-noema-review"),
])
def test_dispatched_reviews_keep_pr_identity_and_rerun_isolation(filename, prefix):
    """Native and dispatched first attempts coalesce, but old dispatch retries do not."""
    assert review_group(filename, None, run_id=202, dispatched=True) == (
        f"{prefix}-ContextualWisdomLab/example-7"
    )
    assert review_group(filename, None, run_id=101, attempt=2, dispatched=True) == (
        f"{prefix}-ContextualWisdomLab/example-rerun-101"
    )


def test_opencode_dispatch_workflow_reruns_cannot_cancel_current_dispatch():
    """Workflow admission must isolate retries before the guarded job can start."""
    current = review_group(
        "opencode-review-dispatch.yml", None, run_id=202, dispatched=True
    )
    same_pr_first_attempt = review_group(
        "opencode-review-dispatch.yml", None, run_id=101, dispatched=True
    )
    old_retry = review_group(
        "opencode-review-dispatch.yml", None, run_id=101, attempt=2, dispatched=True
    )
    other_retry = review_group(
        "opencode-review-dispatch.yml", None, run_id=303, attempt=2, dispatched=True
    )

    assert current == "opencode-review-dispatch-ContextualWisdomLab/example-7"
    assert same_pr_first_attempt == current
    assert old_retry == "opencode-review-dispatch-ContextualWisdomLab/example-rerun-101"
    assert other_retry == "opencode-review-dispatch-ContextualWisdomLab/example-rerun-303"
    assert old_retry != current
    assert other_retry != old_retry


def test_strix_first_branch_push_coalesces_only_the_same_repository_and_ref():
    """A newer first branch push must replace only its same-branch predecessor."""
    current = review_group(
        "strix.yml", None, run_id=202, pr=None,
        event_name="push", ref_type="branch", ref="refs/heads/main",
    )
    assert current == "strix-security-scan-ContextualWisdomLab/example-refs/heads/main"
    assert current == review_group(
        "strix.yml", None, run_id=101, pr=None,
        event_name="push", ref_type="branch", ref="refs/heads/main",
    )
    assert current != review_group(
        "strix.yml", None, run_id=203, pr=None,
        event_name="push", ref_type="branch", ref="refs/heads/release",
    )
    assert current != review_group(
        "strix.yml", None, run_id=204, pr=None,
        repository="ContextualWisdomLab/other", event_name="push",
        ref_type="branch", ref="refs/heads/main",
    )


@pytest.mark.parametrize(
    "event_name,ref_type,ref",
    [
        ("push", "tag", "refs/tags/v1.0.0"),
        ("schedule", "", "refs/heads/main"),
        ("workflow_dispatch", "branch", "refs/heads/main"),
        ("repository_dispatch", "branch", "refs/heads/main"),
        ("unknown", "", "refs/heads/main"),
        ("push", "branch", ""),
    ],
)
def test_strix_non_branch_push_first_attempts_remain_run_isolated(
    event_name, ref_type, ref,
):
    """Non-branch-push events and missing refs must not cancel sibling runs."""
    first = review_group(
        "strix.yml", None, run_id=101, pr=None,
        event_name=event_name, ref_type=ref_type, ref=ref,
    )
    second = review_group(
        "strix.yml", None, run_id=202, pr=None,
        event_name=event_name, ref_type=ref_type, ref=ref,
    )
    assert first == "strix-security-scan-ContextualWisdomLab/example-101"
    assert second == "strix-security-scan-ContextualWisdomLab/example-202"


def test_strix_old_branch_push_rerun_remains_run_isolated():
    """A branch-push rerun must not cancel a newer first attempt."""
    assert review_group(
        "strix.yml", None, run_id=101, attempt=2, pr=None,
        event_name="push", ref_type="branch", ref="refs/heads/main",
    ) == "strix-security-scan-ContextualWisdomLab/example-rerun-101"
