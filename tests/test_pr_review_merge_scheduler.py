import json
import sys

import pytest

from scripts.ci import pr_review_merge_scheduler as sched


def make_pr(**overrides):
    value = {
        "number": 1,
        "title": "Central review",
        "isDraft": False,
        "mergeable": "MERGEABLE",
        "mergeStateStatus": "CLEAN",
        "reviewDecision": "REVIEW_REQUIRED",
        "baseRefName": "main",
        "baseRefOid": "base",
        "headRefName": "feature",
        "headRefOid": "head",
        "headRepository": {"nameWithOwner": "owner/repo"},
        "autoMergeRequest": None,
        "reviewThreads": {"nodes": []},
        "reviews": {"nodes": []},
        "statusCheckRollup": {"contexts": {"nodes": []}},
    }
    value.update(overrides)
    return value


def opencode_review(state="APPROVED", commit="head", login="opencode-agent"):
    return {"state": state, "author": {"login": login}, "commit": {"oid": commit}}


def strix_check(status="COMPLETED", conclusion="SUCCESS", workflow="Strix Security Scan"):
    return {
        "__typename": "CheckRun",
        "name": "strix",
        "status": status,
        "conclusion": conclusion,
        "checkSuite": {"workflowRun": {"workflow": {"name": workflow}}},
    }


def inspect(pr, **overrides):
    kwargs = {
        "dry_run": True,
        "trigger_reviews": True,
        "enable_auto_merge_flag": True,
        "update_branches": True,
        "workflow": "OpenCode Review",
        "security_workflow": "Strix Security Scan",
        "base_branch": "main",
    }
    kwargs.update(overrides)
    return sched.inspect_pr("owner/repo", pr, **kwargs)


def test_run_split_repo_and_graphql(monkeypatch):
    assert sched.run([sys.executable, "-c", "print('ok')"]).strip() == "ok"
    with pytest.raises(RuntimeError):
        sched.run([sys.executable, "-c", "import sys; sys.exit(7)"])

    assert sched.split_repo("owner/repo") == ("owner", "repo")
    with pytest.raises(ValueError):
        sched.split_repo("bad")
    with pytest.raises(ValueError):
        sched.split_repo("/repo")

    calls = []

    def fake_run(args, stdin=None):
        calls.append((args, stdin))
        return '{"ok": true}'

    monkeypatch.setattr(sched, "run", fake_run)
    assert sched.gh_graphql("query", pageSize=2, cursor="abc") == {"ok": True}
    assert "-F" in calls[0][0]
    assert "-f" in calls[0][0]
    assert calls[0][1] == "query"


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
    assert sched.fetch_open_prs("owner/repo", 3) == [{"number": 1}, {"number": 2}]
    assert seen[0]["pageSize"] == 3
    assert seen[1]["cursor"] == "cursor"


def test_context_review_and_check_helpers():
    assert sched.context_nodes({}) == []
    assert sched.context_nodes(make_pr()) == []
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

    running = make_pr(
        statusCheckRollup={"contexts": {"nodes": [{"__typename": "CheckRun", "name": "opencode-review", "status": "IN_PROGRESS"}]}}
    )
    assert sched.opencode_in_progress(running)
    complete = make_pr(
        statusCheckRollup={"contexts": {"nodes": [{"context": "opencode-review", "state": "SUCCESS"}]}}
    )
    assert not sched.opencode_in_progress(complete)
    unrelated = make_pr(statusCheckRollup={"contexts": {"nodes": [{"context": "strix", "state": "PENDING"}]}})
    assert not sched.opencode_in_progress(unrelated)
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

    threaded = make_pr(reviewThreads={"nodes": [{"isResolved": False}, {"isResolved": True}, {"isOutdated": True}]})
    assert sched.unresolved_thread_count(threaded) == 1
    assert sched.review_author_login({}) == ""
    assert sched.review_author_login({"author": {"login": "OpenCode-Agent"}}) == "opencode-agent"
    assert sched.is_opencode_review(opencode_review())
    assert not sched.is_opencode_review(opencode_review(login="human"))


def test_review_state_and_failed_checks():
    pr = make_pr(reviews={"nodes": [opencode_review("APPROVED", "old"), opencode_review("APPROVED", "head")]})
    assert sched.current_head_review_state(pr, "APPROVED")
    assert sched.latest_opencode_review(pr)["commit"]["oid"] == "head"
    assert sched.latest_opencode_approved(pr)
    assert sched.has_current_head_approval(pr)
    assert not sched.has_current_head_changes_requested(pr)
    assert sched.latest_opencode_review(make_pr()) is None
    assert not sched.latest_opencode_approved(make_pr())
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


def test_actions_call_gh_with_expected_arguments(monkeypatch):
    calls = []
    monkeypatch.setattr(sched, "run", lambda args: calls.append(args) or "")
    pr = make_pr()
    sched.enable_auto_merge("owner/repo", pr, dry_run=True)
    sched.update_branch("owner/repo", pr, dry_run=True)
    sched.dispatch_strix_evidence("owner/repo", "Strix Security Scan", pr, dry_run=True)
    sched.dispatch_opencode_review("owner/repo", "OpenCode Review", pr, dry_run=True)
    assert calls == []

    sched.enable_auto_merge("owner/repo", pr, dry_run=False)
    sched.update_branch("owner/repo", pr, dry_run=False)
    sched.dispatch_strix_evidence("owner/repo", "Strix Security Scan", pr, dry_run=False)
    sched.dispatch_opencode_review("owner/repo", "OpenCode Review", pr, dry_run=False)
    assert calls[0][:4] == ["gh", "pr", "merge", "1"]
    assert calls[1][:4] == ["gh", "api", "-X", "PUT"]
    assert calls[2][:5] == ["gh", "workflow", "run", "Strix Security Scan", "--repo"]
    assert calls[3][:5] == ["gh", "workflow", "run", "OpenCode Review", "--repo"]


def test_inspect_pr_blocks_and_waits_for_policy_states(monkeypatch):
    assert inspect(make_pr(isDraft=True)).action == "skip"
    assert inspect(make_pr(baseRefName="develop")).reason == "base branch is develop; expected main"
    assert inspect(make_pr(headRepository={"nameWithOwner": "fork/repo"})).action == "skip"
    assert inspect(make_pr(mergeStateStatus="DIRTY")).reason == "merge conflict: DIRTY"
    assert inspect(make_pr(reviewThreads={"nodes": [{"isResolved": False}]})).reason == "1 unresolved review thread(s)"
    assert inspect(make_pr(reviews={"nodes": [opencode_review("CHANGES_REQUESTED", "head")]})).reason == (
        "current-head OpenCode review requested changes"
    )

    stale_behind = make_pr(mergeStateStatus="BEHIND", reviews={"nodes": [opencode_review("APPROVED", "old")]})
    dispatched = []
    monkeypatch.setattr(sched, "dispatch_strix_evidence", lambda repo, workflow, pr, dry_run: dispatched.append(workflow))
    monkeypatch.setattr(sched, "dispatch_opencode_review", lambda repo, workflow, pr, dry_run: dispatched.append(workflow))
    assert inspect(stale_behind).action == "security_dispatch"
    assert dispatched == ["Strix Security Scan"]

    behind = make_pr(mergeStateStatus="BEHIND", reviews={"nodes": [opencode_review("APPROVED", "head")]})
    assert inspect(behind, update_branches=False).reason == "current-head OpenCode review approved; branch update disabled"
    called = []
    monkeypatch.setattr(sched, "update_branch", lambda repo, pr, dry_run: called.append((repo, pr["number"], dry_run)))
    assert inspect(behind).action == "update_branch"
    assert called == [("owner/repo", 1, True)]


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
    assert inspect(approved, enable_auto_merge_flag=False).reason == (
        "current head is approved; auto-merge disabled by scheduler inputs"
    )

    merged = []
    monkeypatch.setattr(sched, "enable_auto_merge", lambda repo, pr, dry_run: merged.append((repo, pr["number"], dry_run)))
    assert inspect(approved).action == "auto_merge"
    assert merged == [("owner/repo", 1, True)]

    running = make_pr(
        statusCheckRollup={"contexts": {"nodes": [{"__typename": "CheckRun", "name": "opencode-review", "status": "IN_PROGRESS"}]}}
    )
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
    assert inspect(make_pr(), trigger_reviews=False).reason == "current head has no OpenCode approval"


def test_print_summary_self_test_parse_args_and_main(monkeypatch, capsys):
    sched.print_summary(
        [sched.Decision(1, "wait", "ready"), sched.Decision(2, "wait", "queued")],
        dry_run=True,
        base_branch="main",
        project_flow="github",
    )
    output = capsys.readouterr().out
    assert "PR #1: wait: ready" in output
    assert json.loads(output.strip().splitlines()[-1])["counts"] == {"wait": 2}

    sched.self_test()
    assert "self-test passed" in capsys.readouterr().out

    parsed = sched.parse_args(["--repo", "owner/repo", "--base-branch", "main", "--project-flow", "github", "--no-trigger-reviews"])
    assert parsed.repo == "owner/repo"
    assert not parsed.trigger_reviews
    assert parsed.security_workflow == "Strix Security Scan"

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
