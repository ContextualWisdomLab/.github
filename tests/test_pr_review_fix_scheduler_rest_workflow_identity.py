"""Regression coverage for REST-fallback workflow identity."""

from __future__ import annotations

from typing import Any

import pytest

from scripts.ci import pr_review_fix_scheduler as fix
from scripts.ci import pr_review_merge_scheduler as merge


def test_rest_fallback_preserves_renamed_opencode_workflow_identity(
    monkeypatch: Any,
) -> None:
    """A renamed OpenCode job remains a control-plane check after REST conversion."""
    head_sha = "a" * 40
    calls: list[str] = []
    payloads: dict[str, Any] = {
        "repos/owner/repo/pulls/42/reviews?per_page=100&page=1": [],
        f"repos/owner/repo/commits/{head_sha}/check-runs?per_page=100": {
            "check_runs": [
                {
                    "name": "renamed review policy gate",
                    "status": "completed",
                    "conclusion": "failure",
                    "started_at": "2026-09-01T03:00:00Z",
                    "details_url": (
                        "https://github.com/owner/repo/actions/runs/123/job/456"
                    ),
                    "check_suite": {"id": 777},
                    "app": {"slug": "github-actions"},
                }
            ]
        },
        f"repos/owner/repo/commits/{head_sha}/check-suites?per_page=100": {
            "check_suites": [
                {"id": 777, "created_at": "2026-09-01T03:00:00Z"}
            ]
        },
        f"repos/owner/repo/commits/{head_sha}/status": {"statuses": []},
        "repos/owner/repo/pulls/42/files?per_page=20": [],
    }

    def fake_api(path: str) -> Any:
        calls.append(path)
        if path.startswith("repos/owner/repo/actions/runs?"):
            return {
                "workflow_runs": [
                    {
                        "check_suite_id": 777,
                        "name": "Required OpenCode Review",
                    }
                ]
            }
        return payloads[path]

    monkeypatch.setattr(merge, "gh_api_json", fake_api)

    pr = merge.rest_pr_node(
        "owner/repo",
        {
            "number": 42,
            "title": "REST fallback",
            "draft": False,
            "mergeable": True,
            "mergeable_state": "clean",
            "maintainer_can_modify": True,
            "auto_merge": None,
            "user": {"login": "author"},
            "head": {
                "ref": "feature",
                "sha": head_sha,
                "repo": {"full_name": "owner/repo"},
            },
            "base": {"ref": "main", "sha": "b" * 40},
        },
    )

    contexts = merge.context_nodes(pr)
    workflow = contexts[0]["checkSuite"]["workflowRun"]["workflow"]
    assert workflow["name"] == "Required OpenCode Review"
    assert fix.current_head_failed_checks(pr) == ()
    assert any("/actions/runs?" in path for path in calls)


@pytest.mark.parametrize(
    ("conclusion", "expected_state"),
    [("success", "complete"), ("failure", "failed")],
)
def test_rest_fallback_keeps_name_only_strix_when_actions_runs_are_inaccessible(
    monkeypatch: Any,
    conclusion: str,
    expected_state: str,
) -> None:
    """Unknown workflow identity does not erase authoritative name-only Strix evidence."""
    head_sha = "c" * 40
    payloads: dict[str, Any] = {
        "repos/owner/repo/pulls/43/reviews?per_page=100&page=1": [],
        f"repos/owner/repo/commits/{head_sha}/check-runs?per_page=100": {
            "check_runs": [
                {
                    "name": "strix",
                    "status": "completed",
                    "conclusion": conclusion,
                    "started_at": "2026-09-01T04:00:00Z",
                    "details_url": (
                        "https://github.com/owner/repo/actions/runs/321/job/654"
                    ),
                    "check_suite": {"id": 778},
                    "app": {"slug": "github-actions"},
                }
            ]
        },
        f"repos/owner/repo/commits/{head_sha}/check-suites?per_page=100": {
            "check_suites": [
                {"id": 778, "created_at": "2026-09-01T04:00:00Z"}
            ]
        },
        f"repos/owner/repo/commits/{head_sha}/status": {"statuses": []},
        "repos/owner/repo/pulls/43/files?per_page=20": [],
    }

    def fake_api(path: str) -> Any:
        if path.startswith("repos/owner/repo/actions/runs?"):
            raise RuntimeError("Resource not accessible by integration")
        return payloads[path]

    monkeypatch.setattr(merge, "gh_api_json", fake_api)

    pr = merge.rest_pr_node(
        "owner/repo",
        {
            "number": 43,
            "title": "REST fallback Strix",
            "draft": False,
            "mergeable": True,
            "mergeable_state": "clean",
            "maintainer_can_modify": True,
            "auto_merge": None,
            "user": {"login": "author"},
            "head": {
                "ref": "feature",
                "sha": head_sha,
                "repo": {"full_name": "owner/repo"},
            },
            "base": {"ref": "main", "sha": "d" * 40},
        },
    )

    context = merge.context_nodes(pr)[0]
    workflow = context["checkSuite"]["workflowRun"]["workflow"]
    assert workflow["name"] == merge.REST_UNKNOWN_GITHUB_ACTIONS_WORKFLOW
    assert merge.is_strix_context(context)
    assert merge.strix_evidence_state(pr) == expected_state
    assert fix.current_head_failed_checks(pr) == ()
