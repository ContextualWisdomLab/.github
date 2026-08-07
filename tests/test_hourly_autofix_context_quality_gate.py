"""Contract tests for exact-head quality evidence of autofix context production."""

import hashlib
from pathlib import Path

from scripts.ci import pr_review_autofix_context as context


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


def test_context_helper_covers_unknown_checks_and_explicit_path_output(
    monkeypatch, tmp_path: Path
) -> None:
    """Exercise fail-closed status filtering and the explicit sealed-output CLI path."""
    head = "a" * 40
    pull_request = {
        "number": 7,
        "title": "Bound context authority",
        "url": "https://example.invalid/pull/7",
        "headRefName": "feature",
        "baseRefName": "main",
        "headRefOid": head,
        "baseRefOid": "b" * 40,
        "mergeStateStatus": "CLEAN",
        "statusCheckRollup": [{"__typename": "UnknownStatusNode"}],
    }
    monkeypatch.setattr(context, "pr_view", lambda _repo, _number: pull_request)
    monkeypatch.setattr(
        context,
        "current_reviews",
        lambda _repo, _number, _head_sha: [],
    )
    monkeypatch.setattr(context, "review_threads", lambda _repo, _number: [])

    assert context.check_summary(pull_request["statusCheckRollup"]) == []

    markdown_output = tmp_path / "context.md"
    allowed_paths_output = tmp_path / "explicit-allowed-paths.zlist"
    assert (
        context.main(
            [
                "--repo",
                "owner/repo",
                "--pr-number",
                "7",
                "--head-sha",
                head,
                "--output",
                str(markdown_output),
                "--allowed-paths-output",
                str(allowed_paths_output),
            ]
        )
        == 0
    )
    assert allowed_paths_output.read_bytes() == b""
    assert Path(f"{allowed_paths_output}.sha256").read_text(encoding="ascii") == (
        f"{hashlib.sha256(b'').hexdigest()}\n"
    )
    assert markdown_output.is_file()
