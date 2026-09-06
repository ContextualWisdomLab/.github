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
                        "workflow_id": 11,
                        # GitHub renders run-name: into the run's own name.
                        "name": (
                            "Required OpenCode Review owner/repo#42@" + head_sha
                        ),
                    }
                ]
            }
        if path == "repos/owner/repo/actions/workflows/11":
            return {"name": "Required OpenCode Review"}
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


def test_fetch_workflow_names_by_check_suite_rest_paginates_past_100(
    monkeypatch: Any,
) -> None:
    """A first page of exactly 100 runs must fetch a second page and merge both."""
    head_sha = "e" * 40
    page1 = [
        {"check_suite_id": i, "workflow_id": i, "name": f"rendered-{i}"}
        for i in range(100)
    ]
    page2 = [{"check_suite_id": 100, "workflow_id": 100, "name": "rendered-100"}]
    calls: list[str] = []

    def fake_api(path: str) -> Any:
        """Return deterministic paginated workflow-run fixtures."""
        calls.append(path)
        if path.endswith("page=1"):
            return {"workflow_runs": page1}
        if path.endswith("page=2"):
            return {"workflow_runs": page2}
        prefix = "repos/owner/repo/actions/workflows/"
        if path.startswith(prefix):
            return {"name": f"workflow-{path[len(prefix):]}"}
        raise AssertionError(f"unexpected path {path}")

    monkeypatch.setattr(merge, "gh_api_json", fake_api)
    merge.reset_active_workflow_runs_cache()

    names = merge.fetch_workflow_names_by_check_suite_rest("owner/repo", head_sha)

    assert names == {i: f"workflow-{i}" for i in range(101)}
    run_list_calls = [path for path in calls if "/actions/runs?" in path]
    assert run_list_calls == [
        f"repos/owner/repo/actions/runs?head_sha={head_sha}&per_page=100&page=1",
        f"repos/owner/repo/actions/runs?head_sha={head_sha}&per_page=100&page=2",
    ]


def test_fetch_workflow_names_by_check_suite_rest_skips_entries_missing_suite_id_or_name(
    monkeypatch: Any,
) -> None:
    """A run missing a check-suite id, a workflow id, or a name must not populate the map."""
    head_sha = "f" * 40

    def fake_api(path: str) -> Any:
        """Return workflow runs that exercise incomplete-identity filtering."""
        if path.startswith("repos/owner/repo/actions/runs?"):
            return {
                "workflow_runs": [
                    {"check_suite_id": None, "workflow_id": 1, "name": "orphaned"},
                    {"check_suite_id": 900, "workflow_id": 2, "name": "blank"},
                    {"check_suite_id": 902, "name": "no workflow id"},
                    {"check_suite_id": 901, "workflow_id": 3, "name": "rendered"},
                ]
            }
        return {
            "repos/owner/repo/actions/workflows/1": {"name": "orphaned run"},
            "repos/owner/repo/actions/workflows/2": {"name": ""},
            "repos/owner/repo/actions/workflows/3": {"name": "kept run"},
        }[path]

    monkeypatch.setattr(merge, "gh_api_json", fake_api)
    merge.reset_active_workflow_runs_cache()

    names = merge.fetch_workflow_names_by_check_suite_rest("owner/repo", head_sha)

    assert names == {901: "kept run"}


def test_fetch_workflow_names_by_check_suite_rest_propagates_non_access_errors(
    monkeypatch: Any,
) -> None:
    """A page-fetch failure unrelated to integration access must fail closed."""
    head_sha = "0" * 40

    def fake_api(path: str) -> Any:
        """Simulate a non-access REST failure that must propagate."""
        raise RuntimeError("gh: HTTP 502 (exhausted retries)")

    monkeypatch.setattr(merge, "gh_api_json", fake_api)

    with pytest.raises(RuntimeError, match="HTTP 502"):
        merge.fetch_workflow_names_by_check_suite_rest("owner/repo", head_sha)


def test_rest_fallback_identifies_strix_behind_a_rendered_run_name(
    monkeypatch: Any,
) -> None:
    """A workflow declaring run-name: stays identifiable through the REST fallback.

    GitHub renders ``run-name:`` into a run's own ``name``, so the Actions run
    list reports a title carrying the pull request and head SHA. Reading that
    as workflow identity leaves it matching none of the declared names the
    policy predicates compare against, and the fail-closed sentinel does not
    engage because a name is present -- it is simply the wrong one.
    """
    head_sha = "1" * 40
    payloads: dict[str, Any] = {
        "repos/owner/repo/pulls/44/reviews?per_page=100&page=1": [],
        f"repos/owner/repo/commits/{head_sha}/check-runs?per_page=100": {
            "check_runs": [
                {
                    "name": "strix",
                    "status": "completed",
                    "conclusion": "success",
                    "started_at": "2026-09-01T05:00:00Z",
                    "details_url": (
                        "https://github.com/owner/repo/actions/runs/900/job/901"
                    ),
                    "check_suite": {"id": 779},
                    "app": {"slug": "github-actions"},
                }
            ]
        },
        f"repos/owner/repo/commits/{head_sha}/check-suites?per_page=100": {
            "check_suites": [{"id": 779, "created_at": "2026-09-01T05:00:00Z"}]
        },
        f"repos/owner/repo/commits/{head_sha}/status": {"statuses": []},
        "repos/owner/repo/pulls/44/files?per_page=20": [],
    }

    def fake_api(path: str) -> Any:
        """Serve a Strix run whose name has been rewritten by run-name:."""
        if path.startswith("repos/owner/repo/actions/runs?"):
            return {
                "workflow_runs": [
                    {
                        "check_suite_id": 779,
                        "workflow_id": 55,
                        "name": f"Strix Security Scan owner/repo#44@{head_sha}",
                    }
                ]
            }
        if path == "repos/owner/repo/actions/workflows/55":
            return {"name": "Strix Security Scan"}
        return payloads[path]

    monkeypatch.setattr(merge, "gh_api_json", fake_api)
    merge.reset_active_workflow_runs_cache()

    pr = merge.rest_pr_node(
        "owner/repo",
        {
            "number": 44,
            "title": "REST fallback rendered run name",
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
            "base": {"ref": "main", "sha": "2" * 40},
        },
    )

    context = merge.context_nodes(pr)[0]
    workflow = context["checkSuite"]["workflowRun"]["workflow"]
    assert workflow["name"] == "Strix Security Scan"
    assert merge.is_strix_context(context)


def test_workflow_static_name_caches_each_workflow_once(monkeypatch: Any) -> None:
    """Workflow identity is immutable per run, so it is read at most once."""
    calls: list[str] = []

    def fake_api(path: str) -> Any:
        """Count workflow-resource reads."""
        calls.append(path)
        return {"name": "Strix Security Scan"}

    monkeypatch.setattr(merge, "gh_api_json", fake_api)
    merge.reset_active_workflow_runs_cache()

    assert merge.workflow_static_name("owner/repo", 55) == "Strix Security Scan"
    assert merge.workflow_static_name("owner/repo", 55) == "Strix Security Scan"

    assert calls == ["repos/owner/repo/actions/workflows/55"]


def test_workflow_static_name_caches_an_unreadable_workflow_as_no_identity(
    monkeypatch: Any,
) -> None:
    """A workflow the integration cannot read yields no identity, and is not re-read."""
    calls: list[str] = []

    def fake_api(path: str) -> Any:
        """Deny the workflow resource the way a scoped token does."""
        calls.append(path)
        raise RuntimeError("Resource not accessible by integration")

    monkeypatch.setattr(merge, "gh_api_json", fake_api)
    merge.reset_active_workflow_runs_cache()

    assert merge.workflow_static_name("owner/repo", 56) == ""
    assert merge.workflow_static_name("owner/repo", 56) == ""

    assert calls == ["repos/owner/repo/actions/workflows/56"]


def test_workflow_static_name_propagates_non_access_errors(monkeypatch: Any) -> None:
    """An unrelated REST failure must not be recorded as absent identity."""

    def fake_api(path: str) -> Any:
        """Simulate a non-access REST failure that must propagate."""
        raise RuntimeError("gh: HTTP 502 (exhausted retries)")

    monkeypatch.setattr(merge, "gh_api_json", fake_api)
    merge.reset_active_workflow_runs_cache()

    with pytest.raises(RuntimeError, match="HTTP 502"):
        merge.workflow_static_name("owner/repo", 57)


def test_reset_active_workflow_runs_cache_clears_workflow_identity(
    monkeypatch: Any,
) -> None:
    """The reset entry point must not leave stale identity behind for a later run."""
    names = iter(["First Name", "Second Name"])

    def fake_api(path: str) -> Any:
        """Return a different declared name on each read."""
        return {"name": next(names)}

    monkeypatch.setattr(merge, "gh_api_json", fake_api)
    merge.reset_active_workflow_runs_cache()

    assert merge.workflow_static_name("owner/repo", 58) == "First Name"
    merge.reset_active_workflow_runs_cache()
    assert merge.workflow_static_name("owner/repo", 58) == "Second Name"


@pytest.mark.parametrize(
    ("error", "cause"),
    [
        ("Resource not accessible by integration", "integration permission"),
        ("gh: HTTP 502 (exhausted retries)", "transient API error"),
    ],
)
def test_warn_graphql_rest_fallback_names_the_cause(
    capsys: Any, error: str, cause: str
) -> None:
    """Each fallback cause is reported separately because each needs a different fix."""
    merge.warn_graphql_rest_fallback("owner/repo", "pull request #7", RuntimeError(error))

    captured = capsys.readouterr().out
    assert "::warning::GraphQL pull request #7 read for owner/repo" in captured
    assert f"fell back to REST ({cause})" in captured


def test_fetch_pr_announces_its_rest_fallback(monkeypatch: Any, capsys: Any) -> None:
    """A single-PR fallback leaves a trace; gh_graphql raises before printing one."""

    def fake_graphql(query: str, **fields: Any) -> Any:
        """Deny the GraphQL read the way a scoped token does."""
        raise RuntimeError("Resource not accessible by integration")

    monkeypatch.setattr(merge, "gh_graphql", fake_graphql)
    monkeypatch.setattr(merge, "fetch_pr_rest", lambda repo, number: ["rest"])

    assert merge.fetch_pr("owner/repo", 7) == ["rest"]

    captured = capsys.readouterr().out
    assert "::warning::GraphQL pull request #7 read for owner/repo" in captured
    assert "(integration permission)" in captured


def test_fetch_open_prs_announces_its_rest_fallback(
    monkeypatch: Any, capsys: Any
) -> None:
    """The queue scan's fallback is silent otherwise, and carries no pragma-covered trace."""

    def fake_graphql(query: str, **fields: Any) -> Any:
        """Fail the GraphQL read with a transient error."""
        raise RuntimeError("gh: HTTP 502 (exhausted retries)")

    monkeypatch.setattr(merge, "gh_graphql", fake_graphql)
    monkeypatch.setattr(
        merge,
        "fetch_open_prs_rest",
        lambda repo, max_prs, offset=0, window_size=None: ["rest"],
    )

    assert merge.fetch_open_prs("owner/repo", 5) == ["rest"]

    captured = capsys.readouterr().out
    assert "::warning::GraphQL open pull request read for owner/repo" in captured
    assert "(transient API error)" in captured
