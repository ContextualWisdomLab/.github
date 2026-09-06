"""Mock-only Strix rerun identity contracts through the real scheduler caller."""

import json

import pytest

from scripts.ci import pr_review_merge_scheduler as sched


@pytest.mark.parametrize("case,allowed", [
    ("current-associated-head-top-level-base", True),
    ("current-associated-head-top-level-head", True),
    ("stale-associated-head", False),
    ("stale-association-top-level-current", False),
    ("contradictory-title", False),
    ("missing-association", False),
    ("foreign-details-repository", False),
    ("different-workflow-path", False),
    ("untrusted-check-publisher", False),
    ("unrelated-push-event", False),
    ("dispatch-without-target-receipt", False),
    ("api-unavailable", False),
    ("wrong-job-run", False),
    ("wrong-check-suite", False),
    ("contradictory-repository", False),
    ("missing-check-id", False),
    ("current-head-moves-during-binding", False),
    ("repository-api-url-only", True),
])
def test_actual_strix_rerun_caller_binds_selected_job(monkeypatch, case, allowed):
    """Selected job/run provenance, not a current PR snapshot alone, authorizes rerun."""
    repo = "owner/repo"
    current_head, stale_head, base_sha = "b" * 40, "a" * 40, "c" * 40
    job_id, run_id, suite_id, workflow_id = 202, 101, 303, 404
    associated_head = stale_head if case.startswith("stale-") else current_head
    title_head = stale_head if case in {"stale-associated-head", "contradictory-title"} else current_head
    execution_sha = current_head if case in {
        "current-associated-head-top-level-head", "stale-association-top-level-current"
    } else base_sha
    details_repo = "other/repo" if case == "foreign-details-repository" else repo
    publisher = "third-party-app" if case == "untrusted-check-publisher" else "github-actions"
    actual_check_id = 606 if publisher != "github-actions" else 505
    check = {
        "id": 505, "name": "strix", "status": "completed", "conclusion": "failure",
        "head_sha": current_head,
        "details_url": f"https://github.com/{details_repo}/actions/runs/{run_id}/job/{job_id}",
        "app": {"slug": publisher}, "check_suite": {"id": suite_id},
    }
    node = sched.rest_check_node(
        check, {}, {} if publisher != "github-actions" else {suite_id: "Strix Security Scan"}
    )
    if case == "missing-check-id":
        node.pop("databaseId")
    pr = {
        "number": 7, "state": "OPEN", "headRefOid": current_head,
        "baseRefOid": base_sha, "headRefName": "feature", "baseRefName": "main",
        "headRepository": {"nameWithOwner": repo},
        "statusCheckRollup": {"contexts": {"nodes": [node]}},
    }
    job = {
        "id": job_id, "run_id": run_id, "head_sha": execution_sha,
        "name": "strix", "status": "completed", "conclusion": "failure",
        "check_run_url": f"https://api.github.com/repos/{repo}/check-runs/{actual_check_id}",
        "html_url": f"https://github.com/{repo}/actions/runs/{run_id}/job/{job_id}",
    }
    run = {
        "id": run_id, "head_sha": execution_sha, "workflow_id": workflow_id,
        "check_suite_id": suite_id, "repository": {"full_name": repo},
        "event": "push" if case == "unrelated-push-event" else "pull_request_target",
        "path": ".github/workflows/other.yml" if case == "different-workflow-path" else ".github/workflows/strix.yml",
        "name": "Strix Security Scan", "status": "completed", "conclusion": "failure",
        "display_title": f"Strix Security Scan {repo}#7@{title_head}",
        "pull_requests": [] if case == "missing-association" else [{
            "number": 7, "base": {"sha": base_sha, "repo": {"name": "repo", "full_name": repo}},
            "head": {"sha": associated_head, "repo": {"name": "repo", "full_name": repo}},
        }],
    }
    if case == "dispatch-without-target-receipt":
        run["event"] = "repository_dispatch"
        run["pull_requests"] = []
    if case == "wrong-job-run":
        job["run_id"] = 999
    if case == "wrong-check-suite":
        run["check_suite_id"] = 999
    if case == "contradictory-repository":
        run["pull_requests"][0]["head"]["repo"]["url"] = "https://api.github.com/repos/other/repo"
    if case == "repository-api-url-only":
        for side in ("base", "head"):
            run["pull_requests"][0][side]["repo"] = {"name": "repo", "url": f"https://api.github.com/repos/{repo}"}
    reads, posts = [], []
    responses = {
        f"repos/{repo}/actions/jobs/{job_id}": job,
        f"repos/{repo}/actions/runs/{run_id}": run,
        f"repos/{repo}/check-runs/505": check,
        f"repos/{repo}/actions/workflows/{workflow_id}": {
            "id": workflow_id, "path": run["path"], "name": "Strix Security Scan",
        },
    }
    if actual_check_id != 505:
        responses[f"repos/{repo}/check-runs/{actual_check_id}"] = {
            **check, "id": actual_check_id, "app": {"slug": "github-actions"},
        }

    def read(endpoint):
        reads.append(endpoint)
        if case == "api-unavailable":
            raise RuntimeError("metadata unavailable")
        assert endpoint in responses, f"Unexpected metadata lookup: {endpoint}"
        return responses[endpoint]

    def actions(args, *, stdin=None):
        assert stdin is None
        if args == ["gh", "api", "-X", "POST", f"repos/{repo}/actions/jobs/{job_id}/rerun"]:
            posts.append(args)
            return ""
        assert args[:2] == ["gh", "api"] and len(args) == 3
        return json.dumps(read(args[2]))

    def no_external_call(*args, **kwargs):
        pytest.fail("Unexpected unmocked command boundary")

    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("SCHEDULER_ACTIONS_TOKEN", "fixture-token")
    monkeypatch.setattr(sched, "run", no_external_call)
    monkeypatch.setattr(sched, "run_with_env", no_external_call)
    monkeypatch.setattr(sched, "gh_api_json", read)
    monkeypatch.setattr(sched, "run_github_read", actions)
    monkeypatch.setattr(sched, "run_github_actions", actions)
    monkeypatch.setattr(sched, "review_dispatch_admitted", lambda *_: True)
    def fetch_pr(*_):
        if case == "current-head-moves-during-binding" and reads:
            return [{**pr, "headRefOid": "d" * 40}]
        return [pr]

    monkeypatch.setattr(sched, "fetch_pr", fetch_pr)
    # Keep real selection, live guard, caller, control-actor check and rerun wrapper.
    result = sched.dispatch_strix_evidence(repo, "Strix Security Scan", pr, dry_run=False)
    if allowed:
        assert result == "rerun"
        assert len(posts) == 1
        assert len(reads) == 4
    else:
        assert posts == [], f"Unsafe rerun reached POST without binding metadata; reads={reads}; run={run}"
        assert result in {"identity_unverified", "stale_head"}
