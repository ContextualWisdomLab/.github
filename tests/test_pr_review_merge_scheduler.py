import json
import sys
from datetime import datetime, timezone

import pytest

from scripts.ci import pr_review_merge_scheduler as sched


def make_pr(**overrides):
    value = {
        "number": 1,
        "title": "Central review",
        "isDraft": False,
        "mergeable": "MERGEABLE",
        "mergeStateStatus": "CLEAN",
        "restMergeableState": "",
        "reviewDecision": "REVIEW_REQUIRED",
        "baseRefName": "main",
        "baseRefOid": "base",
        "headRefName": "feature",
        "headRefOid": "head",
        "isCrossRepository": False,
        "maintainerCanModify": False,
        "headRepository": {"nameWithOwner": "owner/repo"},
        "autoMergeRequest": None,
        "commits": {
            "nodes": [
                {
                    "commit": {
                        "oid": "head",
                        "authoredDate": "2026-06-25T07:00:00Z",
                        "committedDate": "2026-06-25T07:00:00Z",
                    }
                }
            ]
        },
        "reviewThreads": {"nodes": []},
        "files": {"nodes": []},
        "reviews": {"nodes": []},
        "statusCheckRollup": {"contexts": {"nodes": []}},
    }
    value.update(overrides)
    return value


def opencode_review(
    state="APPROVED",
    commit="head",
    login="opencode-agent",
    submitted_at="2026-06-25T07:01:00Z",
):
    return {
        "state": state,
        "author": {"login": login},
        "submittedAt": submitted_at,
        "commit": {"oid": commit},
    }


def strix_check(status="COMPLETED", conclusion="SUCCESS", workflow="Strix Security Scan", details_url=None):
    value = {
        "__typename": "CheckRun",
        "name": "strix",
        "status": status,
        "conclusion": conclusion,
        "checkSuite": {"workflowRun": {"workflow": {"name": workflow}}},
    }
    if details_url:
        value["detailsUrl"] = details_url
    return value


def opencode_check(status="IN_PROGRESS", started_at=None, details_url=None):
    value = {
        "__typename": "CheckRun",
        "name": "opencode-review",
        "status": status,
        "startedAt": started_at,
        "checkSuite": {"workflowRun": {"workflow": {"name": "OpenCode Review"}}},
    }
    if details_url:
        value["detailsUrl"] = details_url
    return value


def inspect(pr, **overrides):
    kwargs = {
        "dry_run": True,
        "trigger_reviews": True,
        "enable_auto_merge_flag": True,
        "update_branches": True,
        "workflow": "OpenCode Review",
        "security_workflow": "Strix Security Scan",
        "base_branch": "main",
        "merge_mode": "auto",
    }
    kwargs.update(overrides)
    return sched.inspect_pr("owner/repo", pr, **kwargs)


def test_run_split_repo_and_graphql(monkeypatch):
    assert sched.run([sys.executable, "-c", "print('ok')"]).strip() == "ok"
    with pytest.raises(RuntimeError):
        sched.run([sys.executable, "-c", "import sys; sys.exit(7)"])
    with pytest.raises(TypeError):
        sched.run("echo unsafe")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        sched.run(["echo", 1])  # type: ignore[list-item]

    assert sched.split_repo("owner/repo") == ("owner", "repo")
    with pytest.raises(ValueError):
        sched.split_repo("bad")
    with pytest.raises(ValueError):
        sched.split_repo("/repo")

    assert sched.validate_git_ref("feature/safe.branch-1") == "feature/safe.branch-1"
    for bad_ref in (
        "",
        "-bad",
        "HEAD",
        "feature/../main",
        "feature/.tmp/main",
        "feature/./main",
        "feature//main",
        "feature/main.",
        "feature/@{upstream}",
        "feat;echo pwned",
    ):
        with pytest.raises(ValueError):
            sched.validate_git_ref(bad_ref)

    assert sched.validate_git_sha("a" * 40) == "a" * 40
    for bad_sha in ("", "a" * 39, "g" * 40, "a" * 40 + ";echo pwned"):
        with pytest.raises(ValueError):
            sched.validate_git_sha(bad_sha)

    assert sched.validate_github_repository("owner/repo.name") == "owner/repo.name"
    for bad_repo in ("", "owner", "owner/repo/extra", "owner/repo;echo pwned"):
        with pytest.raises(ValueError):
            sched.validate_github_repository(bad_repo)

    calls = []

    def fake_run(args, stdin=None):
        calls.append((args, stdin))
        return '{"ok": true}'

    monkeypatch.setattr(sched, "run", fake_run)
    assert sched.gh_graphql("query", pageSize=2, cursor="abc") == {"ok": True}
    assert "-F" in calls[0][0]
    assert "-f" in calls[0][0]
    assert calls[0][1] == "query"


def test_github_reads_use_dedicated_read_token_when_configured(monkeypatch):
    calls = []

    monkeypatch.setenv("GH_TOKEN", "mutation-token")
    monkeypatch.setenv("SCHEDULER_READ_TOKEN", "read-token")

    def fake_run_with_env(args, stdin=None, env=None):
        calls.append((args, stdin, env))
        return '{"ok": true}'

    monkeypatch.setattr(sched, "run_with_env", fake_run_with_env)

    assert sched.gh_api_json("repos/owner/repo/pulls/1") == {"ok": True}
    assert sched.gh_graphql("query", owner="owner") == {"ok": True}
    assert calls[0][0] == ["gh", "api", "repos/owner/repo/pulls/1"]
    assert calls[0][2]["GH_TOKEN"] == "read-token"
    assert calls[1][0][:3] == ["gh", "api", "graphql"]
    assert calls[1][1] == "query"
    assert calls[1][2]["GH_TOKEN"] == "read-token"


def test_run_passes_shell_metacharacters_as_plain_arguments(tmp_path):
    sentinel = tmp_path / "pwned"
    payload = f"feature; touch {sentinel}; #"

    output = sched.run(
        [
            sys.executable,
            "-c",
            "import sys; print(sys.argv[1])",
            payload,
        ]
    )

    assert payload in output
    assert not sentinel.exists()


def test_fetch_open_prs_paginates(monkeypatch):
    pages = [
        {
            "data": {
                "repository": {
                    "pullRequests": {
                        "nodes": [{"number": 1}],
                        "pageInfo": {"hasNextPage": True, "endCursor": "cursor"},
                    }
                }
            }
        },
        {
            "data": {
                "repository": {
                    "pullRequests": {
                        "nodes": [{"number": 2}],
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                    }
                }
            }
        },
    ]
    seen = []

    def fake_graphql(query, **fields):
        seen.append(fields)
        return pages.pop(0)

    monkeypatch.setattr(sched, "gh_graphql", fake_graphql)
    monkeypatch.setattr(sched, "enrich_rest_mergeable_states", lambda repo, prs: None)
    assert sched.fetch_open_prs("owner/repo", 3) == [{"number": 1}, {"number": 2}]
    assert seen[0]["pageSize"] == 3
    assert seen[1]["cursor"] == "cursor"


def test_fetch_open_prs_zero_limit_skips_graphql(monkeypatch):
    calls = []
    monkeypatch.setattr(sched, "gh_graphql", lambda *args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setattr(sched, "enrich_rest_mergeable_states", lambda repo, prs: calls.append((repo, prs)))

    assert sched.fetch_open_prs("owner/repo", 0) == []
    assert calls == [("owner/repo", [])]


def test_fetch_open_prs_caps_page_size_to_avoid_graphql_resource_limits(monkeypatch):
    seen = []

    def fake_graphql(query, **fields):
        seen.append(fields)
        return {
            "data": {
                "repository": {
                    "pullRequests": {
                        "nodes": [{"number": fields["pageSize"]}],
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                    }
                }
            }
        }

    monkeypatch.setattr(sched, "gh_graphql", fake_graphql)
    monkeypatch.setattr(sched, "enrich_rest_mergeable_states", lambda repo, prs: None)

    assert sched.fetch_open_prs("owner/repo", 120) == [{"number": sched.OPEN_PRS_PAGE_SIZE}]
    assert seen[0]["pageSize"] == sched.OPEN_PRS_PAGE_SIZE


def test_fetch_pr_uses_exact_pull_request_number(monkeypatch):
    seen = []

    def fake_graphql(query, **fields):
        seen.append(fields)
        return {
            "data": {
                "repository": {
                    "pullRequest": {"number": fields["number"]},
                }
            }
        }

    monkeypatch.setattr(sched, "gh_graphql", fake_graphql)
    monkeypatch.setattr(sched, "enrich_rest_mergeable_states", lambda repo, prs: None)

    assert sched.fetch_pr("owner/repo", 42) == [{"number": 42}]
    assert seen == [{"owner": "owner", "name": "repo", "number": 42}]


def test_gh_graphql_retries_transient_gateway_errors(monkeypatch):
    calls = []
    sleeps = []

    def fake_run(args, stdin=None):
        calls.append((args, stdin))
        if len(calls) == 1:
            raise RuntimeError("Command failed (1): gh api graphql\ngh: HTTP 502")
        if len(calls) == 2:
            raise RuntimeError("Command failed (1): gh api graphql\ngh: HTTP 504")
        return '{"data":{"repository":{"pullRequests":{"nodes":[],"pageInfo":{"hasNextPage":false}}}}}'

    monkeypatch.setattr(sched, "run", fake_run)
    monkeypatch.setattr(sched.time, "sleep", lambda seconds: sleeps.append(seconds))

    payload = sched.gh_graphql("query", owner="owner", name="repo", pageSize=100)

    assert payload["data"]["repository"]["pullRequests"]["nodes"] == []
    assert len(calls) == 3
    assert sleeps == [1, 2]


def test_gh_graphql_does_not_retry_non_transient_errors(monkeypatch):
    calls = []

    def fake_run(args, stdin=None):
        calls.append(args)
        raise RuntimeError("Command failed (1): gh api graphql\ngh: Field 'unknown' doesn't exist on type 'PullRequest'")

    monkeypatch.setattr(sched, "run", fake_run)

    with pytest.raises(RuntimeError, match="Field 'unknown'"):
        sched.gh_graphql("query", owner="owner")
    assert len(calls) == 1


def test_rest_mergeable_state_helpers(monkeypatch):
    calls = []

    def fake_run(args, stdin=None):
        calls.append(args)
        return "dirty\n"

    monkeypatch.setattr(sched, "run", fake_run)

    assert sched.fetch_rest_mergeable_state("owner/repo", 7) == "DIRTY"
    assert calls == [["gh", "api", "repos/owner/repo/pulls/7", "--jq", ".mergeable_state // \"\""]]
    calls.clear()

    def fake_compare_run(args, stdin=None):
        calls.append(args)
        return '{"status":"behind","behind_by":3}'

    monkeypatch.setattr(sched, "run", fake_compare_run)
    compare = sched.fetch_compare_branch_freshness(
        "owner/repo",
        {
            "baseRefName": "main",
            "headRefName": "feature/update-branch",
            "headRepository": {"nameWithOwner": "fork/repo"},
        },
    )
    assert compare == {"status": "behind", "behind_by": 3}
    assert calls == [["gh", "api", "repos/owner/repo/compare/main...fork:feature%2Fupdate-branch"]]
    calls.clear()
    same_repo_compare = sched.fetch_compare_branch_freshness(
        "owner/repo",
        {
            "baseRefName": "main",
            "headRefName": "feature/update-branch",
            "headRepository": {"nameWithOwner": "owner/repo"},
        },
    )
    assert same_repo_compare == {"status": "behind", "behind_by": 3}
    assert calls == [["gh", "api", "repos/owner/repo/compare/main...feature%2Fupdate-branch"]]

    prs = [{"number": 8, "baseRefName": "main", "headRefName": "feature"}]
    empty_prs = []
    sched.enrich_rest_mergeable_states("owner/repo", empty_prs)
    assert empty_prs == []

    prs = [{"number": 8, "baseRefName": "main", "headRefName": "feature"}]
    monkeypatch.setattr(sched, "fetch_rest_mergeable_state", lambda repo, number: f"{repo}:{number}")
    monkeypatch.setattr(
        sched,
        "fetch_compare_branch_freshness",
        lambda repo, pr: {"status": "behind", "behind_by": 2},
    )
    sched.enrich_rest_mergeable_states("owner/repo", prs)
    assert prs == [
        {
            "number": 8,
            "baseRefName": "main",
            "headRefName": "feature",
            "restMergeableState": "owner/repo:8",
            "compareStatus": "behind",
            "compareBehindBy": 2,
        }
    ]

    def raise_lookup_error(repo, number):
        raise RuntimeError("transient REST failure")

    prs = [{"number": 9, "baseRefName": "main", "headRefName": "feature"}]
    monkeypatch.setattr(sched, "fetch_rest_mergeable_state", raise_lookup_error)
    sched.enrich_rest_mergeable_states("owner/repo", prs)
    assert prs == [
        {
            "number": 9,
            "baseRefName": "main",
            "headRefName": "feature",
            "restMergeableStateError": "transient REST failure",
            "compareStatus": "behind",
            "compareBehindBy": 2,
        }
    ]

    def raise_compare_error(repo, pr):
        raise RuntimeError("transient compare failure")

    prs = [{"number": 10, "baseRefName": "main", "headRefName": "feature"}]
    monkeypatch.setattr(sched, "fetch_rest_mergeable_state", lambda repo, number: "CLEAN")
    monkeypatch.setattr(sched, "fetch_compare_branch_freshness", raise_compare_error)
    sched.enrich_rest_mergeable_states("owner/repo", prs)
    assert prs == [
        {
            "number": 10,
            "baseRefName": "main",
            "headRefName": "feature",
            "restMergeableState": "CLEAN",
            "compareBranchFreshnessError": "transient compare failure",
        }
    ]


def test_rest_pr_fallback_shapes_reviews_and_checks(monkeypatch):
    calls = []
    payloads = {
        "repos/owner/repo/pulls/42/reviews?per_page=100": [
            {
                "state": "APPROVED",
                "body": "Head SHA: `abc123`",
                "submitted_at": "2026-06-30T00:00:00Z",
                "commit_id": "abc123",
                "user": {"login": "opencode-agent[bot]"},
            }
        ],
        "repos/owner/repo/commits/abc123/check-runs?per_page=100": {
            "check_runs": [
                {
                    "name": "opencode-review",
                    "status": "completed",
                    "conclusion": "success",
                    "started_at": "2026-06-30T00:00:00Z",
                    "details_url": "https://github.com/owner/repo/actions/runs/1/job/2",
                }
            ]
        },
        "repos/owner/repo/pulls/42/files?per_page=20": [
            {"filename": "scripts/ci/pr_review_merge_scheduler.py"},
        ],
    }

    def fake_api(path):
        calls.append(path)
        return payloads[path]

    monkeypatch.setattr(sched, "gh_api_json", fake_api)
    node = sched.rest_pr_node(
        "owner/repo",
        {
            "number": 42,
            "title": "Fallback",
            "draft": False,
            "mergeable": True,
            "mergeable_state": "clean",
            "base": {"ref": "main", "sha": "base123"},
            "head": {
                "ref": "feature",
                "sha": "abc123",
                "repo": {"full_name": "owner/repo"},
            },
            "maintainer_can_modify": True,
            "auto_merge": {"enabled_at": "2026-06-30T00:01:00Z"},
        },
    )

    assert calls == [
        "repos/owner/repo/pulls/42/reviews?per_page=100",
        "repos/owner/repo/commits/abc123/check-runs?per_page=100",
        "repos/owner/repo/pulls/42/files?per_page=20",
    ]
    assert node["number"] == 42
    assert node["mergeStateStatus"] == "CLEAN"
    assert node["restMergeableState"] == "CLEAN"
    assert node["files"]["nodes"] == [{"path": "scripts/ci/pr_review_merge_scheduler.py"}]
    assert node["headRepository"] == {"nameWithOwner": "owner/repo"}
    assert not node["isCrossRepository"]
    assert node["reviews"]["nodes"][0]["author"]["login"] == "opencode-agent[bot]"
    assert node["reviews"]["nodes"][0]["commit"]["oid"] == "abc123"
    assert node["statusCheckRollup"]["contexts"]["nodes"][0]["status"] == "COMPLETED"
    assert node["statusCheckRollup"]["contexts"]["nodes"][0]["conclusion"] == "SUCCESS"


def test_fetch_pr_falls_back_to_rest_when_graphql_denied(monkeypatch):
    def deny_graphql(*args, **kwargs):
        raise RuntimeError("gh: Resource not accessible by integration")

    monkeypatch.setattr(sched, "gh_graphql", deny_graphql)
    monkeypatch.setattr(sched, "fetch_pr_rest", lambda repo, number: [{"number": number, "repo": repo}])

    assert sched.github_resource_inaccessible(RuntimeError("Resource not accessible by integration"))
    assert sched.fetch_pr("owner/repo", 77) == [{"number": 77, "repo": "owner/repo"}]


def test_rest_api_wrapper_and_fetch_pr_rest(monkeypatch):
    run_calls = []

    def fake_run(args, stdin=None):
        run_calls.append(args)
        return json.dumps({"number": 42})

    monkeypatch.setattr(sched, "run", fake_run)
    assert sched.gh_api_json("repos/owner/repo/pulls/42") == {"number": 42}
    assert run_calls == [["gh", "api", "repos/owner/repo/pulls/42"]]

    api_calls = []

    def fake_api(path):
        api_calls.append(path)
        if path == "repos/owner/repo/pulls/42":
            return {"number": 42}
        return {}

    monkeypatch.setattr(sched, "gh_api_json", fake_api)
    monkeypatch.setattr(sched, "rest_pr_node", lambda repo, pr: {"repo": repo, "number": pr["number"]})
    assert sched.fetch_pr_rest("owner/repo", 42) == [{"repo": "owner/repo", "number": 42}]
    assert sched.fetch_pr_rest("owner/repo", 99) == []
    assert api_calls == ["repos/owner/repo/pulls/42", "repos/owner/repo/pulls/99"]


def test_fetch_open_prs_rest_paginates_and_fetch_open_prs_falls_back(monkeypatch):
    paths = []
    pages = {
        "repos/owner/repo/pulls?state=open&sort=created&direction=asc&per_page=3&page=1": [
            {"number": 1},
            {"number": 2},
        ]
    }

    def fake_api(path):
        paths.append(path)
        return pages[path]

    monkeypatch.setattr(sched, "gh_api_json", fake_api)
    monkeypatch.setattr(sched, "rest_pr_node", lambda repo, pr: {"number": pr["number"], "repo": repo})

    assert sched.fetch_open_prs_rest("owner/repo", 3) == [
        {"number": 1, "repo": "owner/repo"},
        {"number": 2, "repo": "owner/repo"},
    ]
    assert paths == [
        "repos/owner/repo/pulls?state=open&sort=created&direction=asc&per_page=3&page=1",
    ]

    def deny_graphql(*args, **kwargs):
        raise RuntimeError("gh: Resource not accessible by integration")

    monkeypatch.setattr(sched, "gh_graphql", deny_graphql)
    monkeypatch.setattr(sched, "fetch_open_prs_rest", lambda repo, max_prs: [{"repo": repo, "max": max_prs}])
    assert sched.fetch_open_prs("owner/repo", 5) == [{"repo": "owner/repo", "max": 5}]


def test_fetch_open_prs_rest_base_branch_empty_and_next_page(monkeypatch):
    paths = []
    pages = {
        "repos/owner/repo/pulls?state=open&sort=created&direction=asc&per_page=100&page=1&base=release%2Fv1": [
            {"number": number} for number in range(1, 101)
        ],
        "repos/owner/repo/pulls?state=open&sort=created&direction=asc&per_page=1&page=2&base=release%2Fv1": [],
    }

    def fake_api(path):
        paths.append(path)
        return pages[path]

    monkeypatch.setattr(sched, "gh_api_json", fake_api)
    monkeypatch.setattr(sched, "rest_pr_node", lambda repo, pr: {"number": pr["number"]})

    assert sched.fetch_open_prs_rest("owner/repo", 101, base_branch="release/v1") == [
        {"number": number} for number in range(1, 101)
    ]
    assert paths == list(pages)


def test_graphql_read_errors_fall_back_for_transient_failures(monkeypatch):
    def fail_graphql(*args, **kwargs):
        raise RuntimeError("Command failed (1): gh api graphql\ngh: HTTP 504")

    monkeypatch.setattr(sched, "gh_graphql", fail_graphql)
    monkeypatch.setattr(sched, "fetch_open_prs_rest", lambda repo, max_prs: [{"repo": repo, "max": max_prs}])
    monkeypatch.setattr(sched, "fetch_pr_rest", lambda repo, number: [{"repo": repo, "number": number}])

    assert sched.fetch_open_prs("owner/repo", 1) == [{"repo": "owner/repo", "max": 1}]
    assert sched.fetch_pr("owner/repo", 1) == [{"repo": "owner/repo", "number": 1}]


def test_graphql_read_errors_do_not_fall_back_for_schema_errors(monkeypatch):
    def fail_graphql(*args, **kwargs):
        raise RuntimeError("gh: Field 'unknown' doesn't exist on type 'PullRequest'")

    monkeypatch.setattr(sched, "gh_graphql", fail_graphql)

    with pytest.raises(RuntimeError, match="unknown"):
        sched.fetch_open_prs("owner/repo", 1)
    with pytest.raises(RuntimeError, match="unknown"):
        sched.fetch_pr("owner/repo", 1)


def test_enrich_rest_mergeable_states_skips_executor_for_small_inputs(monkeypatch):
    def fail_executor(*args, **kwargs):
        raise AssertionError("single PR enrichment should not create an executor")

    monkeypatch.setattr(sched.concurrent.futures, "ThreadPoolExecutor", fail_executor)
    monkeypatch.setattr(sched, "fetch_rest_mergeable_state", lambda repo, number: f"{repo}:{number}")
    monkeypatch.setattr(sched, "fetch_compare_branch_freshness", lambda repo, pr: {})

    empty_prs: list[dict[str, object]] = []
    sched.enrich_rest_mergeable_states("owner/repo", empty_prs)
    assert empty_prs == []

    one_pr = [{"number": 10}]
    sched.enrich_rest_mergeable_states("owner/repo", one_pr)
    assert one_pr == [
        {
            "number": 10,
            "restMergeableState": "owner/repo:10",
            "compareStatus": None,
            "compareBehindBy": None,
        }
    ]


def test_enrich_rest_mergeable_states_attaches_state_and_errors(monkeypatch):
    def mock_fetch(repo, number):
        if number == 1:
            return "CLEAN"
        raise RuntimeError("API limit")

    monkeypatch.setattr(sched, "fetch_rest_mergeable_state", mock_fetch)
    monkeypatch.setattr(sched, "fetch_compare_branch_freshness", lambda repo, pr: {})

    prs = [{"number": 1}, {"number": 2}]
    sched.enrich_rest_mergeable_states("owner/repo", prs)

    assert prs[0]["restMergeableState"] == "CLEAN"
    assert prs[0]["compareStatus"] is None
    assert prs[0]["compareBehindBy"] is None
    assert prs[1]["restMergeableStateError"] == "API limit"
    assert prs[1]["compareStatus"] is None
    assert prs[1]["compareBehindBy"] is None


def test_enrich_rest_mergeable_states_uses_bounded_executor_for_multiple_prs(monkeypatch):
    seen_workers = []

    class FakeExecutor:
        def __init__(self, *, max_workers):
            seen_workers.append(max_workers)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def map(self, func, items):
            return [func(item) for item in items]

    monkeypatch.setattr(sched.concurrent.futures, "ThreadPoolExecutor", FakeExecutor)
    monkeypatch.setattr(sched, "fetch_rest_mergeable_state", lambda repo, number: f"{repo}:{number}")
    monkeypatch.setattr(sched, "fetch_compare_branch_freshness", lambda repo, pr: {})

    prs = [{"number": number} for number in range(1, sched.REST_MERGEABLE_STATE_WORKERS + 3)]
    sched.enrich_rest_mergeable_states("owner/repo", prs)

    assert seen_workers == [sched.REST_MERGEABLE_STATE_WORKERS]
    assert prs[0]["restMergeableState"] == "owner/repo:1"
    assert prs[-1]["restMergeableState"] == f"owner/repo:{sched.REST_MERGEABLE_STATE_WORKERS + 2}"


def test_resolve_outdated_review_threads_uses_bounded_executor_for_multiple_threads(monkeypatch):
    seen_workers = []

    class FakeExecutor:
        def __init__(self, *, max_workers):
            seen_workers.append(max_workers)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def map(self, func, items):
            return [func(item) for item in items]

    monkeypatch.setattr(sched.concurrent.futures, "ThreadPoolExecutor", FakeExecutor)
    resolved = []
    monkeypatch.setattr(sched, "resolve_review_thread", resolved.append)
    monkeypatch.setattr(sched, "require_github_actions_mutation_actor", lambda x: None)

    pr = make_pr(
        reviewThreads={
            "nodes": [
                {"id": str(i), "isResolved": False, "isOutdated": True}
                for i in range(sched.REST_MERGEABLE_STATE_WORKERS + 3)
            ]
        }
    )
    count = sched.resolve_outdated_review_threads(pr, dry_run=False)

    assert seen_workers == [sched.REST_MERGEABLE_STATE_WORKERS]
    assert count == sched.REST_MERGEABLE_STATE_WORKERS + 3
    assert len(resolved) == count


def test_cancel_stale_opencode_runs_uses_bounded_executor_for_multiple_runs(monkeypatch):
    seen_workers = []

    class FakeExecutor:
        def __init__(self, *, max_workers):
            seen_workers.append(max_workers)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def map(self, func, items):
            return [func(item) for item in items]

    monkeypatch.setattr(sched.concurrent.futures, "ThreadPoolExecutor", FakeExecutor)
    monkeypatch.setattr(
        sched,
        "stale_opencode_run_ids",
        lambda repo, workflow, pr: [str(i) for i in range(sched.REST_MERGEABLE_STATE_WORKERS + 3)]
    )
    cancelled = []
    monkeypatch.setattr(sched, "run_github_actions", cancelled.append)
    monkeypatch.setattr(sched, "require_github_actions_control_actor", lambda x: None)

    run_ids = sched.cancel_stale_opencode_runs("owner/repo", "workflow", make_pr(), dry_run=False)

    assert seen_workers == [sched.REST_MERGEABLE_STATE_WORKERS]
    assert len(run_ids) == sched.REST_MERGEABLE_STATE_WORKERS + 3
    assert len(cancelled) == len(run_ids)


def test_context_review_and_check_helpers():
    assert sched.context_nodes({}) == []
    assert sched.context_nodes(make_pr()) == []
    assert sched.compare_behind_by({"compareBehindBy": "2"}) == 2
    assert sched.compare_behind_by({"compareBehindBy": "unknown"}) == 0
    assert sched.is_opencode_context({"__typename": "CheckRun", "name": "opencode-review"})
    assert sched.is_opencode_context(
        {
            "__typename": "CheckRun",
            "name": "other",
            "checkSuite": {"workflowRun": {"workflow": {"name": "OpenCode Review"}}},
        }
    )
    assert sched.is_opencode_context({"context": "opencode-review"})
    assert not sched.is_opencode_context({"context": "strix"})
    assert sched.is_strix_context(strix_check())
    assert sched.is_strix_context(strix_check(workflow="Strix"))
    assert sched.is_strix_context({"context": "Strix Security Scan"})
    assert sched.is_strix_context({"__typename": "CheckRun", "name": "strix", "checkSuite": {"workflowRun": {"workflow": None}}})
    assert not sched.is_strix_context({"context": "lint"})
    assert sched.actions_job_id_from_details_url(None) is None
    assert sched.actions_job_id_from_details_url("https://github.com/owner/repo/actions/runs/123/job/456?pr=1") == "456"
    assert sched.actions_job_id_from_details_url("https://github.com/owner/repo/actions/runs/123") is None
    check_jobs = make_pr(
        statusCheckRollup={
            "contexts": {
                "nodes": [
                    opencode_check(details_url="https://github.com/owner/repo/actions/runs/1/job/11"),
                    strix_check(details_url="https://github.com/owner/repo/actions/runs/2/job/22"),
                ]
            }
        }
    )
    assert sched.matching_actions_job_id(check_jobs, sched.is_opencode_context) == "11"
    assert sched.matching_actions_job_id(check_jobs, sched.is_strix_context) == "22"
    no_job_url = make_pr(statusCheckRollup={"contexts": {"nodes": [opencode_check()]}})
    assert sched.matching_actions_job_id(no_job_url, sched.is_opencode_context) is None

    assert sched.parse_github_datetime(None) is None
    assert sched.parse_github_datetime("not-a-date") is None
    assert sched.parse_github_datetime("2026-06-25T07:00:00Z") == datetime(2026, 6, 25, 7, 0, tzinfo=timezone.utc)
    assert sched.parse_github_datetime("2026-06-25T07:00:00") == datetime(2026, 6, 25, 7, 0, tzinfo=timezone.utc)
    assert sched.running_check_state({}) == "absent"
    assert sched.running_check_state({"status": "IN_PROGRESS"}) == "running"
    assert sched.running_check_state({"status": "COMPLETED"}) == "complete"

    missing_state = make_pr(
        statusCheckRollup={
            "contexts": {
                "nodes": [
                    {
                        "__typename": "CheckRun",
                        "name": "opencode-review",
                        "checkSuite": {"workflowRun": {"workflow": {"name": "OpenCode Review"}}},
                    }
                ]
            }
        }
    )
    assert not sched.opencode_in_progress(missing_state)
    assert sched.opencode_progress_state(missing_state, stale_after_minutes=45) == "absent"

    running = make_pr(statusCheckRollup={"contexts": {"nodes": [opencode_check()]}})
    assert sched.opencode_in_progress(running)
    assert sched.opencode_progress_state(running, stale_after_minutes=45) == "running"
    recent_running = make_pr(
        statusCheckRollup={
            "contexts": {
                "nodes": [
                    opencode_check(started_at="2026-06-25T07:30:00Z"),
                ]
            }
        }
    )
    assert (
        sched.opencode_progress_state(
            recent_running,
            stale_after_minutes=45,
            now=datetime(2026, 6, 25, 8, 0, tzinfo=timezone.utc),
        )
        == "running"
    )
    stale = make_pr(
        statusCheckRollup={
            "contexts": {
                "nodes": [
                    opencode_check(started_at="2026-06-25T07:00:00Z"),
                    {"context": "unrelated", "state": "PENDING"},
                ]
            }
        }
    )
    assert (
        sched.opencode_progress_state(
            stale,
            stale_after_minutes=45,
            now=datetime(2026, 6, 25, 8, 0, tzinfo=timezone.utc),
        )
        == "stale"
    )
    complete = make_pr(
        statusCheckRollup={"contexts": {"nodes": [{"context": "opencode-review", "state": "SUCCESS"}]}}
    )
    assert not sched.opencode_in_progress(complete)
    assert sched.opencode_progress_state(complete, stale_after_minutes=45) == "complete"
    unrelated = make_pr(statusCheckRollup={"contexts": {"nodes": [{"context": "strix", "state": "PENDING"}]}})
    assert not sched.opencode_in_progress(unrelated)
    assert sched.opencode_progress_state(unrelated, stale_after_minutes=45) == "absent"
    assert sched.strix_evidence_state(make_pr()) == "missing"
    assert sched.strix_evidence_state(unrelated) == "running"
    mixed_contexts = make_pr(
        statusCheckRollup={"contexts": {"nodes": [{"context": "lint", "state": "SUCCESS"}, strix_check()]}}
    )
    assert sched.strix_evidence_state(mixed_contexts) == "complete"
    unknown_running = make_pr(
        statusCheckRollup={"contexts": {"nodes": [strix_check(status="", conclusion="")]}}
    )
    assert sched.strix_evidence_state(unknown_running) == "running"
    assert sched.strix_evidence_state(make_pr(statusCheckRollup={"contexts": {"nodes": [strix_check()]}})) == "complete"
    assert (
        sched.strix_evidence_state(make_pr(statusCheckRollup={"contexts": {"nodes": [strix_check(conclusion="FAILURE")]}}))
        == "complete"
    )

    threaded = make_pr(
        reviewThreads={
            "nodes": [
                {"id": "active", "isResolved": False},
                {"id": "resolved", "isResolved": True},
                {"id": "outdated", "isResolved": False, "isOutdated": True},
            ]
        }
    )
    assert sched.unresolved_thread_count(threaded) == 1
    assert sched.outdated_thread_ids(threaded) == ["outdated"]
    assert sched.review_author_login({}) == ""
    assert sched.review_author_login({"author": {"login": "OpenCode-Agent"}}) == "opencode-agent"
    assert sched.is_opencode_review(opencode_review())
    assert sched.is_opencode_review(opencode_review(login="opencode-agent[bot]"))
    assert not sched.is_opencode_review(opencode_review(login="human"))


def test_review_state_and_failed_checks():
    pr = make_pr(reviews={"nodes": [opencode_review("APPROVED", "old"), opencode_review("APPROVED", "head")]})
    assert sched.current_head_review_state(pr, "APPROVED")
    assert sched.has_current_head_approval(pr)
    assert not sched.has_current_head_changes_requested(pr)
    exact_head = "a" * 40
    stale_body_head = "b" * 40
    body_sha_mismatch = make_pr(
        headRefOid=exact_head,
        reviews={
            "nodes": [
                {
                    **opencode_review("APPROVED", exact_head),
                    "body": f"## Gate evidence\n\n- Head SHA: `{stale_body_head}`",
                }
            ]
        },
    )
    assert sched.review_body_head_sha(body_sha_mismatch["reviews"]["nodes"][0]) == stale_body_head
    assert not sched.has_current_head_approval(body_sha_mismatch)
    body_sha_match = make_pr(
        headRefOid=exact_head,
        reviews={
            "nodes": [
                {
                    **opencode_review("APPROVED", exact_head),
                    "body": f"## Gate evidence\n\n- Head SHA: `{exact_head.upper()}`",
                }
            ]
        },
    )
    assert sched.has_current_head_approval(body_sha_match)
    deterministic_fallback = make_pr(
        headRefOid=exact_head,
        reviews={
            "nodes": [
                {
                    **opencode_review("APPROVED", exact_head),
                    "body": (
                        "OpenCode model attempts did not emit a usable current-head "
                        "control block, so the approval gate used deterministic "
                        "current-head evidence instead of model prose."
                    ),
                }
            ]
        },
    )
    assert sched.is_deterministic_fallback_approval(
        deterministic_fallback["reviews"]["nodes"][0]
    )
    assert not sched.is_deterministic_fallback_approval(
        opencode_review("CHANGES_REQUESTED", exact_head)
    )
    assert not sched.has_current_head_approval(deterministic_fallback)
    stale_review = make_pr(
        reviews={
            "nodes": [
                opencode_review(
                    "APPROVED",
                    "head",
                    submitted_at="2026-06-25T06:59:59Z",
                )
            ]
        }
    )
    assert sched.has_current_head_approval(stale_review)
    same_timestamp_review = make_pr(
        reviews={
            "nodes": [
                opencode_review(
                    "APPROVED",
                    "head",
                    submitted_at="2026-06-25T07:00:00Z",
                )
            ]
        }
    )
    assert sched.has_current_head_approval(same_timestamp_review)
    missing_review_time = make_pr(
        reviews={
            "nodes": [
                {
                    "state": "APPROVED",
                    "author": {"login": "opencode-agent"},
                    "commit": {"oid": "head"},
                }
            ]
        }
    )
    assert sched.has_current_head_approval(missing_review_time)
    human_review_only = make_pr(
        reviews={"nodes": [opencode_review("APPROVED", "head", login="human")]}
    )
    assert not sched.has_current_head_approval(human_review_only)
    superseded = make_pr(
        reviews={
            "nodes": [
                opencode_review("CHANGES_REQUESTED", "head"),
                opencode_review("APPROVED", "head"),
            ]
        }
    )
    assert sched.has_current_head_approval(superseded)
    assert not sched.has_current_head_changes_requested(superseded)

    failed = make_pr(
        statusCheckRollup={
            "contexts": {
                "nodes": [
                    {"__typename": "CheckRun", "name": "strix", "conclusion": "FAILURE"},
                    {"context": "lint", "state": "ERROR"},
                    {"context": "ok", "state": "SUCCESS"},
                ]
            }
        }
    )
    assert sched.failed_status_checks(failed) == ["strix", "lint"]
    action_required = make_pr(
        statusCheckRollup={
            "contexts": {
                "nodes": [
                    {"__typename": "CheckRun", "name": "opencode-review", "conclusion": "ACTION_REQUIRED"},
                    {"context": "lint", "state": "SUCCESS"},
                ]
            }
        }
    )
    assert sched.failed_status_checks(action_required) == []
    assert sched.action_required_checks(action_required) == ["opencode-review"]
    assert sched.workflow_action_required_reason(["a", "b", "c", "d", "e", "f"]).startswith(
        "workflow action required: a, b, c, d, e, +1 more"
    )
    manual_strix_supersedes_pr_target_failure = make_pr(
        statusCheckRollup={
            "contexts": {
                "nodes": [
                    {"__typename": "CheckRun", "name": "strix", "conclusion": "FAILURE"},
                    {"context": "strix", "state": "SUCCESS"},
                    {"context": "lint", "state": "ERROR"},
                ]
            }
        }
    )
    assert sched.failed_status_checks(manual_strix_supersedes_pr_target_failure) == ["lint"]


def test_run_command_failure_scrubs_secrets(monkeypatch):
    import subprocess

    class MockProcess:
        def __init__(self, returncode, stdout, stderr):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def mock_run(args, **kwargs):
        stderr_msg = "Error using Token secret_token_123 and bearer super_secret"
        if "fail" in args:
            raise subprocess.CalledProcessError(1, args, output="", stderr=stderr_msg)
        return MockProcess(0, "success", "")

    monkeypatch.setattr(subprocess, "run", mock_run)

    assert sched.run(["success"]) == "success"

    token_placeholder = "ghp_placeholder_token_with_underscores_123"
    with pytest.raises(RuntimeError) as exc_info:
        sched.run(["gh", "api", "fail", "-H", f"Authorization: token {token_placeholder}"])

    error_msg = str(exc_info.value)
    assert token_placeholder not in error_msg
    assert "secret_token_123" not in error_msg
    assert "super_secret" not in error_msg
    assert "***" in error_msg

def test_actions_call_gh_with_expected_arguments(monkeypatch):
    calls = []
    head_sha = "a" * 40
    base_sha = "b" * 40

    def fake_run(args, stdin=None):
        calls.append(args)
        if args[:5] == ["gh", "api", "--method", "GET", "repos/owner/repo/actions/runs"]:
            return '{"workflow_runs": []}'
        return ""

    monkeypatch.setattr(sched, "run", fake_run)
    pr = make_pr(baseRefOid=base_sha, headRefOid=head_sha)
    sched.enable_auto_merge("owner/repo", pr, dry_run=True)
    sched.merge_pr("owner/repo", pr, dry_run=True)
    sched.disable_auto_merge("owner/repo", pr, dry_run=True)
    sched.update_branch("owner/repo", pr, dry_run=True)
    sched.dispatch_strix_evidence("owner/repo", "Strix Security Scan", pr, dry_run=True)
    sched.dispatch_opencode_review("owner/repo", "OpenCode Review", pr, dry_run=True)
    sched.rerun_actions_job("owner/repo", "101", dry_run=True, action="rerun-opencode-review")
    assert calls == []

    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GH_TOKEN", "workflow-token")
    sched.enable_auto_merge("owner/repo", pr, dry_run=False)
    sched.merge_pr("owner/repo", pr, dry_run=False)
    sched.disable_auto_merge("owner/repo", pr, dry_run=False)
    sched.update_branch("owner/repo", pr, dry_run=False)
    sched.dispatch_strix_evidence("owner/repo", "Strix Security Scan", pr, dry_run=False)
    sched.dispatch_opencode_review("owner/repo", "OpenCode Review", pr, dry_run=False)
    assert calls[0][:4] == ["gh", "pr", "merge", "1"]
    assert "--squash" in calls[0]
    assert calls[0][-2:] == ["--match-head-commit", head_sha]
    assert calls[1] == [
        "gh",
        "pr",
        "merge",
        "1",
        "--repo",
        "owner/repo",
        "--squash",
        "--match-head-commit",
        head_sha,
    ]
    assert calls[2] == ["gh", "pr", "merge", "1", "--repo", "owner/repo", "--disable-auto"]
    assert calls[3][:4] == ["gh", "api", "-X", "PUT"]
    assert calls[3][-1] == f"expected_head_sha={head_sha}"
    assert calls[4][:5] == ["gh", "workflow", "run", "Strix Security Scan", "--repo"]
    assert calls[5][:5] == ["gh", "api", "--method", "GET", "repos/owner/repo/actions/runs"]
    assert calls[6][:5] == ["gh", "api", "--method", "GET", "repos/owner/repo/actions/runs"]
    assert calls[7][:5] == ["gh", "workflow", "run", "OpenCode Review", "--repo"]
    calls.clear()

    required_workflow_pr = make_pr(
        statusCheckRollup={
            "contexts": {
                "nodes": [
                    opencode_check(details_url="https://github.com/owner/repo/actions/runs/1/job/101"),
                    strix_check(details_url="https://github.com/owner/repo/actions/runs/2/job/202"),
                ]
            }
        }
    )
    sched.dispatch_opencode_review("owner/repo", "OpenCode Review", required_workflow_pr, dry_run=False)
    sched.dispatch_strix_evidence("owner/repo", "Strix Security Scan", required_workflow_pr, dry_run=False)
    assert calls[:2] == [
        ["gh", "api", "--method", "GET", "repos/owner/repo/actions/runs", "-f", "status=queued", "-F", "per_page=100"],
        ["gh", "api", "--method", "GET", "repos/owner/repo/actions/runs", "-f", "status=in_progress", "-F", "per_page=100"],
    ]
    assert calls[2:] == [
        ["gh", "api", "-X", "POST", "repos/owner/repo/actions/jobs/101/rerun"],
        ["gh", "api", "-X", "POST", "repos/owner/repo/actions/jobs/202/rerun"],
    ]


def test_actions_control_uses_workflow_token_when_mutation_token_is_app(monkeypatch):
    calls = []

    def fake_run_with_env(args, *, stdin=None, env=None):
        calls.append((args, stdin, None if env is None else env.get("GH_TOKEN")))
        if args[:5] == ["gh", "api", "--method", "GET", "repos/owner/repo/actions/runs"]:
            return '{"workflow_runs": []}'
        return ""

    monkeypatch.setattr(sched, "run_with_env", fake_run_with_env)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GH_TOKEN", "opencode-app-token")
    monkeypatch.setenv("SCHEDULER_ACTIONS_TOKEN", "workflow-actions-token")

    pr = make_pr(baseRefOid="b" * 40, headRefOid="a" * 40)
    sched.rerun_actions_job("owner/repo", "101", dry_run=False, action="rerun-opencode-review")
    sched.dispatch_strix_evidence("owner/repo", "Strix Security Scan", pr, dry_run=False)
    sched.dispatch_opencode_review("owner/repo", "OpenCode Review", pr, dry_run=False)

    assert [call[2] for call in calls] == ["workflow-actions-token"] * len(calls)
    assert calls[0][0] == ["gh", "api", "-X", "POST", "repos/owner/repo/actions/jobs/101/rerun"]
    assert calls[1][0][:5] == ["gh", "workflow", "run", "Strix Security Scan", "--repo"]
    assert calls[2][0][:5] == ["gh", "api", "--method", "GET", "repos/owner/repo/actions/runs"]
    assert calls[3][0][:5] == ["gh", "api", "--method", "GET", "repos/owner/repo/actions/runs"]
    assert calls[4][0][:5] == ["gh", "workflow", "run", "OpenCode Review", "--repo"]


def test_missing_evidence_dispatch_uses_central_required_workflow_repository(monkeypatch):
    calls = []
    head_sha = "a" * 40
    base_sha = "b" * 40

    def fake_run_with_env(args, *, stdin=None, env=None):
        calls.append((args, None if env is None else env.get("GH_TOKEN")))
        if args[:5] == ["gh", "api", "--method", "GET", "repos/owner/repo/actions/runs"]:
            return '{"workflow_runs": []}'
        return ""

    monkeypatch.setattr(sched, "run_with_env", fake_run_with_env)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GH_TOKEN", "opencode-app-token")
    monkeypatch.setenv("SCHEDULER_ACTIONS_TOKEN", "workflow-actions-token")
    monkeypatch.setenv("SCHEDULER_REQUIRED_WORKFLOW_REPOSITORY", "ContextualWisdomLab/.github")
    monkeypatch.setenv("SCHEDULER_REQUIRED_WORKFLOW_REF", "main")

    pr = make_pr(baseRefName="develop", baseRefOid=base_sha, headRefOid=head_sha)
    sched.dispatch_strix_evidence("owner/repo", "Strix Security Scan", pr, dry_run=False)
    sched.dispatch_opencode_review("owner/repo", "OpenCode Review", pr, dry_run=False)

    strix_call = calls[0][0]
    opencode_call = calls[-1][0]

    assert calls and all(call[1] == "workflow-actions-token" for call in calls)
    assert strix_call[:7] == [
        "gh",
        "workflow",
        "run",
        "Strix Security Scan",
        "--repo",
        "ContextualWisdomLab/.github",
        "--ref",
    ]
    assert strix_call[7] == "main"
    assert "-f" in strix_call
    assert "target_repository=owner/repo" in strix_call
    assert f"pr_base_sha={base_sha}" in strix_call
    assert f"pr_head_sha={head_sha}" in strix_call

    assert opencode_call[:7] == [
        "gh",
        "workflow",
        "run",
        "OpenCode Review",
        "--repo",
        "ContextualWisdomLab/.github",
        "--ref",
    ]
    assert opencode_call[7] == "main"
    assert "target_repository=owner/repo" in opencode_call
    assert "pr_base_ref=develop" in opencode_call
    assert f"pr_base_sha={base_sha}" in opencode_call
    assert f"pr_head_sha={head_sha}" in opencode_call


def test_dispatch_opencode_review_force_cancels_same_pr_old_head_runs(monkeypatch):
    calls = []
    head_sha = "a" * 40
    base_sha = "b" * 40
    stale_same_pr = {
        "id": 9001,
        "name": "OpenCode Review",
        "head_sha": "old",
        "pull_requests": [{"number": 1}],
    }
    current_same_pr = {
        "id": 9002,
        "name": "OpenCode Review",
        "head_sha": head_sha,
        "pull_requests": [{"number": 1}],
    }
    stale_other_pr = {
        "id": 9003,
        "name": "OpenCode Review",
        "head_sha": "old",
        "pull_requests": [{"number": 2}],
    }
    stale_strix = {
        "id": 9004,
        "name": "Strix Security Scan",
        "head_sha": "old",
        "pull_requests": [{"number": 1}],
    }

    def fake_run(args, stdin=None):
        calls.append(args)
        if args[:5] == ["gh", "api", "--method", "GET", "repos/owner/repo/actions/runs"]:
            if "status=queued" in args:
                return json.dumps({"workflow_runs": [stale_same_pr, current_same_pr]})
            return json.dumps({"workflow_runs": [stale_other_pr, stale_strix]})
        return ""

    monkeypatch.setattr(sched, "run", fake_run)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GH_TOKEN", "workflow-token")

    sched.dispatch_opencode_review(
        "owner/repo",
        "OpenCode Review",
        make_pr(baseRefOid=base_sha, headRefOid=head_sha),
        dry_run=False,
    )

    assert ["gh", "api", "--method", "GET", "repos/owner/repo/actions/runs", "-f", "status=queued", "-F", "per_page=100"] in calls
    assert ["gh", "api", "-X", "POST", "repos/owner/repo/actions/runs/9001/force-cancel"] in calls
    assert not any("9002/force-cancel" in " ".join(call) for call in calls)
    assert not any("9003/force-cancel" in " ".join(call) for call in calls)
    assert not any("9004/force-cancel" in " ".join(call) for call in calls)
    assert calls[-1][:5] == ["gh", "workflow", "run", "OpenCode Review", "--repo"]


def test_mutations_refuse_local_credentials(monkeypatch):
    calls = []
    monkeypatch.setattr(sched, "run", lambda args: calls.append(args) or "")
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setenv("GH_TOKEN", "local-token")

    for mutation in (sched.update_branch, sched.enable_auto_merge, sched.merge_pr, sched.disable_auto_merge):
        with pytest.raises(RuntimeError, match="refused outside GitHub Actions"):
            mutation("owner/repo", make_pr(), dry_run=False)
    rerun_pr = make_pr(
        statusCheckRollup={
            "contexts": {
                "nodes": [
                    opencode_check(details_url="https://github.com/owner/repo/actions/runs/1/job/101"),
                ]
            }
        }
    )
    with pytest.raises(RuntimeError, match="refused outside GitHub Actions"):
        sched.dispatch_opencode_review("owner/repo", "OpenCode Review", rerun_pr, dry_run=False)
    assert calls == []

    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("SCHEDULER_ACTIONS_TOKEN", raising=False)
    for mutation in (sched.update_branch, sched.enable_auto_merge, sched.merge_pr, sched.disable_auto_merge):
        with pytest.raises(RuntimeError, match="refused without GH_TOKEN"):
            mutation("owner/repo", make_pr(), dry_run=False)
    with pytest.raises(RuntimeError, match="refused without SCHEDULER_ACTIONS_TOKEN or GH_TOKEN"):
        sched.dispatch_opencode_review("owner/repo", "OpenCode Review", rerun_pr, dry_run=False)
    assert calls == []


def test_mutation_token_labels_follow_selected_scheduler_credential(monkeypatch):
    monkeypatch.delenv("SCHEDULER_MUTATION_TOKEN_SOURCE", raising=False)
    assert sched.mutation_token_label() == "workflow GITHUB_TOKEN"
    assert sched.mutation_actor_label() == "github-actions[bot]"

    monkeypatch.setenv("SCHEDULER_MUTATION_TOKEN_SOURCE", "opencode-app")
    assert sched.mutation_token_label() == "OpenCode app token"
    assert sched.mutation_actor_label() == "OpenCode GitHub App"

    monkeypatch.setenv("SCHEDULER_MUTATION_TOKEN_SOURCE", "PR_REVIEW_MERGE_TOKEN")
    assert sched.mutation_token_label() == "PR_REVIEW_MERGE_TOKEN"
    assert sched.mutation_actor_label() == "configured workflow credential"


def test_resolve_outdated_review_threads_uses_github_actions_actor(monkeypatch):
    calls = []
    pr = make_pr(
        reviewThreads={
            "nodes": [
                {"id": "thread-1", "isResolved": False, "isOutdated": True},
                {"id": "thread-2", "isResolved": True, "isOutdated": True},
                {"id": "thread-3", "isResolved": False, "isOutdated": False},
                {"id": "thread-4", "isResolved": False, "isOutdated": True},
            ]
        }
    )

    def fake_graphql(query, **fields):
        calls.append((query, fields))
        return {"data": {"resolveReviewThread": {"thread": {"id": fields["threadId"], "isResolved": True}}}}

    monkeypatch.setattr(sched, "gh_graphql", fake_graphql)
    assert sched.resolve_outdated_review_threads(pr, dry_run=True) == 2
    assert calls == []

    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setenv("GH_TOKEN", "local-token")
    with pytest.raises(RuntimeError, match="refused outside GitHub Actions"):
        sched.resolve_outdated_review_threads(pr, dry_run=False)
    assert calls == []

    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GH_TOKEN", "workflow-token")
    assert sched.resolve_outdated_review_threads(pr, dry_run=False) == 2
    assert [fields["threadId"] for _, fields in calls] == ["thread-1", "thread-4"]
    assert all(query == sched.RESOLVE_REVIEW_THREAD_MUTATION for query, _ in calls)


def test_print_summary_writes_github_step_summary(monkeypatch, tmp_path, capsys):
    summary_path = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_path))
    conflict_reason = sched.merge_conflict_guidance(
        make_pr(
            number=7,
            headRefName="feature|x",
            files={"nodes": [{"path": "scripts/ci/pr_review_merge_scheduler.py"}, {"path": "tests/test_pr_review_merge_scheduler.py"}]},
        ),
        "DIRTY",
    )
    decisions = [
        sched.Decision(7, "block", conflict_reason),
        sched.Decision(
            8,
            "update_branch",
            "current-head OpenCode review approved; branch update requested with workflow GITHUB_TOKEN inside GitHub Actions as github-actions[bot]",
        ),
        sched.Decision(
            12,
            "merge",
            "current head is approved; direct merge requested with workflow GITHUB_TOKEN and --match-head-commit",
        ),
        sched.Decision(
            9,
            "disable_auto_merge",
            "auto-merge disabled; OpenCode review does not postdate the current head commit; wait for a fresh same-head OpenCode review",
        ),
        sched.Decision(
            10,
            "wait",
            "workflow action required: opencode-review; approve or unblock the GitHub Actions run before treating checks as failed or passed",
            ("Would resolve 1 outdated review thread(s) before active unresolved-thread checks; outdated diff comments are not current-head review blockers.",),
        ),
        sched.Decision(
            11,
            "wait",
            "current-head OpenCode review approved, but head repo fork/repo is external and not writable by the scheduler credential; ask the PR author to update the branch against the base branch, or enable a maintainer-writable head path before rerunning",
        ),
    ]

    sched.print_summary(decisions, dry_run=True, base_branch="main", project_flow="github-flow")

    output = capsys.readouterr().out
    assert "PR #7: block: merge conflict: DIRTY" in output
    payload = json.loads(output.splitlines()[-1])
    assert payload["schema_version"] == "pr-review-merge-scheduler/v2"
    assert payload["base_branch"] == "main"
    assert payload["counts"] == {"block": 1, "disable_auto_merge": 1, "merge": 1, "update_branch": 1, "wait": 2}
    assert payload["dry_run"] is True
    assert payload["inspected"] == 6
    assert payload["project_flow"] == "github-flow"
    assert payload["decisions"][0]["contract_decision"] == "WAIT"
    assert payload["decisions"][1]["contract_decision"] == "UPDATE_BRANCH"
    assert payload["decisions"][2]["contract_decision"] == "NO_ACTION"
    assert payload["decisions"][3]["contract_decision"] == "WAIT"
    assert payload["decisions"][4]["contract_decision"] == "WAIT"
    assert payload["decisions"][5]["contract_decision"] == "WAIT"
    assert payload["decisions"][4]["notes"] == [
        "Would resolve 1 outdated review thread(s) before active unresolved-thread checks; outdated diff comments are not current-head review blockers."
    ]
    assert payload["decisions"][0]["guidance"]["type"] == "merge_conflict_repair"
    assert payload["decisions"][0]["guidance"]["merge_state"] == "DIRTY"
    assert payload["decisions"][0]["guidance"]["base_ref"] == "main"
    assert payload["decisions"][0]["guidance"]["head_ref"] == "feature|x"
    assert payload["decisions"][0]["guidance"]["changed_files_to_inspect"] == [
        "scripts/ci/pr_review_merge_scheduler.py",
        "tests/test_pr_review_merge_scheduler.py",
    ]
    assert "update-branch cannot choose" in payload["decisions"][0]["guidance"]["automation_limit"]
    assert "gh pr checkout 7" in payload["decisions"][0]["guidance"]["commands"]
    assert "git merge --no-ff origin/main" in payload["decisions"][0]["guidance"]["commands"]
    assert payload["decisions"][1]["guidance"]["type"] == "github_actions_update_branch"
    assert payload["decisions"][1]["guidance"]["actor"] == "github-actions[bot]"
    assert payload["decisions"][1]["guidance"]["token"] == "workflow GITHUB_TOKEN"
    assert payload["decisions"][1]["guidance"]["required_permission"] == "pull-requests: write"
    assert payload["decisions"][1]["guidance"]["head_guard"] == "expected_head_sha"
    assert payload["decisions"][2]["guidance"]["type"] == "github_actions_direct_merge"
    assert payload["decisions"][2]["guidance"]["required_permission"] == "contents: write"
    assert payload["decisions"][2]["guidance"]["head_guard"] == "gh pr merge --match-head-commit"
    assert payload["decisions"][3]["guidance"]["type"] == "unsafe_auto_merge_disabled"
    assert payload["decisions"][4]["guidance"]["type"] == "workflow_action_required"
    assert payload["decisions"][4]["guidance"]["checks"] == "opencode-review"
    assert payload["decisions"][5]["guidance"]["type"] == "external_head_update_required"
    assert payload["decisions"][5]["guidance"]["head_repository"] == "fork/repo"
    summary = summary_path.read_text(encoding="utf-8")
    assert "## PR review merge scheduler" in summary
    assert "| #7 | block | merge conflict: DIRTY; base=main, head=feature\\|x; changed files to inspect first:" in summary
    assert "do not retry update-branch until the conflict is repaired" in summary
    assert "### Outdated review threads" in summary
    assert "Would resolve 1 outdated review thread(s)" in summary
    assert (
        "| #8 | update_branch | current-head OpenCode review approved; "
        "branch update requested with workflow GITHUB_TOKEN inside GitHub Actions as github-actions[bot] |"
    ) in summary
    assert "| #12 | merge | current head is approved; direct merge requested with workflow GITHUB_TOKEN" in summary
    assert "fresh same-head OpenCode review" in summary
    assert "### Conflict repair" in summary
    assert "When GitHub shows `Conflicting`" in summary
    assert "`update-branch` is not a conflict resolver" in summary
    assert "PR #7 is `DIRTY` against `main` from `feature\\|x`:" not in summary
    assert "PR #7 is `DIRTY` against `main` from `feature|x`:" in summary
    assert "gh pr checkout 7" in summary
    assert "git fetch origin main" in summary
    assert "git merge --no-ff origin/main" in summary
    assert "Changed files to inspect first:" in summary
    assert "- `scripts/ci/pr_review_merge_scheduler.py`" in summary
    assert "- `tests/test_pr_review_merge_scheduler.py`" in summary
    assert "git push --force-with-lease" in summary
    assert "### Branch update requests" in summary
    assert "Requested `update-branch` for PR #8 with `workflow GITHUB_TOKEN`" in summary
    assert "not from a maintainer's local `gh` credential" in summary
    assert "refuses a non-dry-run `update-branch` outside GitHub Actions" in summary
    assert "needs `pull-requests: write`" in summary
    assert "does not require the scheduler job to widen repository `contents` to write" in summary
    assert "github-actions[bot]" in summary
    assert "### Workflow action required" in summary
    assert "`ACTION_REQUIRED` means GitHub Actions is waiting for approval" in summary
    assert "- PR #10: workflow action required: opencode-review" in summary
    assert "### External head update required" in summary
    assert "mutation-capability limit" in summary
    assert "- PR #11: ask the author of `fork/repo` to update the branch" in summary


def test_write_actions_summary_is_noop_without_summary_path(monkeypatch):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

    sched.write_actions_summary(
        [sched.Decision(1, "block", "merge conflict: DIRTY; base=main, head=feature")],
        counts={"block": 1},
        dry_run=True,
        base_branch="main",
        project_flow="github-flow",
    )


def test_summary_section_helpers_handle_empty_and_action_error_cases():
    wait_decisions = [sched.Decision(1, "wait", "nothing to do")]
    assert sched.conflict_repair_summary(wait_decisions) == []
    assert sched.update_branch_summary(wait_decisions) == []
    assert sched.external_head_update_summary(wait_decisions) == []
    assert sched.external_head_merge_summary(wait_decisions) == []
    assert sched.workflow_action_required_summary(wait_decisions) == []
    assert sched.outdated_thread_cleanup_summary(wait_decisions) == []
    assert sched.action_error_summary(wait_decisions) == []

    outdated_lines = sched.outdated_thread_cleanup_summary(
        [
            sched.Decision(
                4,
                "wait",
                "current head is approved; auto-merge already enabled",
                ("Would resolve 1 outdated review thread(s) before active unresolved-thread checks; outdated diff comments are not current-head review blockers.",),
            )
        ]
    )
    assert "### Outdated review threads" in outdated_lines
    assert "stale UI conversations do not block current-head decisions" in "\n".join(outdated_lines)
    assert "- PR #4: Would resolve 1 outdated review thread(s)" in "\n".join(outdated_lines)

    action_required_lines = sched.workflow_action_required_summary(
        [
            sched.Decision(
                3,
                "wait",
                "workflow action required: opencode-review; approve or unblock the GitHub Actions run before treating checks as failed or passed",
            )
        ]
    )
    assert "### Workflow action required" in action_required_lines
    assert "not a source-code failure" in "\n".join(action_required_lines)
    assert "- PR #3: workflow action required: opencode-review" in "\n".join(action_required_lines)

    lines = sched.action_error_summary([sched.Decision(2, "action_error", "permission failed")])
    assert "### Action errors" in lines
    assert "not source-code review findings" in "\n".join(lines)
    assert "- PR #2: permission failed" in lines

    external_merge_lines = sched.external_head_merge_summary(
        [
            sched.Decision(
                5,
                "wait",
                "current-head OpenCode review approved, but head repo fork/repo is external; fork or external PR heads are excluded from scheduler direct merge and auto-merge. A maintainer must merge manually after required checks, same-head OpenCode approval, same-head Strix evidence, and unresolved-thread checks stay clean",
            )
        ]
    )
    assert "### External head merge excluded" in external_merge_lines
    assert "- PR #5: `fork/repo` is external" in "\n".join(external_merge_lines)


def test_inspect_pr_blocks_and_waits_for_policy_states(monkeypatch):
    assert inspect(make_pr(isDraft=True)).action == "skip"
    assert inspect(make_pr(baseRefName="develop")).reason == "base branch is develop; expected main"
    external_head = inspect(make_pr(headRepository={"nameWithOwner": "fork/repo"}, isCrossRepository=True))
    assert external_head.action == "security_dispatch"
    conflict = inspect(
        make_pr(
            mergeStateStatus="DIRTY",
            files={"nodes": [{"path": "scripts/ci/pr_review_merge_scheduler.py"}]},
        )
    )
    assert conflict.action == "block"
    assert "merge conflict: DIRTY" in conflict.reason
    assert "changed files to inspect first: scripts/ci/pr_review_merge_scheduler.py" in conflict.reason
    assert "base=main, head=feature" in conflict.reason
    assert "gh pr checkout 1" in conflict.reason
    assert "git fetch origin main" in conflict.reason
    assert "git merge --no-ff origin/main" in conflict.reason
    assert "git rebase origin/main" in conflict.reason
    assert "git status --short" in conflict.reason
    assert "resolve conflict markers in the PR branch" in conflict.reason
    assert "rerun focused checks" in conflict.reason
    assert "git push --force-with-lease" in conflict.reason
    assert "push the same feature branch" in conflict.reason
    assert "do not retry update-branch" in conflict.reason
    conflicting = inspect(make_pr(mergeStateStatus="CONFLICTING"))
    assert conflicting.action == "block"
    assert "merge conflict: CONFLICTING" in conflicting.reason
    rest_conflict = inspect(
        make_pr(
            mergeStateStatus="CLEAN",
            restMergeableState="DIRTY",
            autoMergeRequest={"enabledAt": "now"},
        )
    )
    assert rest_conflict.action == "disable_auto_merge"
    assert "merge conflict: DIRTY" in rest_conflict.reason
    unknown_mergeability = inspect(make_pr(mergeStateStatus="CLEAN", restMergeableState="UNKNOWN"))
    assert unknown_mergeability.action == "wait"
    assert unknown_mergeability.reason == (
        "mergeability is still being calculated and no branch freshness evidence is available"
    )
    unknown_auto_merge = inspect(
        make_pr(
            mergeStateStatus="CLEAN",
            restMergeableState="UNKNOWN",
            autoMergeRequest={"enabledAt": "now"},
        )
    )
    assert unknown_auto_merge.action == "disable_auto_merge"
    assert "mergeability is still being calculated" in unknown_auto_merge.reason
    rest_clean = inspect(
        make_pr(
            mergeStateStatus="BEHIND",
            restMergeableState="CLEAN",
            reviews={"nodes": [opencode_review("APPROVED", "head")]},
        )
    )
    assert rest_clean.action == "auto_merge"
    assert inspect(make_pr(reviewThreads={"nodes": [{"isResolved": False}]})).reason == "1 unresolved review thread(s)"
    outdated_only = inspect(
        make_pr(
            reviewThreads={"nodes": [{"id": "outdated-thread", "isResolved": False, "isOutdated": True}]},
            reviews={"nodes": [opencode_review("APPROVED", "head")]},
        )
    )
    assert outdated_only.action == "auto_merge"
    assert outdated_only.notes == (
        "Would resolve 1 outdated review thread(s) before active unresolved-thread checks; outdated diff comments are not current-head review blockers.",
    )
    unresolved_auto = inspect(
        make_pr(
            reviewThreads={"nodes": [{"isResolved": False}]},
            autoMergeRequest={"enabledAt": "now"},
        )
    )
    assert unresolved_auto.action == "disable_auto_merge"
    assert "unresolved review thread" in unresolved_auto.reason
    assert inspect(make_pr(reviews={"nodes": [opencode_review("CHANGES_REQUESTED", "head")]})).reason == (
        "current-head OpenCode review requested changes"
    )
    action_required_pr = make_pr(
        statusCheckRollup={
            "contexts": {
                "nodes": [{"__typename": "CheckRun", "name": "opencode-review", "conclusion": "ACTION_REQUIRED"}]
            }
        }
    )
    action_required_decision = inspect(action_required_pr)
    assert action_required_decision.action == "wait"
    assert action_required_decision.reason == (
        "workflow action required: opencode-review; approve or unblock the GitHub Actions run before treating checks as failed or passed"
    )
    action_required_auto = inspect(
        make_pr(
            autoMergeRequest={"enabledAt": "now"},
            statusCheckRollup={
                "contexts": {
                    "nodes": [
                        {"__typename": "CheckRun", "name": "opencode-review", "conclusion": "ACTION_REQUIRED"}
                    ]
                }
            },
        )
    )
    assert action_required_auto.action == "disable_auto_merge"
    assert "workflow action required: opencode-review" in action_required_auto.reason
    same_head_auto = make_pr(
        autoMergeRequest={"enabledAt": "now"},
        reviews={"nodes": [opencode_review("APPROVED", "head", submitted_at="2026-06-25T06:59:59Z")]},
    )
    disabled = []
    monkeypatch.setattr(sched, "disable_auto_merge", lambda repo, pr, dry_run: disabled.append((repo, pr["number"], dry_run)))
    same_head_auto_decision = inspect(same_head_auto)
    assert same_head_auto_decision.action == "wait"
    assert same_head_auto_decision.reason == "current head is approved; auto-merge already enabled"
    assert disabled == []
    blocked_auto = make_pr(
        restMergeableState="blocked",
        autoMergeRequest={"enabledAt": "now"},
        reviews={"nodes": [opencode_review("APPROVED", "head")]},
    )
    blocked_auto_decision = inspect(blocked_auto)
    assert blocked_auto_decision.action == "wait"
    assert "GitHub mergeability is BLOCKED" in blocked_auto_decision.reason
    assert "rerun the scheduler" in blocked_auto_decision.reason

    stale_behind = make_pr(mergeStateStatus="BEHIND", reviews={"nodes": [opencode_review("APPROVED", "old")]})
    dispatched = []
    monkeypatch.setattr(sched, "dispatch_strix_evidence", lambda repo, workflow, pr, dry_run: dispatched.append(workflow))
    monkeypatch.setattr(sched, "dispatch_opencode_review", lambda repo, workflow, pr, dry_run: dispatched.append(workflow))
    stale_behind_decision = inspect(stale_behind)
    assert stale_behind_decision.action == "update_branch"
    assert "branch is outdated before review dispatch" in stale_behind_decision.reason
    assert dispatched == []

    behind = make_pr(mergeStateStatus="BEHIND", reviews={"nodes": [opencode_review("APPROVED", "head")]})
    assert inspect(behind, update_branches=False).reason == "current-head OpenCode review approved; branch update disabled"
    called = []
    monkeypatch.setattr(sched, "update_branch", lambda repo, pr, dry_run: called.append((repo, pr["number"], dry_run)))
    decision = inspect(behind)
    assert decision.action == "update_branch"
    assert "workflow GITHUB_TOKEN" in decision.reason
    assert "github-actions[bot]" in decision.reason
    assert called == [("owner/repo", 1, True)]
    called.clear()
    blocked_behind = make_pr(
        mergeStateStatus="BLOCKED",
        compareBehindBy=2,
        reviews={"nodes": [opencode_review("APPROVED", "head")]},
    )
    blocked_behind_decision = inspect(blocked_behind)
    assert blocked_behind_decision.action == "update_branch"
    assert "base branch is 2 commit(s) ahead" in blocked_behind_decision.reason
    assert "GitHub mergeability is BLOCKED" in blocked_behind_decision.reason
    assert called == [("owner/repo", 1, True)]
    called.clear()
    external_behind = make_pr(
        mergeStateStatus="BEHIND",
        isCrossRepository=True,
        maintainerCanModify=False,
        headRepository={"nameWithOwner": "fork/repo"},
        reviews={"nodes": [opencode_review("APPROVED", "head")]},
    )
    external_decision = inspect(external_behind)
    assert external_decision.action == "wait"
    assert "fork/repo is external and not writable" in external_decision.reason
    assert sched.decision_guidance(external_decision)["type"] == "external_head_update_required"
    assert called == []
    external_mutable = make_pr(
        mergeStateStatus="BEHIND",
        isCrossRepository=True,
        maintainerCanModify=True,
        headRepository={"nameWithOwner": "fork/repo"},
        reviews={"nodes": [opencode_review("APPROVED", "head")]},
    )
    assert inspect(external_mutable).action == "update_branch"
    assert called == [("owner/repo", 1, True)]
    called.clear()
    assert sched.can_update_pr_head("owner/repo", behind)
    assert not sched.can_update_pr_head("owner/repo", external_behind)
    assert sched.can_update_pr_head("owner/repo", external_mutable)
    assert "same-repository head update permission" in sched.non_mutable_head_reason("owner/repo", behind)
    behind_failed = make_pr(
        mergeStateStatus="BEHIND",
        reviews={"nodes": [opencode_review("APPROVED", "head")]},
        statusCheckRollup={"contexts": {"nodes": [{"__typename": "CheckRun", "name": "strix", "conclusion": "FAILURE"}]}},
    )
    failed_decision = inspect(behind_failed)
    assert failed_decision.action == "block"
    assert failed_decision.reason == "failed check(s): strix"
    assert called == []
    called.clear()
    mixed_failure_and_action_required = make_pr(
        reviews={"nodes": [opencode_review("APPROVED", "head")]},
        statusCheckRollup={
            "contexts": {
                "nodes": [
                    {"__typename": "CheckRun", "name": "strix", "conclusion": "FAILURE"},
                    {"__typename": "CheckRun", "name": "opencode-review", "conclusion": "ACTION_REQUIRED"},
                ]
            }
        },
    )
    mixed_decision = inspect(mixed_failure_and_action_required)
    assert mixed_decision.action == "block"
    assert mixed_decision.reason == "failed check(s): strix"
    called.clear()
    behind_action_required = make_pr(
        mergeStateStatus="BEHIND",
        reviews={"nodes": [opencode_review("APPROVED", "head")]},
        statusCheckRollup={
            "contexts": {
                "nodes": [{"__typename": "CheckRun", "name": "opencode-review", "conclusion": "ACTION_REQUIRED"}]
            }
        },
    )
    action_required_decision = inspect(behind_action_required)
    assert action_required_decision.action == "wait"
    assert "workflow action required: opencode-review" in action_required_decision.reason
    assert called == []
    called.clear()
    behind_auto_merge_enabled = make_pr(
        mergeStateStatus="BEHIND",
        reviews={"nodes": [opencode_review("APPROVED", "head")]},
        autoMergeRequest={"enabledAt": "now"},
    )
    disabled.clear()
    behind_auto_merge_decision = inspect(behind_auto_merge_enabled)
    assert behind_auto_merge_decision.action == "update_branch"
    assert "existing auto-merge request remains queued" in behind_auto_merge_decision.reason
    assert called == [("owner/repo", 1, True)]
    assert disabled == []
    called.clear()
    rest_behind = make_pr(
        mergeStateStatus="CLEAN",
        restMergeableState="BEHIND",
        reviews={"nodes": [opencode_review("APPROVED", "head")]},
        autoMergeRequest={"enabledAt": "now"},
    )
    rest_behind_decision = inspect(rest_behind)
    assert rest_behind_decision.action == "update_branch"
    assert "github-actions[bot]" in rest_behind_decision.reason
    assert called == [("owner/repo", 1, True)]
    called.clear()
    blocked_failed_behind_auto = make_pr(
        mergeStateStatus="BLOCKED",
        restMergeableState="BLOCKED",
        compareBehindBy=2,
        reviews={"nodes": [opencode_review("APPROVED", "head")]},
        autoMergeRequest={"enabledAt": "now"},
        statusCheckRollup={
            "contexts": {
                "nodes": [{"__typename": "CheckRun", "name": "strix", "conclusion": "FAILURE"}],
            }
        },
    )
    disabled.clear()
    blocked_failed_behind_decision = inspect(blocked_failed_behind_auto)
    assert blocked_failed_behind_decision.action == "disable_auto_merge"
    assert "failed check(s): strix" in blocked_failed_behind_decision.reason
    assert called == []
    assert disabled == [("owner/repo", 1, True)]
    called.clear()
    blocked_failed_behind_auto_without_opencode_approval = make_pr(
        mergeStateStatus="BLOCKED",
        restMergeableState="BLOCKED",
        compareBehindBy=2,
        autoMergeRequest={"enabledAt": "now"},
        statusCheckRollup={
            "contexts": {
                "nodes": [{"__typename": "CheckRun", "name": "strix", "conclusion": "FAILURE"}],
            }
        },
    )
    blocked_without_opencode_decision = inspect(blocked_failed_behind_auto_without_opencode_approval)
    assert blocked_without_opencode_decision.action == "update_branch"
    assert "auto-merge already enabled" in blocked_without_opencode_decision.reason
    assert "base branch is 2 commit(s) ahead" in blocked_without_opencode_decision.reason
    assert "existing auto-merge request remains queued" in blocked_without_opencode_decision.reason
    assert called == [("owner/repo", 1, True)]
    called.clear()
    blocked_compare_behind_auto = make_pr(
        mergeStateStatus="BLOCKED",
        restMergeableState="BLOCKED",
        compareStatus="behind",
        autoMergeRequest={"enabledAt": "now"},
        statusCheckRollup={
            "contexts": {
                "nodes": [
                    {"__typename": "CheckRun", "name": "strix", "conclusion": "FAILURE"},
                    {"__typename": "CheckRun", "name": "coverage-evidence", "conclusion": "FAILURE"},
                ],
            }
        },
    )
    blocked_compare_behind_decision = inspect(blocked_compare_behind_auto)
    assert blocked_compare_behind_decision.action == "update_branch"
    assert "auto-merge already enabled" in blocked_compare_behind_decision.reason
    assert "base branch is 1 commit(s) ahead" in blocked_compare_behind_decision.reason
    assert "existing auto-merge request remains queued" in blocked_compare_behind_decision.reason
    assert called == [("owner/repo", 1, True)]
    called.clear()
    diverged_failed_auto = make_pr(
        mergeStateStatus="BLOCKED",
        restMergeableState="BLOCKED",
        compareStatus="diverged",
        compareBehindBy=184,
        compareAheadBy=1,
        autoMergeRequest={"enabledAt": "now"},
        statusCheckRollup={
            "contexts": {
                "nodes": [
                    {"__typename": "CheckRun", "name": "coverage-evidence", "conclusion": "FAILURE"},
                    {"__typename": "CheckRun", "name": "opencode-review", "conclusion": "FAILURE"},
                ],
            }
        },
    )
    diverged_failed_decision = inspect(diverged_failed_auto)
    assert diverged_failed_decision.action == "update_branch"
    assert "auto-merge already enabled" in diverged_failed_decision.reason
    assert "base branch is 184 commit(s) ahead" in diverged_failed_decision.reason
    assert "existing auto-merge request remains queued" in diverged_failed_decision.reason
    assert called == [("owner/repo", 1, True)]
    called.clear()
    unknown_compare_behind_auto = make_pr(
        mergeStateStatus="UNKNOWN",
        restMergeableState="UNKNOWN",
        compareStatus="behind",
        autoMergeRequest={"enabledAt": "now"},
        statusCheckRollup={
            "contexts": {
                "nodes": [
                    {"__typename": "CheckRun", "name": "strix", "conclusion": "FAILURE"},
                    {"__typename": "CheckRun", "name": "coverage-evidence", "conclusion": "FAILURE"},
                ],
            }
        },
    )
    unknown_compare_behind_decision = inspect(unknown_compare_behind_auto)
    assert unknown_compare_behind_decision.action == "update_branch"
    assert "auto-merge already enabled" in unknown_compare_behind_decision.reason
    assert "base branch is 1 commit(s) ahead" in unknown_compare_behind_decision.reason
    assert "GitHub mergeability is UNKNOWN" in unknown_compare_behind_decision.reason
    assert "existing auto-merge request remains queued" in unknown_compare_behind_decision.reason
    assert called == [("owner/repo", 1, True)]
    called.clear()
    disabled.clear()
    assert (
        inspect(blocked_failed_behind_auto_without_opencode_approval, update_branches=False).reason
        == "auto-merge already enabled; branch update disabled"
    )
    assert called == []
    assert disabled == []
    behind_auto_without_opencode_approval = make_pr(
        mergeStateStatus="BEHIND",
        autoMergeRequest={"enabledAt": "now"},
    )
    behind_without_opencode_decision = inspect(behind_auto_without_opencode_approval)
    assert behind_without_opencode_decision.action == "update_branch"
    assert behind_without_opencode_decision.reason.startswith("auto-merge already enabled; branch update requested")
    assert "existing auto-merge request remains queued" in behind_without_opencode_decision.reason
    assert called == [("owner/repo", 1, True)]


def test_stale_opencode_run_ids_filters_current_head_and_missing_ids(monkeypatch):
    runs = [
        {"name": "Other", "id": 10, "head_sha": "old", "pull_requests": [{"number": 1}]},
        {"name": "OpenCode Review", "id": 11, "head_sha": "head", "pull_requests": [{"number": 1}]},
        {"name": "OpenCode Review", "id": None, "head_sha": "older", "pull_requests": [{"number": 1}]},
        {"name": "OpenCode Review", "id": 12, "head_sha": "old", "pull_requests": [{"number": 2}]},
        {"name": "OpenCode Review", "id": 13, "head_sha": "old", "pull_requests": [{"number": 1}]},
    ]
    monkeypatch.setattr(sched, "active_workflow_runs", lambda repo: runs)

    assert sched.stale_opencode_run_ids("owner/repo", "OpenCode Review", make_pr()) == ["13"]


def test_inspect_pr_queues_auto_merge_for_approved_conflicts(monkeypatch):
    auto_merges = []
    disables = []
    monkeypatch.setattr(
        sched,
        "enable_auto_merge",
        lambda repo, pr, dry_run: auto_merges.append((repo, pr["number"], dry_run)),
    )
    monkeypatch.setattr(
        sched,
        "disable_auto_merge",
        lambda repo, pr, dry_run: disables.append((repo, pr["number"], dry_run)),
    )

    approved_conflict = make_pr(
        mergeStateStatus="DIRTY",
        reviews={"nodes": [opencode_review("APPROVED", "head")]},
    )
    decision = inspect(approved_conflict)
    assert decision.action == "auto_merge"
    assert "auto-merge enabled and queued while conflict repair remains required" in decision.reason
    assert "merge conflict: DIRTY" in decision.reason
    assert "gh pr checkout 1" in decision.reason
    assert auto_merges == [("owner/repo", 1, True)]
    assert disables == []

    already_queued = inspect(
        make_pr(
            mergeStateStatus="CONFLICTING",
            reviews={"nodes": [opencode_review("APPROVED", "head")]},
            autoMergeRequest={"enabledAt": "now"},
        )
    )
    assert already_queued.action == "wait"
    assert "auto-merge is already enabled" in already_queued.reason
    assert "conflict repair is required" in already_queued.reason
    assert "merge conflict: CONFLICTING" in already_queued.reason
    assert auto_merges == [("owner/repo", 1, True)]
    assert disables == []

    disabled_by_inputs = inspect(
        make_pr(
            mergeStateStatus="DIRTY",
            reviews={"nodes": [opencode_review("APPROVED", "head")]},
        ),
        enable_auto_merge_flag=False,
    )
    assert disabled_by_inputs.action == "wait"
    assert "auto-merge is not queued" in disabled_by_inputs.reason
    assert "merge conflict: DIRTY" in disabled_by_inputs.reason
    assert auto_merges == [("owner/repo", 1, True)]

    external_conflict = inspect(
        make_pr(
            mergeStateStatus="DIRTY",
            isCrossRepository=True,
            headRepository={"nameWithOwner": "fork/repo"},
            reviews={"nodes": [opencode_review("APPROVED", "head")]},
        )
    )
    assert external_conflict.action == "wait"
    assert "fork or external PR heads are excluded from scheduler direct merge and auto-merge" in external_conflict.reason
    assert "merge conflict: DIRTY" in external_conflict.reason
    assert auto_merges == [("owner/repo", 1, True)]

    direct_mode = inspect(
        make_pr(
            mergeStateStatus="DIRTY",
            reviews={"nodes": [opencode_review("APPROVED", "head")]},
        ),
        merge_mode="direct",
    )
    assert direct_mode.action == "wait"
    assert "merge mode is direct" in direct_mode.reason
    assert "merge conflict: DIRTY" in direct_mode.reason
    assert auto_merges == [("owner/repo", 1, True)]


def test_wait_for_updated_branch_head_polls_until_head_changes(monkeypatch):
    fetches = []
    sleeps = []
    same_head = make_pr(
        headRefOid="head",
        mergeStateStatus="BLOCKED",
        restMergeableState="BLOCKED",
        compareBehindBy=1,
    )
    new_head = make_pr(headRefOid="new-head", mergeStateStatus="CLEAN", restMergeableState="CLEAN")

    def fake_fetch_pr(repo, number):
        fetches.append((repo, number))
        return [same_head if len(fetches) == 1 else new_head]

    monkeypatch.setattr(sched, "fetch_pr", fake_fetch_pr)
    monkeypatch.setattr(sched.time, "sleep", lambda seconds: sleeps.append(seconds))

    assert sched.wait_for_updated_branch_head("owner/repo", make_pr(), attempts=3, delay_seconds=0.25) == new_head
    assert fetches == [("owner/repo", 1), ("owner/repo", 1)]
    assert sleeps == [0.25]


def test_wait_for_updated_branch_head_handles_empty_fetch_and_fresh_same_head(monkeypatch):
    fetches = []
    fresh_same_head = make_pr(headRefOid="head", mergeStateStatus="CLEAN", restMergeableState="CLEAN")

    def fake_fetch_pr(repo, number):
        fetches.append((repo, number))
        return [] if len(fetches) == 1 else [fresh_same_head]

    monkeypatch.setattr(sched, "fetch_pr", fake_fetch_pr)
    monkeypatch.setattr(sched.time, "sleep", lambda seconds: None)

    assert sched.short_sha(None) == "<unknown>"
    assert sched.wait_for_updated_branch_head("owner/repo", make_pr(), attempts=2, delay_seconds=0) == fresh_same_head
    assert fetches == [("owner/repo", 1), ("owner/repo", 1)]


def test_wait_for_updated_branch_head_returns_none_when_still_outdated(monkeypatch):
    stale_same_head = make_pr(
        headRefOid="head",
        mergeStateStatus="BLOCKED",
        restMergeableState="BLOCKED",
        compareBehindBy=2,
    )

    monkeypatch.setattr(sched, "fetch_pr", lambda repo, number: [stale_same_head])
    monkeypatch.setattr(sched.time, "sleep", lambda seconds: None)

    assert sched.wait_for_updated_branch_head("owner/repo", make_pr(), attempts=2, delay_seconds=0) is None


def test_inspect_pr_dispatches_strix_after_update_branch_observes_new_head(monkeypatch):
    updated = []
    dispatched = []
    old_head_pr = make_pr(
        mergeStateStatus="BEHIND",
        reviews={"nodes": [opencode_review("APPROVED", "head")]},
        autoMergeRequest={"enabledAt": "now"},
    )
    new_head_pr = make_pr(headRefOid="new-head", reviews={"nodes": []})

    monkeypatch.setattr(sched, "update_branch", lambda repo, pr, dry_run: updated.append((repo, pr["headRefOid"], dry_run)))
    monkeypatch.setattr(sched, "wait_for_updated_branch_head", lambda repo, pr: new_head_pr)
    monkeypatch.setattr(
        sched,
        "dispatch_strix_evidence",
        lambda repo, workflow, pr, dry_run: dispatched.append((repo, workflow, pr["headRefOid"], dry_run)),
    )

    decision = inspect(old_head_pr, dry_run=False)

    assert decision.action == "update_branch"
    assert updated == [("owner/repo", "head", False)]
    assert dispatched == [("owner/repo", "Strix Security Scan", "new-head", False)]
    assert decision.notes == (
        "updated head new-head observed after update-branch; same-head Strix evidence dispatched because workflow-token branch updates must not rely on a PR synchronize event to rerun evidence",
    )


def test_inspect_pr_notes_when_update_branch_head_is_not_observed(monkeypatch):
    updated = []
    pr = make_pr(
        mergeStateStatus="BEHIND",
        reviews={"nodes": [opencode_review("APPROVED", "head")]},
    )

    monkeypatch.setattr(sched, "update_branch", lambda repo, pr, dry_run: updated.append(pr["number"]))
    monkeypatch.setattr(sched, "wait_for_updated_branch_head", lambda repo, pr: None)

    decision = inspect(pr, dry_run=False)

    assert decision.action == "update_branch"
    assert updated == [1]
    assert decision.notes == (
        "update-branch was accepted, but the scheduler did not observe a refreshed PR head within the poll window; the next scheduler run must re-read the PR before review or merge",
    )


def test_inspect_pr_updates_outdated_branch_before_review_dispatch(monkeypatch):
    updated = []
    dispatched = []
    old_head_pr = make_pr(
        mergeStateStatus="BEHIND",
        compareBehindBy=111,
        statusCheckRollup={"contexts": {"nodes": [strix_check(), opencode_check(status="COMPLETED")]}},
    )
    new_head_pr = make_pr(
        headRefOid="new-head",
        statusCheckRollup={"contexts": {"nodes": [strix_check()]}},
    )

    monkeypatch.setattr(sched, "update_branch", lambda repo, pr, dry_run: updated.append((repo, pr["headRefOid"], dry_run)))
    monkeypatch.setattr(sched, "wait_for_updated_branch_head", lambda repo, pr: new_head_pr)
    monkeypatch.setattr(
        sched,
        "dispatch_opencode_review",
        lambda repo, workflow, pr, dry_run: dispatched.append((repo, workflow, pr["headRefOid"], dry_run)),
    )

    decision = inspect(old_head_pr, dry_run=False)

    assert decision.action == "update_branch"
    assert decision.reason.startswith(
        "current head has no OpenCode approval; branch is outdated before review dispatch"
    )
    assert updated == [("owner/repo", "head", False)]
    assert dispatched == [("owner/repo", "OpenCode Review", "new-head", False)]
    assert decision.notes == (
        "updated head new-head observed after update-branch; same-head Strix evidence is complete, so OpenCode review was dispatched",
    )


def test_inspect_pr_update_before_review_dispatch_boundaries():
    behind_pr = make_pr(mergeStateStatus="BEHIND", compareBehindBy=3)

    disabled = inspect(behind_pr, update_branches=False)
    assert disabled.action == "wait"
    assert disabled.reason == "current head has no OpenCode approval; branch update disabled before review dispatch"

    external = inspect(
        make_pr(
            mergeStateStatus="BEHIND",
            compareBehindBy=3,
            isCrossRepository=True,
            maintainerCanModify=False,
            headRepository={"nameWithOwner": "fork/repo"},
        )
    )
    assert external.action == "wait"
    assert external.reason == (
        "current head has no OpenCode approval; branch is outdated before review dispatch, "
        "but head repo fork/repo is not writable by the scheduler credential"
    )

    blocked_but_behind = inspect(
        make_pr(
            mergeStateStatus="BLOCKED",
            restMergeableState="BLOCKED",
            compareBehindBy=7,
        )
    )
    assert blocked_but_behind.action == "update_branch"
    assert "base branch is 7 commit(s) ahead before review dispatch" in blocked_but_behind.reason
    assert "GitHub mergeability is BLOCKED" in blocked_but_behind.reason


def test_post_update_branch_followup_covers_dispatch_boundaries(monkeypatch):
    original = make_pr(headRefOid="old-head")
    opencode_dispatched = []

    def followup(updated_pr, **overrides):
        monkeypatch.setattr(sched, "wait_for_updated_branch_head", lambda repo, pr: updated_pr)
        kwargs = {
            "dry_run": False,
            "trigger_reviews": True,
            "review_dispatch_allowed": True,
            "workflow": "OpenCode Review",
            "security_workflow": "Strix Security Scan",
            "stale_opencode_minutes": 45,
        }
        kwargs.update(overrides)
        return sched.post_update_branch_followup("owner/repo", original, **kwargs)

    assert "without a new head SHA" in followup(make_pr(headRefOid="old-head"))
    assert "review dispatch is disabled" in followup(make_pr(headRefOid="new-head"), trigger_reviews=False)
    assert "review dispatch limit reached" in followup(
        make_pr(headRefOid="new-head"),
        review_dispatch_allowed=False,
    )
    assert "same-head Strix evidence is already running" in followup(
        make_pr(
            headRefOid="new-head",
            statusCheckRollup={"contexts": {"nodes": [strix_check(status="IN_PROGRESS", conclusion="")]}},
        )
    )
    assert "same-head OpenCode review is already running" in followup(
        make_pr(
            headRefOid="new-head",
            statusCheckRollup={"contexts": {"nodes": [strix_check(), opencode_check()]}},
        )
    )

    monkeypatch.setattr(
        sched,
        "dispatch_opencode_review",
        lambda repo, workflow, pr, dry_run: opencode_dispatched.append((repo, workflow, pr["headRefOid"], dry_run)),
    )
    assert "OpenCode review was dispatched" in followup(
        make_pr(
            headRefOid="new-head",
            statusCheckRollup={"contexts": {"nodes": [strix_check()]}},
        )
    )
    assert opencode_dispatched == [("owner/repo", "OpenCode Review", "new-head", False)]


def test_update_branch_summary_includes_followup_notes():
    summary = "\n".join(
        sched.update_branch_summary(
            [
                sched.Decision(
                    12,
                    "update_branch",
                    "branch update requested",
                    ("updated head abc123 observed after update-branch; same-head Strix evidence dispatched",),
                )
            ]
        )
    )

    assert "Follow-up evidence" in summary
    assert "PR #12: updated head abc123 observed after update-branch" in summary


def test_inspect_pr_handles_approved_reviews_and_dispatch(monkeypatch):
    approved = make_pr(reviews={"nodes": [opencode_review("APPROVED", "head")]})
    failed = make_pr(
        reviews={"nodes": [opencode_review("APPROVED", "head")]},
        statusCheckRollup={"contexts": {"nodes": [{"__typename": "CheckRun", "name": "strix", "conclusion": "FAILURE"}]}},
    )
    assert inspect(failed).reason == "failed check(s): strix"
    assert inspect(make_pr(reviews={"nodes": [opencode_review("APPROVED", "head")]}, autoMergeRequest={"enabledAt": "now"})).reason == (
        "current head is approved; auto-merge already enabled"
    )
    approved_with_auto_merge = make_pr(
        reviews={"nodes": [opencode_review("APPROVED", "head")]},
        autoMergeRequest={"enabledAt": "now"},
    )
    assert inspect(approved_with_auto_merge, enable_auto_merge_flag=False).reason == (
        "current head is approved; auto-merge already enabled"
    )
    assert inspect(approved_with_auto_merge, merge_mode="disabled").reason == (
        "current head is approved; auto-merge already enabled"
    )
    assert inspect(approved, enable_auto_merge_flag=False).reason == (
        "current head is approved; auto-merge disabled by scheduler inputs"
    )
    assert inspect(approved, merge_mode="disabled").reason == (
        "current head is approved; merge mode disabled by scheduler inputs"
    )
    assert inspect(approved, merge_mode="unknown").reason == (
        "current head is approved; unsupported merge mode: unknown"
    )
    blocked_approved = make_pr(
        mergeStateStatus="BLOCKED",
        reviews={"nodes": [opencode_review("APPROVED", "head")]},
    )
    assert inspect(blocked_approved, enable_auto_merge_flag=False).reason == (
        "current head is approved; auto-merge disabled by scheduler inputs"
    )
    assert inspect(blocked_approved, merge_mode="disabled").reason == (
        "current head is approved; merge mode disabled by scheduler inputs"
    )
    assert inspect(blocked_approved, merge_mode="unknown").reason == (
        "current head is approved; unsupported merge mode: unknown"
    )
    blocked_unmergeable = make_pr(
        mergeable="UNKNOWN",
        mergeStateStatus="BLOCKED",
        reviews={"nodes": [opencode_review("APPROVED", "head")]},
    )
    assert inspect(blocked_unmergeable, enable_auto_merge_flag=False).reason == (
        "current head is approved; auto-merge disabled by scheduler inputs"
    )
    assert inspect(blocked_unmergeable, merge_mode="disabled").reason == (
        "current head is approved; merge mode disabled by scheduler inputs"
    )
    blocked_unmergeable_direct_or_auto = inspect(blocked_unmergeable, merge_mode="direct_or_auto")
    assert blocked_unmergeable_direct_or_auto.action == "auto_merge"
    assert "GitHub mergeability is BLOCKED" in blocked_unmergeable_direct_or_auto.reason
    blocked_unmergeable_direct = inspect(blocked_unmergeable, merge_mode="direct")
    assert blocked_unmergeable_direct.action == "wait"
    assert blocked_unmergeable_direct.reason == (
        "current head is approved; direct merge waits for CLEAN mergeability, current merge state is BLOCKED"
    )
    external_unmergeable = inspect(
        make_pr(
            mergeable="UNKNOWN",
            mergeStateStatus="BLOCKED",
            isCrossRepository=True,
            headRepository={"nameWithOwner": "fork/repo"},
            reviews={"nodes": [opencode_review("APPROVED", "head")]},
        ),
        merge_mode="direct_or_auto",
    )
    assert external_unmergeable.action == "wait"
    assert "fork or external PR heads are excluded" in external_unmergeable.reason

    direct_merges = []
    monkeypatch.setattr(
        sched,
        "merge_pr",
        lambda repo, pr, dry_run: direct_merges.append((repo, pr["number"], dry_run)),
    )
    blocked_direct = inspect(
        make_pr(
            mergeStateStatus="BLOCKED",
            reviews={"nodes": [opencode_review("APPROVED", "head")]},
        ),
        merge_mode="direct",
    )
    assert blocked_direct.action == "merge"
    assert "GitHub mergeability is BLOCKED" in blocked_direct.reason
    assert direct_merges == [("owner/repo", 1, True)]
    direct = inspect(approved, merge_mode="direct")
    assert direct.action == "merge"
    assert "--match-head-commit" in direct.reason
    assert direct_merges == [("owner/repo", 1, True), ("owner/repo", 1, True)]

    direct_or_auto = inspect(approved, merge_mode="direct_or_auto")
    assert direct_or_auto.action == "merge"
    assert "--match-head-commit" in direct_or_auto.reason
    assert direct_merges == [("owner/repo", 1, True), ("owner/repo", 1, True), ("owner/repo", 1, True)]

    already_auto_direct_or_auto = inspect(
        make_pr(
            autoMergeRequest={"enabledAt": "now"},
            reviews={"nodes": [opencode_review("APPROVED", "head")]},
        ),
        merge_mode="direct_or_auto",
    )
    assert already_auto_direct_or_auto.action == "merge"
    assert "direct merge requested" in already_auto_direct_or_auto.reason
    assert direct_merges == [
        ("owner/repo", 1, True),
        ("owner/repo", 1, True),
        ("owner/repo", 1, True),
        ("owner/repo", 1, True),
    ]

    clean_but_compare_behind = inspect(
        make_pr(
            mergeStateStatus="CLEAN",
            compareBehindBy=20,
            reviews={"nodes": [opencode_review("APPROVED", "head")]},
        ),
        merge_mode="direct_or_auto",
    )
    assert clean_but_compare_behind.action == "merge"
    assert "direct merge requested" in clean_but_compare_behind.reason
    assert direct_merges == [
        ("owner/repo", 1, True),
        ("owner/repo", 1, True),
        ("owner/repo", 1, True),
        ("owner/repo", 1, True),
        ("owner/repo", 1, True),
    ]

    blocked_but_mergeable_and_compare_behind = inspect(
        make_pr(
            mergeStateStatus="BLOCKED",
            compareBehindBy=20,
            reviews={"nodes": [opencode_review("APPROVED", "head")]},
        ),
        merge_mode="direct_or_auto",
    )
    assert blocked_but_mergeable_and_compare_behind.action == "merge"
    assert "GitHub mergeability is BLOCKED" in blocked_but_mergeable_and_compare_behind.reason
    assert "direct merge requested" in blocked_but_mergeable_and_compare_behind.reason
    assert direct_merges == [
        ("owner/repo", 1, True),
        ("owner/repo", 1, True),
        ("owner/repo", 1, True),
        ("owner/repo", 1, True),
        ("owner/repo", 1, True),
        ("owner/repo", 1, True),
    ]

    auto_merges = []
    monkeypatch.setattr(sched, "enable_auto_merge", lambda repo, pr, dry_run: auto_merges.append((repo, pr["number"], dry_run)))
    assert inspect(approved).action == "auto_merge"
    assert auto_merges == [("owner/repo", 1, True)]
    blocked_direct_or_auto = inspect(
        make_pr(
            mergeStateStatus="BLOCKED",
            reviews={"nodes": [opencode_review("APPROVED", "head")]},
        ),
        merge_mode="direct_or_auto",
    )
    assert blocked_direct_or_auto.action == "merge"
    assert "GitHub mergeability is BLOCKED" in blocked_direct_or_auto.reason
    assert direct_merges == [
        ("owner/repo", 1, True),
        ("owner/repo", 1, True),
        ("owner/repo", 1, True),
        ("owner/repo", 1, True),
        ("owner/repo", 1, True),
        ("owner/repo", 1, True),
        ("owner/repo", 1, True),
    ]
    assert auto_merges == [("owner/repo", 1, True)]
    blocked_auto = inspect(blocked_approved, merge_mode="auto")
    assert blocked_auto.action == "auto_merge"
    assert auto_merges == [("owner/repo", 1, True), ("owner/repo", 1, True)]

    external_approved = inspect(
        make_pr(
            isCrossRepository=True,
            headRepository={"nameWithOwner": "fork/repo"},
            reviews={"nodes": [opencode_review("APPROVED", "head")]},
        ),
        merge_mode="direct_or_auto",
    )
    assert external_approved.action == "wait"
    assert "fork or external PR heads are excluded from scheduler direct merge and auto-merge" in external_approved.reason
    assert sched.decision_guidance(external_approved)["type"] == "external_head_merge_excluded"
    external_blocked = inspect(
        make_pr(
            mergeStateStatus="BLOCKED",
            isCrossRepository=True,
            headRepository={"nameWithOwner": "fork/repo"},
            reviews={"nodes": [opencode_review("APPROVED", "head")]},
        ),
        merge_mode="direct_or_auto",
    )
    assert external_blocked.action == "wait"
    assert "fork or external PR heads are excluded from scheduler direct merge and auto-merge" in external_blocked.reason

    running = make_pr(statusCheckRollup={"contexts": {"nodes": [opencode_check()]}})
    assert inspect(running).reason == "OpenCode review is already in progress"

    dispatched = []
    monkeypatch.setattr(sched, "dispatch_strix_evidence", lambda repo, workflow, pr, dry_run: dispatched.append(workflow))
    monkeypatch.setattr(sched, "dispatch_opencode_review", lambda repo, workflow, pr, dry_run: dispatched.append(workflow))
    assert inspect(make_pr()).action == "security_dispatch"
    assert dispatched == ["Strix Security Scan"]
    assert (
        inspect(make_pr(statusCheckRollup={"contexts": {"nodes": [strix_check(status="IN_PROGRESS", conclusion="")]}})).reason
        == "same-head Strix evidence is still running"
    )
    assert inspect(make_pr(statusCheckRollup={"contexts": {"nodes": [strix_check()]}})).action == "review_dispatch"
    assert dispatched == ["Strix Security Scan", "OpenCode Review"]
    stale_opencode = make_pr(
        statusCheckRollup={
            "contexts": {
                "nodes": [
                    opencode_check(started_at="2026-06-25T07:00:00Z"),
                    strix_check(),
                ]
            }
        }
    )
    stale_decision = inspect(stale_opencode, stale_opencode_minutes=0)
    assert stale_decision.action == "review_dispatch"
    assert "retry threshold" in stale_decision.reason
    assert dispatched == ["Strix Security Scan", "OpenCode Review", "OpenCode Review"]
    stale_limited = inspect(stale_opencode, stale_opencode_minutes=0, review_dispatch_allowed=False)
    assert stale_limited.action == "wait"
    assert "review dispatch limit reached" in stale_limited.reason
    stale_wait = inspect(stale_opencode, trigger_reviews=False, stale_opencode_minutes=0)
    assert stale_wait.action == "wait"
    assert "review dispatch disabled" in stale_wait.reason
    missing_limited = inspect(make_pr(), review_dispatch_allowed=False)
    assert missing_limited.action == "wait"
    assert (
        missing_limited.reason
        == "current head has no completed Strix evidence; review dispatch limit reached"
    )
    completed_strix_limited = inspect(
        make_pr(statusCheckRollup={"contexts": {"nodes": [strix_check()]}}),
        review_dispatch_allowed=False,
    )
    assert completed_strix_limited.action == "wait"
    assert completed_strix_limited.reason == "current head has completed Strix evidence; review dispatch limit reached"
    assert inspect(make_pr(), trigger_reviews=False).reason == "current head has no OpenCode approval"
    missing_approval_auto = inspect(make_pr(autoMergeRequest={"enabledAt": "now"}), trigger_reviews=False)
    assert missing_approval_auto.action == "disable_auto_merge"
    assert "no OpenCode approval" in missing_approval_auto.reason


def test_direct_or_auto_falls_back_to_auto_merge_when_branch_policy_blocks_direct_merge(monkeypatch):
    approved = make_pr(reviews={"nodes": [opencode_review("APPROVED", "head")]})
    auto_merges = []

    def policy_blocked_merge(repo, pr, dry_run):
        raise RuntimeError(
            "Command failed (1): gh pr merge 1 --repo owner/repo --squash --match-head-commit head\n"
            "X Pull request owner/repo#1 is not mergeable: the base branch policy prohibits the merge."
        )

    monkeypatch.setattr(sched, "merge_pr", policy_blocked_merge)
    monkeypatch.setattr(
        sched,
        "enable_auto_merge",
        lambda repo, pr, dry_run: auto_merges.append((repo, pr["number"], dry_run)),
    )

    decision = inspect(approved, merge_mode="direct_or_auto")

    assert decision.action == "auto_merge"
    assert "direct merge was blocked by branch policy" in decision.reason
    assert auto_merges == [("owner/repo", 1, True)]

    already_queued = inspect(
        make_pr(
            autoMergeRequest={"enabledAt": "now"},
            reviews={"nodes": [opencode_review("APPROVED", "head")]},
        ),
        merge_mode="direct_or_auto",
    )

    assert already_queued.action == "auto_merge"
    assert "existing auto-merge request remains queued" in already_queued.reason
    assert auto_merges == [("owner/repo", 1, True)]

    with pytest.raises(RuntimeError, match="base branch policy prohibits"):
        inspect(approved, merge_mode="direct")


def test_main_limits_review_dispatches_without_blocking_branch_updates(monkeypatch, capsys):
    prs = [
        make_pr(
            number=1,
            statusCheckRollup={"contexts": {"nodes": [strix_check()]}},
        ),
        make_pr(
            number=2,
            statusCheckRollup={"contexts": {"nodes": [strix_check()]}},
        ),
        make_pr(
            number=3,
            mergeStateStatus="BLOCKED",
            restMergeableState="BLOCKED",
            compareBehindBy=2,
            autoMergeRequest={"enabledAt": "now"},
        ),
    ]
    dispatched = []
    updated = []

    monkeypatch.setattr(sched, "fetch_open_prs", lambda repo, max_prs: prs)
    monkeypatch.setattr(
        sched,
        "dispatch_opencode_review",
        lambda repo, workflow, pr, dry_run: dispatched.append(pr["number"]),
    )
    monkeypatch.setattr(
        sched,
        "update_branch",
        lambda repo, pr, dry_run: updated.append(pr["number"]),
    )
    monkeypatch.setattr(sched, "wait_for_updated_branch_head", lambda repo, pr: None)

    assert (
        sched.main(
            [
                "--repo",
                "owner/repo",
                "--base-branch",
                "main",
                "--project-flow",
                "github-flow",
                "--review-dispatch-limit",
                "1",
            ]
        )
        == 0
    )

    output = capsys.readouterr().out
    payload = json.loads(output.strip().splitlines()[-1])
    assert dispatched == [1]
    assert updated == [3]
    assert payload["counts"] == {"review_dispatch": 1, "update_branch": 1, "wait": 1}
    assert (
        payload["decisions"][1]["reason"]
        == "current head has completed Strix evidence; review dispatch limit reached"
    )
    assert payload["decisions"][2]["contract_decision"] == "UPDATE_BRANCH"


def test_main_rejects_invalid_review_dispatch_limit():
    with pytest.raises(SystemExit, match="--review-dispatch-limit must be -1 or greater"):
        sched.main(
            [
                "--repo",
                "owner/repo",
                "--base-branch",
                "main",
                "--project-flow",
                "github-flow",
                "--review-dispatch-limit",
                "-2",
            ]
        )


def test_print_summary_self_test_parse_args_and_main(monkeypatch, capsys):
    sched.print_summary(
        [sched.Decision(1, "wait", "ready"), sched.Decision(2, "wait", "queued")],
        dry_run=True,
        base_branch="main",
        project_flow="github",
    )
    output = capsys.readouterr().out
    assert "PR #1: wait: ready" in output
    payload = json.loads(output.strip().splitlines()[-1])
    assert payload["schema_version"] == "pr-review-merge-scheduler/v2"
    assert payload["counts"] == {"wait": 2}
    assert [decision["contract_decision"] for decision in payload["decisions"]] == ["WAIT", "WAIT"]

    sched.self_test()
    assert "self-test passed" in capsys.readouterr().out

    real_split_repo = sched.split_repo
    invalid_inputs = ["owner", "/name", "owner/"]
    for accepted_invalid in invalid_inputs:
        def fake_split_repo(repo, accepted_invalid=accepted_invalid):
            if repo == accepted_invalid:
                return ("accepted", "invalid")
            return real_split_repo(repo)

        monkeypatch.setattr(sched, "split_repo", fake_split_repo)
        with pytest.raises(AssertionError, match="expected ValueError"):
            sched.self_test()
    monkeypatch.setattr(sched, "split_repo", real_split_repo)

    parsed = sched.parse_args(
        [
            "--repo",
            "owner/repo",
            "--base-branch",
            "main",
            "--project-flow",
            "github",
            "--no-trigger-reviews",
            "--stale-opencode-minutes",
            "5",
            "--pr-number",
            "12",
        ]
    )
    assert parsed.repo == "owner/repo"
    assert not parsed.trigger_reviews
    assert parsed.security_workflow == "Strix Security Scan"
    assert parsed.stale_opencode_minutes == 5
    assert parsed.pr_number == 12
    assert parsed.merge_mode == "direct_or_auto"

    assert sched.main(["--self-test"]) == 0
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    monkeypatch.delenv("DEFAULT_BRANCH", raising=False)
    monkeypatch.delenv("PROJECT_FLOW", raising=False)
    with pytest.raises(SystemExit):
        sched.main([])
    with pytest.raises(SystemExit):
        sched.main(["--repo", "owner/repo"])
    with pytest.raises(SystemExit):
        sched.main(["--repo", "owner/repo", "--base-branch", "main"])

    monkeypatch.setattr(sched, "fetch_open_prs", lambda repo, max_prs: [make_pr(number=3)])
    monkeypatch.setattr(sched, "inspect_pr", lambda *args, **kwargs: sched.Decision(3, "skip", "done"))
    assert sched.main(["--repo", "owner/repo", "--base-branch", "main", "--project-flow", "github"]) == 0

    exact_fetches = []
    monkeypatch.setattr(sched, "fetch_pr", lambda repo, number: exact_fetches.append((repo, number)) or [make_pr(number=number)])
    assert (
        sched.main(
            [
                "--repo",
                "owner/repo",
                "--base-branch",
                "main",
                "--project-flow",
                "github",
                "--pr-number",
                "7",
            ]
        )
        == 0
    )
    assert exact_fetches == [("owner/repo", 7)]
    with pytest.raises(SystemExit, match="--pr-number must not be negative"):
        sched.main(["--repo", "owner/repo", "--base-branch", "main", "--project-flow", "github", "--pr-number", "-1"])


def test_main_keeps_scanning_after_action_error(monkeypatch, capsys):
    assert sched.summarize_action_error(RuntimeError("")) == "scheduler action failed without stderr"

    prs = [make_pr(number=1), make_pr(number=2)]
    seen = []

    def fake_inspect(repo, pr, **kwargs):
        seen.append(pr["number"])
        if pr["number"] == 1:
            raise RuntimeError(
                "Command failed (1): gh pr merge 1\n"
                "GraphQL: Resource not accessible by integration (enablePullRequestAutoMerge)"
            )
        return sched.Decision(pr["number"], "wait", "next PR still inspected")

    monkeypatch.setattr(sched, "fetch_open_prs", lambda repo, max_prs: prs)
    monkeypatch.setattr(sched, "inspect_pr", fake_inspect)

    assert sched.main(["--repo", "owner/repo", "--base-branch", "main", "--project-flow", "github"]) == 0
    assert seen == [1, 2]
    output = capsys.readouterr().out
    assert "PR #1: action_error: Command failed (1): gh pr merge 1; GraphQL: Resource not accessible by integration" in output
    assert "scheduler GitHub token could not perform merge or auto-merge" in output
    assert "PR #2: wait: next PR still inspected" in output
    payload = json.loads(output.strip().splitlines()[-1])
    assert payload["counts"] == {"action_error": 1, "wait": 1}
    assert payload["decisions"][0]["contract_decision"] == "WAIT"
    assert payload["decisions"][1]["contract_decision"] == "WAIT"


def test_scrub_sensitive_data_and_run_error():
    assert sched.scrub_sensitive_data("Authorization: Bearer mytoken123") == "Authorization: Bearer ***"
    assert sched.scrub_sensitive_data("token mytoken123") == "token ***"
    assert sched.scrub_sensitive_data("ghp_1234567890abcdef") == "***"
    assert sched.scrub_sensitive_data("ghs_1234567890abcdef") == "***"
    assert sched.scrub_sensitive_data("gho_1234567890abcdef") == "***"
    assert sched.scrub_sensitive_data("ghp_1234567890abcdef1234") == "***"
    assert sched.scrub_sensitive_data("gho_1234567890abcdef1234567890extra") == "***"
    assert sched.scrub_sensitive_data("github_pat_11AAAAA_abcdefg1234567890") == "***"
    assert sched.scrub_sensitive_data("ghp_placeholder_token_with_underscores_123") == "***"
    assert sched.scrub_sensitive_data("gho_installation_token_value") == "***"
    assert sched.scrub_sensitive_data("ghu_user_token_value") == "***"
    assert sched.scrub_sensitive_data("ghs_server_token_value") == "***"
    assert sched.scrub_sensitive_data("ghr_runner_token_value") == "***"
    assert sched.scrub_sensitive_data("github_pat_11AAAAA_abcdefg") == "***"
    assert sched.scrub_sensitive_data("sk-1234567890abcdef") == "***"
    assert sched.scrub_sensitive_data("xoxb-1234567890-1234") == "***"
    assert sched.scrub_sensitive_data("AKIA1234567890ABCDEF") == "***"
    assert sched.scrub_sensitive_data("password=mysecret") == "password=***"
    assert sched.scrub_sensitive_data("api_key : 'mysecret'") == "api_key : ***"
    assert sched.scrub_sensitive_data("No secrets here") == "No secrets here"
    assert sched.scrub_sensitive_data("") == ""
    assert sched.scrub_sensitive_data(None) is None

    with pytest.raises(RuntimeError, match=r"Command failed \([12]\): .* \*\*\*"):
        sched.run([sys.executable, "-c", "import sys; sys.exit(1)", "ghp_1234567890abcdef1234"], stdin=None)


def test_main_keeps_scanning_after_update_branch_403_and_422(monkeypatch, capsys):
    prs = [make_pr(number=1), make_pr(number=2), make_pr(number=3)]
    seen = []

    def fake_inspect(repo, pr, **kwargs):
        seen.append(pr["number"])
        if pr["number"] == 1:
            raise RuntimeError(
                "Command failed (1): gh api -X PUT repos/owner/repo/pulls/1/update-branch\n"
                "HTTP 403: Resource not accessible by integration"
            )
        if pr["number"] == 2:
            raise RuntimeError(
                "Command failed (1): gh api -X PUT repos/owner/repo/pulls/2/update-branch\n"
                "HTTP 422: expected_head_sha does not match current head"
            )
        return sched.Decision(pr["number"], "wait", "next PR still inspected")

    monkeypatch.setattr(sched, "fetch_open_prs", lambda repo, max_prs: prs)
    monkeypatch.setattr(sched, "inspect_pr", fake_inspect)

    assert sched.main(["--repo", "owner/repo", "--base-branch", "main", "--project-flow", "github"]) == 0
    assert seen == [1, 2, 3]
    output = capsys.readouterr().out
    assert "PR #1: action_error:" in output
    assert "pull-requests: write" in output
    assert "do not widen `contents` just for update-branch" in output
    assert "PR #2: action_error:" in output
    assert "PR head likely changed after inspection" in output
    assert "PR #3: wait: next PR still inspected" in output
    payload = json.loads(output.strip().splitlines()[-1])
    assert payload["counts"] == {"action_error": 2, "wait": 1}
    assert [decision["contract_decision"] for decision in payload["decisions"]] == ["WAIT", "WAIT", "WAIT"]


def test_action_error_guidance_distinguishes_update_branch_from_merge():
    update_error = sched.summarize_action_error(
        RuntimeError(
            "Command failed (1): gh api -X PUT repos/owner/repo/pulls/7/update-branch\n"
            "HTTP 403: Resource not accessible by integration"
        )
    )
    assert "pull-requests: write" in update_error
    assert "do not widen `contents` just for update-branch" in update_error

    merge_error = sched.summarize_action_error(
        RuntimeError(
            "Command failed (1): gh pr merge 7 --auto --squash\n"
            "GraphQL: Resource not accessible by integration (mergePullRequest)"
        )
    )
    assert "explicit repo policy exception" in merge_error
    assert "contents: write" in merge_error

    workflow_permission_error = sched.summarize_action_error(
        RuntimeError(
            "Command failed (1): gh pr merge 7 --auto --squash\n"
            "GraphQL: Pull request refusing to allow a GitHub App to create or update workflow `.github/workflows/opencode-review.yml` without `workflows` permission (enablePullRequestAutoMerge)"
        )
    )
    assert "workflow-file PRs need a scheduler mutation credential" in workflow_permission_error
    assert "PR_REVIEW_MERGE_TOKEN" in workflow_permission_error
    assert "do not leave this as a review comment" in workflow_permission_error

    unknown_mutation_error = sched.summarize_action_error(
        RuntimeError(
            "Command failed (1): gh api graphql -f mutation=unknown\n"
            "GraphQL: Resource not accessible by integration (unknownMutation)"
        )
    )
    assert "lacks a required repository mutation permission" in unknown_mutation_error
    assert "instead of posting a code-review finding" in unknown_mutation_error

    stale_head_error = sched.summarize_action_error(
        RuntimeError(
            "Command failed (1): gh api -X PUT repos/owner/repo/pulls/7/update-branch\n"
            "HTTP 422: expected_head_sha does not match current head"
        )
    )
    assert "PR head likely changed after inspection" in stale_head_error
    assert "reads the new head before mutating" in stale_head_error

def test_parse_conflict_reason_success():
    """Test parse_conflict_reason with valid complete conflict strings."""
    assert sched.parse_conflict_reason("merge conflict: DIRTY; base=main,head=feature-branch") == ("DIRTY", "main", "feature-branch")
    assert sched.parse_conflict_reason("Some prior text. merge conflict: BEHIND; base=develop,head=feat/123") == ("BEHIND", "develop", "feat/123")
    assert sched.parse_conflict_reason("merge conflict: DIRTY; foo=bar; base=master,head=bugfix; other=stuff") == ("DIRTY", "master", "bugfix")

def test_parse_conflict_reason_no_prefix():
    """Test parse_conflict_reason returns None when prefix is missing."""
    assert sched.parse_conflict_reason("no conflict here") is None
    assert sched.parse_conflict_reason("merge  conflict: space issue") is None

def test_parse_conflict_reason_empty_state():
    """Test parse_conflict_reason defaults state to UNKNOWN if missing or empty."""
    assert sched.parse_conflict_reason("merge conflict: ; base=main,head=feature") == ("UNKNOWN", "main", "feature")
    assert sched.parse_conflict_reason("merge conflict: ") == ("UNKNOWN", "base", "head")

def test_parse_conflict_reason_missing_branches():
    """Test parse_conflict_reason uses defaults when branch info is missing or malformed."""
    assert sched.parse_conflict_reason("merge conflict: DIRTY; some other segment") == ("DIRTY", "base", "head")
    assert sched.parse_conflict_reason("merge conflict: DIRTY; base=,head=something") == ("DIRTY", "base", "something")
    assert sched.parse_conflict_reason("merge conflict: DIRTY; base=main,head=") == ("DIRTY", "main", "head")


def test_run_masks_secrets():
    with pytest.raises(RuntimeError) as exc_info:
        sched.run(
            [
                sys.executable,
                "-c",
                (
                    "import sys; "
                    "sys.stderr.write('ghp_abcdef1234567890abcdef1234567890abcdef\\n"
                    "Bearer super_secret\\ntoken my_secret\\n'); "
                    "sys.exit(1)"
                ),
            ]
        )

    err_msg = str(exc_info.value)
    assert "ghp_abcdef1234567890abcdef1234567890abcdef" not in err_msg
    assert "***" in err_msg
    assert "Bearer super_secret" not in err_msg
    assert "Bearer ***" in err_msg
    assert "token my_secret" not in err_msg
    assert "token ***" in err_msg


def test_run_masks_secrets_in_args():
    with pytest.raises(RuntimeError) as exc_info:
        sched.run(
            [
                sys.executable,
                "-c",
                "import sys; sys.exit(1)",
                "ghp_abcdef1234567890abcdef1234567890abcdef",
            ]
        )

    err_msg = str(exc_info.value)
    assert "ghp_abcdef1234567890abcdef1234567890abcdef" not in err_msg
    assert "***" in err_msg
