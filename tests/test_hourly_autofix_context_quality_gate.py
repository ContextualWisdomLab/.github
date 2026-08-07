"""Contract tests for exact-head quality evidence of autofix context production."""

from pathlib import Path


WORKFLOW = Path(".github/workflows/hourly-nvidia-nim-review-repair.yml")


def test_context_helper_is_part_of_the_focused_exact_head_quality_gate() -> None:
    """Require trigger, test, coverage, docstring, and compile evidence together."""
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert workflow.count("- scripts/ci/pr_review_autofix_context.py") == 2
    assert workflow.count("- tests/test_pr_review_fix_scheduler.py") == 2
    assert workflow.count("- tests/test_hourly_autofix_context_quality_gate.py") == 2
    assert "tests/test_pr_review_fix_scheduler.py \\" in workflow
    assert "tests/test_hourly_autofix_context_quality_gate.py \\" in workflow
    assert "--cov=scripts.ci.pr_review_autofix_context \\" in workflow
    assert (
        "scripts/ci/pr_review_conflict_scope.py \\\n"
        "            scripts/ci/pr_review_autofix_context.py"
    ) in workflow
    assert (
        "scripts/ci/pr_review_conflict_scope.py \\\n"
        "            scripts/ci/pr_review_autofix_context.py \\\n"
        "            tests/test_pr_review_conflict_scope.py"
    ) in workflow
