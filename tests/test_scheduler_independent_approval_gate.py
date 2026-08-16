"""Regression tests for exact-head independent scheduler approval gates."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts.ci import pr_review_merge_scheduler as sched


HEAD_SHA = "a" * 40
BASE_SHA = "b" * 40
ROOT = Path(__file__).resolve().parents[1]


def review(
    login: str,
    *,
    state: str = "APPROVED",
    commit: str = HEAD_SHA,
) -> dict[str, Any]:
    """Return one formal review fixture anchored to a specific commit."""
    return {
        "state": state,
        "author": {"login": login},
        "submittedAt": "2026-08-07T18:00:00Z",
        "commit": {"oid": commit},
        "body": f"Head SHA: `{commit}`",
    }


def make_pr(
    *,
    review_decision: str,
    extra_reviews: list[dict[str, Any]] | None = None,
    author: str = "pull-request-author",
) -> dict[str, Any]:
    """Return a clean current-head PR that otherwise qualifies for merge."""
    reviews = [review("opencode-agent")]
    reviews.extend(extra_reviews or [])
    return {
        "number": 771,
        "title": "Guard independent approval",
        "author": {"login": author},
        "isDraft": False,
        "mergeable": "MERGEABLE",
        "mergeStateStatus": "CLEAN",
        "restMergeableState": "CLEAN",
        "reviewDecision": review_decision,
        "baseRefName": "main",
        "baseRefOid": BASE_SHA,
        "headRefName": "fix/approval-gate",
        "headRefOid": HEAD_SHA,
        "isCrossRepository": False,
        "maintainerCanModify": False,
        "headRepository": {"nameWithOwner": "owner/repo"},
        "autoMergeRequest": None,
        "commits": {
            "nodes": [
                {
                    "commit": {
                        "oid": HEAD_SHA,
                        "authoredDate": "2026-08-07T17:55:00Z",
                        "committedDate": "2026-08-07T17:55:00Z",
                        "messageHeadline": "fix: guard scheduler approval",
                    }
                }
            ]
        },
        "reviewThreads": {"nodes": []},
        "files": {"nodes": []},
        "reviews": {"nodes": reviews},
        "statusCheckRollup": {
            "contexts": {
                "nodes": [
                    {
                        "__typename": "CheckRun",
                        "name": "strix",
                        "status": "COMPLETED",
                        "conclusion": "SUCCESS",
                        "checkSuite": {
                            "workflowRun": {"workflow": {"name": "Strix Security Scan"}}
                        },
                    }
                ]
            }
        },
    }


def inspect(pr: dict[str, Any]):
    """Inspect one fixture using the direct-merge path without mutating GitHub."""
    return sched.inspect_pr(
        "owner/repo",
        pr,
        dry_run=True,
        trigger_reviews=False,
        enable_auto_merge_flag=True,
        update_branches=False,
        workflow="OpenCode Review",
        security_workflow="Strix Security Scan",
        base_branch="main",
        merge_mode="direct",
    )


def test_graphql_contract_requests_pull_request_author() -> None:
    """Request the PR author in the same authoritative GraphQL evidence envelope."""
    assert "\n  author { login }\n" in sched.PULL_REQUEST_FIELDS_FRAGMENT


def test_quality_workflow_tracks_scheduler_core() -> None:
    """Keep the approval regression gate attached to both scheduler facade and core."""
    workflow = (ROOT / ".github/workflows/scheduler-independent-approval-quality-ci.yml").read_text(
        encoding="utf-8"
    )
    assert '- "scripts/ci/_pr_review_merge_scheduler_core.py"' in workflow


def test_quality_workflow_runs_full_suite_and_checks_all_worktree_changes() -> None:
    """Require broad regression evidence and detect staged or untracked test artifacts."""
    workflow = (ROOT / ".github/workflows/scheduler-independent-approval-quality-ci.yml").read_text(
        encoding="utf-8"
    )
    commands = [line.strip() for line in workflow.splitlines()]

    assert commands.count("python -m pytest -q") == 1
    assert [line for line in commands if line.startswith("python -m pytest")] == [
        "python -m pytest -q"
    ]
    assert 'test -z "$(git status --porcelain=v1 --untracked-files=all)"' in commands
    assert "git diff --exit-code" not in workflow


def test_review_required_blocks_even_with_opencode_and_independent_approval() -> None:
    """GitHub REVIEW_REQUIRED must never be converted into a scheduler merge."""
    decision = inspect(
        make_pr(
            review_decision="REVIEW_REQUIRED",
            extra_reviews=[review("cwl-noema-review")],
        )
    )

    assert decision.action == "wait"
    assert "reviewDecision" in decision.reason


def test_github_approved_without_exact_head_independent_review_blocks() -> None:
    """GitHub approval state alone cannot replace exact-head independent evidence."""
    decision = inspect(make_pr(review_decision="APPROVED"))

    assert decision.action == "wait"
    assert "independent" in decision.reason.lower()


def test_missing_independent_approval_disarms_clean_auto_merge() -> None:
    """Do not leave native auto-merge armed after independent approval disappears."""
    pr = make_pr(review_decision="APPROVED")
    pr["autoMergeRequest"] = {"enabledAt": "2026-08-09T00:00:00Z"}

    decision = inspect(pr)

    assert decision.action == "disable_auto_merge"
    assert "obtain fresh independent approval" in decision.reason


def test_stale_independent_approval_does_not_authorize_current_head() -> None:
    """An independent approval for a predecessor commit is non-authoritative."""
    decision = inspect(
        make_pr(
            review_decision="APPROVED",
            extra_reviews=[review("cwl-noema-review", commit="c" * 40)],
        )
    )

    assert decision.action == "wait"
    assert "independent" in decision.reason.lower()


def test_author_self_approval_does_not_count_as_independent() -> None:
    """A formal approval by the pull-request author is never independent evidence."""
    decision = inspect(
        make_pr(
            review_decision="APPROVED",
            extra_reviews=[review("pull-request-author")],
        )
    )

    assert decision.action == "wait"
    assert "independent" in decision.reason.lower()


def test_missing_author_identity_fails_closed() -> None:
    """Do not guess reviewer independence when GitHub omits the PR author identity."""
    pr = make_pr(
        review_decision="APPROVED",
        extra_reviews=[review("cwl-noema-review")],
    )
    pr["author"] = {"login": ""}

    decision = inspect(pr)

    assert decision.action == "wait"
    assert "independent" in decision.reason.lower()


def test_missing_reviewer_identity_does_not_count_as_independent() -> None:
    """Do not treat an anonymous formal review as independent merge authority."""
    decision = inspect(
        make_pr(
            review_decision="APPROVED",
            extra_reviews=[review("")],
        )
    )

    assert decision.action == "wait"
    assert "independent" in decision.reason.lower()


def test_non_approved_independent_review_does_not_authorize_merge() -> None:
    """Only a formal APPROVED independent review is merge authority."""
    decision = inspect(
        make_pr(
            review_decision="APPROVED",
            extra_reviews=[review("cwl-noema-review", state="COMMENTED")],
        )
    )

    assert decision.action == "wait"
    assert "independent" in decision.reason.lower()


def test_exact_head_independent_approval_and_github_approval_allow_merge() -> None:
    """Both policy-level and exact-head independent approvals enable the merge path."""
    decision = inspect(
        make_pr(
            review_decision="APPROVED",
            extra_reviews=[review("cwl-noema-review")],
        )
    )

    assert decision.action == "merge"
