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


def strix_check(status="COMPLETED", conclusion="SUCCESS", workflow="Strix Security Scan"):
    return {
        "__typename": "CheckRun",
        "name": "strix",
        "status": status,
        "conclusion": conclusion,
        "checkSuite": {"workflowRun": {"workflow": {"name": workflow}}},
    }


def opencode_check(status="IN_PROGRESS", started_at=None):
    return {
        "__typename": "CheckRun",
        "name": "opencode-review",
        "status": status,
        "startedAt": started_at,
        "checkSuite": {"workflowRun": {"workflow": {"name": "OpenCode Review"}}},
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
    with pytest.raises(TypeError):
        sched.run("echo unsafe")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        sched.run(["echo", 1])  # type: ignore[list-item]

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


def test_rest_mergeable_state_helpers(monkeypatch):
    calls = []

    def fake_run(args, stdin=None):
        calls.append(args)
        return "dirty\n"

    monkeypatch.setattr(sched, "run", fake_run)

    assert sched.fetch_rest_mergeable_state("owner/repo", 7) == "DIRTY"
    assert calls == [["gh", "api", "repos/owner/repo/pulls/7", "--jq", ".mergeable_state // \"\""]]

    prs = [{"number": 8}]
    monkeypatch.setattr(sched, "fetch_rest_mergeable_state", lambda repo, number: f"{repo}:{number}")
    sched.enrich_rest_mergeable_states("owner/repo", prs)
    assert prs == [{"number": 8, "restMergeableState": "owner/repo:8"}]

    def raise_lookup_error(repo, number):
        raise RuntimeError("transient REST failure")

    prs = [{"number": 9}]
    monkeypatch.setattr(sched, "fetch_rest_mergeable_state", raise_lookup_error)
    sched.enrich_rest_mergeable_states("owner/repo", prs)
    assert prs == [{"number": 9, "restMergeableStateError": "transient REST failure"}]


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

    threaded = make_pr(reviewThreads={"nodes": [{"isResolved": False}, {"isResolved": True}, {"isOutdated": True}]})
    assert sched.unresolved_thread_count(threaded) == 1
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


def test_actions_call_gh_with_expected_arguments(monkeypatch):
    calls = []
    monkeypatch.setattr(sched, "run", lambda args: calls.append(args) or "")
    pr = make_pr()
    sched.enable_auto_merge("owner/repo", pr, dry_run=True)
    sched.disable_auto_merge("owner/repo", pr, dry_run=True)
    sched.update_branch("owner/repo", pr, dry_run=True)
    sched.dispatch_strix_evidence("owner/repo", "Strix Security Scan", pr, dry_run=True)
    sched.dispatch_opencode_review("owner/repo", "OpenCode Review", pr, dry_run=True)
    assert calls == []

    sched.enable_auto_merge("owner/repo", pr, dry_run=False)
    sched.disable_auto_merge("owner/repo", pr, dry_run=False)
    sched.update_branch("owner/repo", pr, dry_run=False)
    sched.dispatch_strix_evidence("owner/repo", "Strix Security Scan", pr, dry_run=False)
    sched.dispatch_opencode_review("owner/repo", "OpenCode Review", pr, dry_run=False)
    assert calls[0][:4] == ["gh", "pr", "merge", "1"]
    assert calls[1] == ["gh", "pr", "merge", "1", "--repo", "owner/repo", "--disable-auto"]
    assert calls[2][:4] == ["gh", "api", "-X", "PUT"]
    assert calls[2][-1] == "expected_head_sha=head"
    assert calls[3][:5] == ["gh", "workflow", "run", "Strix Security Scan", "--repo"]
    assert calls[4][:5] == ["gh", "workflow", "run", "OpenCode Review", "--repo"]


def test_print_summary_writes_github_step_summary(monkeypatch, tmp_path, capsys):
    summary_path = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_path))
    conflict_reason = sched.merge_conflict_guidance(
        make_pr(number=7, headRefName="feature|x"),
        "DIRTY",
    )
    decisions = [
        sched.Decision(7, "block", conflict_reason),
        sched.Decision(
            8,
            "update_branch",
            "current-head OpenCode review approved; branch update requested with workflow GH_TOKEN (github-actions[bot] in GitHub Actions)",
        ),
        sched.Decision(
            9,
            "disable_auto_merge",
            "auto-merge disabled; OpenCode review does not postdate the current head commit; wait for a fresh same-head OpenCode review",
        ),
    ]

    sched.print_summary(decisions, dry_run=True, base_branch="main", project_flow="github-flow")

    output = capsys.readouterr().out
    assert "PR #7: block: merge conflict: DIRTY" in output
    payload = json.loads(output.splitlines()[-1])
    assert payload["schema_version"] == "pr-review-merge-scheduler/v2"
    assert payload["base_branch"] == "main"
    assert payload["counts"] == {"block": 1, "disable_auto_merge": 1, "update_branch": 1}
    assert payload["dry_run"] is True
    assert payload["inspected"] == 3
    assert payload["project_flow"] == "github-flow"
    assert payload["decisions"][0]["contract_decision"] == "WAIT"
    assert payload["decisions"][1]["contract_decision"] == "UPDATE_BRANCH"
    assert payload["decisions"][2]["contract_decision"] == "WAIT"
    assert payload["decisions"][0]["guidance"]["type"] == "merge_conflict_repair"
    assert payload["decisions"][0]["guidance"]["merge_state"] == "DIRTY"
    assert payload["decisions"][0]["guidance"]["base_ref"] == "main"
    assert payload["decisions"][0]["guidance"]["head_ref"] == "feature|x"
    assert "update-branch cannot choose" in payload["decisions"][0]["guidance"]["automation_limit"]
    assert "gh pr checkout 7" in payload["decisions"][0]["guidance"]["commands"]
    assert "git merge --no-ff origin/main" in payload["decisions"][0]["guidance"]["commands"]
    assert payload["decisions"][1]["guidance"]["type"] == "github_actions_update_branch"
    assert payload["decisions"][1]["guidance"]["actor"] == "github-actions[bot]"
    assert payload["decisions"][1]["guidance"]["token"] == "workflow GITHUB_TOKEN"
    assert payload["decisions"][1]["guidance"]["required_permission"] == "pull-requests: write"
    assert payload["decisions"][1]["guidance"]["head_guard"] == "expected_head_sha"
    assert payload["decisions"][2]["guidance"]["type"] == "unsafe_auto_merge_disabled"
    summary = summary_path.read_text(encoding="utf-8")
    assert "## PR review merge scheduler" in summary
    assert "| #7 | block | merge conflict: DIRTY; base=main, head=feature\\|x; run" in summary
    assert "do not retry update-branch until the conflict is repaired" in summary
    assert (
        "| #8 | update_branch | current-head OpenCode review approved; "
        "branch update requested with workflow GH_TOKEN (github-actions[bot] in GitHub Actions) |"
    ) in summary
    assert "fresh same-head OpenCode review" in summary
    assert "### Conflict repair" in summary
    assert "`update-branch` is not a conflict resolver" in summary
    assert "PR #7 is `DIRTY` against `main` from `feature\\|x`:" not in summary
    assert "PR #7 is `DIRTY` against `main` from `feature|x`:" in summary
    assert "gh pr checkout 7" in summary
    assert "git fetch origin main" in summary
    assert "git merge --no-ff origin/main" in summary
    assert "git push --force-with-lease" in summary
    assert "### Branch update requests" in summary
    assert "Requested `update-branch` for PR #8 with the workflow `GITHUB_TOKEN`" in summary
    assert "not from a maintainer's local `gh` credential" in summary
    assert "needs `pull-requests: write`" in summary
    assert "does not require the scheduler job to widen repository `contents` to write" in summary
    assert "github-actions[bot]" in summary


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
    assert sched.action_error_summary(wait_decisions) == []

    lines = sched.action_error_summary([sched.Decision(2, "action_error", "permission failed")])
    assert "### Action errors" in lines
    assert "not source-code review findings" in "\n".join(lines)
    assert "- PR #2: permission failed" in lines


def test_inspect_pr_blocks_and_waits_for_policy_states(monkeypatch):
    assert inspect(make_pr(isDraft=True)).action == "skip"
    assert inspect(make_pr(baseRefName="develop")).reason == "base branch is develop; expected main"
    assert inspect(make_pr(headRepository={"nameWithOwner": "fork/repo"})).action == "skip"
    conflict = inspect(make_pr(mergeStateStatus="DIRTY"))
    assert conflict.action == "block"
    assert "merge conflict: DIRTY" in conflict.reason
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
    assert unknown_mergeability.reason == "mergeability is still being calculated"
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
    decision = inspect(behind)
    assert decision.action == "update_branch"
    assert "workflow GH_TOKEN" in decision.reason
    assert "github-actions[bot]" in decision.reason
    assert called == [("owner/repo", 1, True)]
    called.clear()
    behind_failed = make_pr(
        mergeStateStatus="BEHIND",
        reviews={"nodes": [opencode_review("APPROVED", "head")]},
        statusCheckRollup={"contexts": {"nodes": [{"__typename": "CheckRun", "name": "strix", "conclusion": "FAILURE"}]}},
    )
    failed_decision = inspect(behind_failed)
    assert failed_decision.action == "block"
    assert failed_decision.reason == "failed check(s): strix"
    assert called == []
    behind_auto_merge_enabled = make_pr(
        mergeStateStatus="BEHIND",
        reviews={"nodes": [opencode_review("APPROVED", "head")]},
        autoMergeRequest={"enabledAt": "now"},
    )
    assert inspect(behind_auto_merge_enabled).action == "update_branch"
    assert called == [("owner/repo", 1, True)]
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
    stale_wait = inspect(stale_opencode, trigger_reviews=False, stale_opencode_minutes=0)
    assert stale_wait.action == "wait"
    assert "review dispatch disabled" in stale_wait.reason
    assert inspect(make_pr(), trigger_reviews=False).reason == "current head has no OpenCode approval"
    missing_approval_auto = inspect(make_pr(autoMergeRequest={"enabledAt": "now"}), trigger_reviews=False)
    assert missing_approval_auto.action == "disable_auto_merge"
    assert "no OpenCode approval" in missing_approval_auto.reason


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
        ]
    )
    assert parsed.repo == "owner/repo"
    assert not parsed.trigger_reviews
    assert parsed.security_workflow == "Strix Security Scan"
    assert parsed.stale_opencode_minutes == 5

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
    assert sched.scrub_sensitive_data("github_pat_11AAAAA_abcdefg") == "***"
    assert sched.scrub_sensitive_data("No secrets here") == "No secrets here"
    assert sched.scrub_sensitive_data("") == ""
    assert sched.scrub_sensitive_data(None) is None

    with pytest.raises(RuntimeError, match=r"Command failed \([12]\): .* \*\*\*"):
        sched.run([sys.executable, "-c", "import sys; sys.exit(1)", "ghp_secret"], stdin=None)


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
            "Command failed (1): gh pr merge 7 --auto --merge\n"
            "GraphQL: Resource not accessible by integration (mergePullRequest)"
        )
    )
    assert "explicit repo policy exception" in merge_error
    assert "contents: write" in merge_error

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
