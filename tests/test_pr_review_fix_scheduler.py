import json
import runpy
import subprocess
import sys
import time

import pytest

from scripts.ci import pr_review_autofix_context as context
from scripts.ci import pr_review_fix_scheduler as fix


def make_pr(**overrides):
    value = {
        "number": 7,
        "isDraft": False,
        "baseRefName": "main",
        "baseRefOid": "b" * 40,
        "headRefName": "feature",
        "headRefOid": "a" * 40,
        "headRepository": {"nameWithOwner": "owner/repo"},
        "mergeStateStatus": "CLEAN",
        "reviews": {"nodes": []},
        "reviewThreads": {"nodes": []},
    }
    value.update(overrides)
    return value


def test_recent_fix_marker_is_head_scoped():
    """Fix markers are scoped to the exact PR head."""
    head = "a" * 40
    comments = [{"body": f"{fix.FIX_MARKER} head_sha={head} epoch={int(time.time())} -->"}]

    assert fix.recent_fix_marker_exists(comments, head, 24 * 3600)
    assert not fix.recent_fix_marker_exists(comments, "b" * 40, 24 * 3600)
    assert not fix.recent_fix_marker_exists([{"body": f"{fix.FIX_MARKER} head_sha={head} epoch=oops -->"}], head, 24 * 3600)


def test_needs_autofix_uses_current_head_evidence():
    """Autofix starts from current-head OpenCode change requests."""
    head = "a" * 40
    pr = make_pr(
        headRefOid=head,
        reviews={
            "nodes": [
                {"state": "APPROVED", "author": {"login": "opencode-agent"}, "commit": {"oid": head}},
                {
                    "state": "CHANGES_REQUESTED",
                    "author": {"login": "opencode-agent"},
                    "commit": {"oid": head},
                    "body": "Actionable source-backed finding with suggested diff.",
                },
            ]
        },
        reviewThreads={"nodes": [{"id": "thread", "isResolved": False, "isOutdated": False}]},
    )

    assert fix.needs_autofix(pr) == (
        True,
        ("current-head OpenCode requested changes", "1 active unresolved review thread(s)"),
    )


def test_needs_autofix_ignores_thread_only_feedback():
    """Thread-only feedback must not start an autonomous autofix run."""
    pr = make_pr(
        reviewThreads={"nodes": [{"id": "thread", "isResolved": False, "isOutdated": False}]},
    )

    assert fix.needs_autofix(pr) == (False, ())


@pytest.mark.parametrize(
    ("merge_state", "body"),
    [
        ("DIRTY", "Actionable source-backed finding with suggested diff."),
        ("CONFLICTING", "Actionable source-backed finding with suggested diff."),
        ("CLEAN", "OpenCode could not establish approval sufficiency because the model pool exhausted."),
        ("CLEAN", "OpenCode found unresolved reviewer or review-agent thread evidence before approval."),
        ("CLEAN", "Failed-check evidence reports coverage-evidence failure."),
        ("CLEAN", "Failed check evidence shows coverage-evidence failed on the current head."),
    ],
)
def test_needs_autofix_suppresses_process_only_reviews(merge_state, body):
    """Process-only or non-clean OpenCode requests do not dispatch autofix."""
    head = "a" * 40
    pr = make_pr(
        headRefOid=head,
        mergeStateStatus=merge_state,
        reviews={
            "nodes": [
                {
                    "state": "CHANGES_REQUESTED",
                    "author": {"login": "opencode-agent"},
                    "commit": {"oid": head},
                    "body": body,
                },
            ]
        },
    )

    assert fix.needs_autofix(pr) == (False, ())


def test_change_request_requires_current_head_opencode_review():
    """Autofixable change requests require an OpenCode review on the current head."""
    head = "a" * 40
    stale_head = "b" * 40

    no_review_pr = make_pr(headRefOid=head, mergeStateStatus="CLEAN")
    assert fix.latest_current_head_opencode_review(no_review_pr) is None
    assert not fix.change_request_is_autofixable(no_review_pr)

    stale_review_pr = make_pr(
        headRefOid=head,
        mergeStateStatus="CLEAN",
        reviews={
            "nodes": [
                {
                    "state": "CHANGES_REQUESTED",
                    "author": {"login": "opencode-agent"},
                    "commit": {"oid": stale_head},
                    "body": "Actionable source-backed finding with a suggested diff.",
                }
            ]
        },
    )
    assert fix.latest_current_head_opencode_review(stale_review_pr) is None
    assert not fix.change_request_is_autofixable(stale_review_pr)


def test_process_queue_dispatches_same_repo_current_head(monkeypatch, capsys):
    """The queue path dispatches one same-repository autofix."""
    pr = make_pr()
    calls = []

    monkeypatch.setattr(fix, "fetch_open_prs", lambda repo, max_prs: [pr])
    monkeypatch.setattr(fix, "needs_autofix", lambda pr: (True, ("current-head OpenCode requested changes",)))
    monkeypatch.setattr(fix, "issue_comments", lambda repo, number: [])
    monkeypatch.setattr(
        fix,
        "dispatch_autofix",
        lambda repo, pr, workflow, workflow_repository, dry_run: calls.append((
            "dispatch",
            repo,
            pr["number"],
            workflow,
            workflow_repository,
            dry_run,
        )),
    )
    monkeypatch.setattr(fix, "create_fix_marker", lambda repo, pr, dry_run: calls.append(("marker", repo, pr["number"], dry_run)))

    assert fix.main(["--repo", "owner/repo", "--base-branch", "main", "--dry-run"]) == 0

    assert calls == [
        ("dispatch", "owner/repo", 7, "pr-review-autofix.yml", "ContextualWisdomLab/.github", True),
        ("marker", "owner/repo", 7, True),
    ]
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert payload["autofix_dispatches"] == 1


def test_autofix_context_filters_outdated_threads_and_renders_checks():
    """The context helper filters stale threads and renders compact checks."""
    assert context.repo_parts("owner/repo") == ("owner", "repo")
    assert context.check_summary(
        [
            {"__typename": "CheckRun", "workflowName": "OpenCode Review", "name": "opencode-review", "status": "COMPLETED", "conclusion": "FAILURE"},
            {"__typename": "StatusContext", "context": "lint", "state": "SUCCESS"},
        ]
    ) == ["- OpenCode Review/opencode-review: COMPLETED FAILURE", "- lint: SUCCESS"]
    with pytest.raises(SystemExit):
        context.parse_args(["--repo", "bad repo", "--pr-number", "1", "--head-sha", "a" * 40, "--output", "out.md"])


def test_context_run_json_and_pr_fetch(monkeypatch):
    """Context gh wrappers decode JSON and surface command errors."""
    calls = []

    def fake_run(argv, check, stdout, stderr, text, shell=False):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout='{"ok": true}', stderr="")

    monkeypatch.setattr(context.subprocess, "run", fake_run)
    assert context.run_json(["api", "x"]) == {"ok": True}
    assert context.pr_view("owner/repo", 3) == {"ok": True}
    assert calls[1][:4] == ["gh", "pr", "view", "3"]

    def failed_run(argv, check, stdout, stderr, text, shell=False):
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="bad gh")

    monkeypatch.setattr(context.subprocess, "run", failed_run)
    with pytest.raises(RuntimeError, match="bad gh"):
        context.run_json(["api", "x"])


def test_context_reviews_threads_and_writer(monkeypatch, tmp_path):
    """Context writer includes current reviews, active threads, and checks."""
    head = "a" * 40
    pr = {
        "number": 7,
        "title": "Fix review",
        "url": "https://example.test/pr/7",
        "headRefName": "feature",
        "baseRefName": "main",
        "headRefOid": head,
        "baseRefOid": "b" * 40,
        "mergeStateStatus": "CLEAN",
        "statusCheckRollup": [
            {"__typename": "CheckRun", "name": "tests", "status": "COMPLETED", "conclusion": "SUCCESS"},
            {"__typename": "StatusContext", "context": "lint", "state": "SUCCESS"},
        ],
    }
    reviews = [
        [
            {"commit_id": "old", "state": "COMMENTED", "body": ""},
            {"commit_id": head, "state": "COMMENTED", "body": "not a decision"},
        ],
        [
            {"commit_id": head, "state": "APPROVED", "user": {"login": "opencode-agent"}, "body": "looks good"},
            {"commit_id": "old", "state": "CHANGES_REQUESTED", "user": {"login": "opencode-agent"}, "body": head},
        ],
    ]
    threads = [
        {"id": "resolved", "isResolved": True, "isOutdated": False, "comments": {"nodes": []}},
        {"id": "outdated", "isResolved": False, "isOutdated": True, "comments": {"nodes": []}},
        {
            "id": "active",
            "isResolved": False,
            "isOutdated": False,
            "comments": {"nodes": [{"author": {"login": "reviewer"}, "path": "x.py", "line": 12, "body": "please fix"}]},
        },
    ]

    def fake_run_json(args):
        joined = " ".join(args)
        if args[:2] == ["pr", "view"]:
            return pr
        if "pulls/7/reviews" in joined:
            return reviews
        if args[:2] == ["api", "graphql"]:
            return {"data": {"repository": {"pullRequest": {"reviewThreads": {"nodes": threads}}}}}
        raise AssertionError(args)

    monkeypatch.setattr(context, "run_json", fake_run_json)
    assert [r["state"] for r in context.current_reviews("owner/repo", 7, head)] == ["APPROVED", "CHANGES_REQUESTED"]
    assert [t["id"] for t in context.review_threads("owner/repo", 7)] == ["active"]
    assert context.thread_paths(context.review_threads("owner/repo", 7)) == ["x.py"]

    output = tmp_path / "context.md"
    context.write_context("owner/repo", 7, head, output)
    body = output.read_text()
    assert "APPROVED by opencode-agent" in body
    assert "## Autofix Allowed Paths" in body
    assert "- `x.py`" in body
    assert "Thread active" in body
    assert "- tests: COMPLETED SUCCESS" in body
    assert body.index("## Autofix Allowed Paths") < body.index("## Current Reviews")

    monkeypatch.setattr(context, "pr_view", lambda repo, number: {**pr, "headRefOid": "c" * 40})
    with pytest.raises(RuntimeError, match="live head"):
        context.write_context("owner/repo", 7, head, output)


def test_autofix_thread_paths_filters_unsafe_and_duplicate_paths():
    """Autofix edits are bounded to unique safe repository-relative review paths."""
    threads = [
        {
            "comments": {
                "nodes": [
                    {"path": "tests/test_example.py"},
                    {"path": "tests/test_example.py"},
                    {"path": "/etc/passwd"},
                    {"path": "docs/../secret.md"},
                    {"path": ""},
                    {},
                ]
            }
        },
        {"comments": {"nodes": [{"path": "scripts/fix.py"}]}},
    ]

    assert context.thread_paths(threads) == ["tests/test_example.py", "scripts/fix.py"]


def test_context_writer_empty_reviews_threads_and_validation(monkeypatch, tmp_path):
    """Context writer handles empty bounded review evidence."""
    head = "a" * 40
    pr = {
        "number": 7,
        "title": "Fix review",
        "url": "https://example.test/pr/7",
        "headRefName": "feature",
        "baseRefName": "main",
        "headRefOid": head,
        "baseRefOid": "b" * 40,
        "mergeStateStatus": "CLEAN",
        "statusCheckRollup": [],
    }
    monkeypatch.setattr(context, "pr_view", lambda repo, number: pr)
    monkeypatch.setattr(context, "current_reviews", lambda repo, number, head_sha: [])
    monkeypatch.setattr(context, "review_threads", lambda repo, number: [])

    output = tmp_path / "context.md"
    context.write_context("owner/repo", 7, head, output)
    body = output.read_text()
    assert "(no current-head review objects)" in body
    assert "(no unresolved non-outdated review threads)" in body
    assert context.current_reviews(
        "owner/repo",
        7,
        head,
    ) == []
    with pytest.raises(ValueError):
        context.repo_parts("owner")


def test_context_parse_and_main(monkeypatch, tmp_path):
    """Context CLI validates arguments and calls the writer."""
    head = "a" * 40
    output = tmp_path / "out.md"
    called = []
    monkeypatch.setattr(context, "write_context", lambda repo, number, head_sha, out: called.append((repo, number, head_sha, out)))

    args = context.parse_args(["--repo", "owner/repo", "--pr-number", "1", "--head-sha", head, "--output", str(output)])
    assert args.repo == "owner/repo"
    assert context.main(["--repo", "owner/repo", "--pr-number", "1", "--head-sha", head, "--output", str(output)]) == 0
    assert called == [("owner/repo", 1, head, output)]

    for bad_args in (
        ["--pr-number", "1", "--head-sha", head, "--output", str(output)],
        ["--repo", "owner/repo", "--pr-number", "0", "--head-sha", head, "--output", str(output)],
        ["--repo", "owner/repo", "--pr-number", "1", "--head-sha", "bad", "--output", str(output)],
    ):
        monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
        with pytest.raises(SystemExit):
            context.parse_args(bad_args)

    monkeypatch.setattr(sys, "argv", ["pr_review_autofix_context.py", "--repo", "bad repo", "--pr-number", "1", "--head-sha", head, "--output", str(output)])
    with pytest.raises(SystemExit):
        runpy.run_path("scripts/ci/pr_review_autofix_context.py", run_name="__main__")


def test_fix_run_json_comment_marker_and_dispatch(monkeypatch, capsys):
    """Fix scheduler gh wrappers and mutation helpers use plain argv."""
    calls = []
    monkeypatch.setattr(
        fix,
        "run",
        lambda argv: calls.append(argv)
        or ('[[{"id": 1}]]' if any("issues/7/comments" in item for item in argv) else '[{"id": 1}]'),
    )
    assert fix.run_json(["api", "x"]) == [{"id": 1}]
    assert fix.issue_comments("owner/repo", 7) == [{"id": 1}]

    pr = make_pr()
    fix.create_fix_marker("owner/repo", pr, dry_run=True)
    fix.dispatch_autofix(
        "owner/repo",
        pr,
        workflow="fix.yml",
        workflow_repository="ContextualWisdomLab/.github",
        dry_run=True,
    )
    assert "DRY-RUN: would create autofix marker" in capsys.readouterr().out

    fix.create_fix_marker("owner/repo", pr, dry_run=False)
    fix.dispatch_autofix(
        "owner/repo",
        pr,
        workflow="fix.yml",
        workflow_repository="ContextualWisdomLab/.github",
        dry_run=False,
    )
    assert calls[-2][:5] == ["gh", "api", "-X", "POST", "repos/owner/repo/issues/7/comments"]
    assert calls[-1][:6] == ["gh", "workflow", "run", "fix.yml", "--repo", "ContextualWisdomLab/.github"]
    assert "-f" in calls[-1]
    assert "target_repository=owner/repo" in calls[-1]


def test_fix_inspect_skip_wait_and_error_paths(monkeypatch):
    """Inspect and queue logic report skip, wait, dispatch-limit, and errors."""
    args = fix.parse_args(["--repo", "owner/repo", "--base-branch", "main"])
    assert fix.inspect_pr("owner/repo", make_pr(isDraft=True), args) == ("skip", ("draft PR",))
    assert fix.inspect_pr("owner/repo", make_pr(baseRefName="develop"), args)[1][0].startswith("base branch")
    assert fix.inspect_pr("owner/repo", make_pr(headRepository={"nameWithOwner": "fork/repo"}), args)[1] == (
        "external PR head is not writable by repository workflow credentials",
    )

    monkeypatch.setattr(fix, "needs_autofix", lambda pr: (False, ()))
    assert fix.inspect_pr("owner/repo", make_pr(), args) == (
        "skip",
        ("no current-head autofixable OpenCode change request",),
    )

    monkeypatch.setattr(fix, "needs_autofix", lambda pr: (True, ("reason",)))
    monkeypatch.setattr(fix, "issue_comments", lambda repo, number: [{"body": f"{fix.FIX_MARKER} head_sha={'a' * 40} epoch={int(time.time())} -->"}])
    assert fix.inspect_pr("owner/repo", make_pr(), args) == ("wait", ("recent autofix marker exists for this head",))

    pr1 = make_pr(number=1)
    pr2 = make_pr(number=2)
    monkeypatch.setattr(fix, "fetch_open_prs", lambda repo, max_prs: [pr1, pr2])
    monkeypatch.setattr(fix, "inspect_pr", lambda repo, pr, args, **kwargs: ("dispatch", ("reason",)))
    payload_lines = []
    monkeypatch.setattr("builtins.print", lambda *parts, **kwargs: payload_lines.append(" ".join(map(str, parts))))
    assert fix.process_queue(args) == 0
    assert "autofix dispatch limit reached" in payload_lines[-1]

    monkeypatch.setattr(fix, "fetch_pr", lambda repo, number: [make_pr(number=number)])
    monkeypatch.setattr(fix, "inspect_pr", lambda repo, pr, args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    args = fix.parse_args(["--repo", "owner/repo", "--base-branch", "main", "--pr-number", "3"])
    payload_lines.clear()
    assert fix.process_queue(args) == 0
    assert '"action": "error"' in payload_lines[-1]


def test_fix_parse_args_and_self_test(monkeypatch):
    """Fix scheduler CLI validates inputs and exposes self-test."""
    assert fix.main(["--self-test"]) == 0
    assert fix.parse_args(["--self-test"]).self_test
    monkeypatch.setattr(sys, "argv", ["pr_review_fix_scheduler.py", "--self-test"])
    with pytest.raises(SystemExit) as exc:
        runpy.run_path("scripts/ci/pr_review_fix_scheduler.py", run_name="__main__")
    assert exc.value.code == 0

    for bad_args in (
        ["--base-branch", "main"],
        ["--repo", "bad repo", "--base-branch", "main"],
        ["--repo", "owner/repo"],
        ["--repo", "owner/repo", "--base-branch", "main", "--pr-number", "-1"],
        ["--repo", "owner/repo", "--base-branch", "main", "--max-prs", "0"],
        ["--repo", "owner/repo", "--base-branch", "main", "--max-dispatches", "0"],
        ["--repo", "owner/repo", "--base-branch", "main", "--retry-hours", "0"],
        ["--repo", "owner/repo", "--base-branch", "main", "--autofix-repository", "bad"],
    ):
        monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
        monkeypatch.delenv("DEFAULT_BRANCH", raising=False)
        with pytest.raises(SystemExit):
            fix.parse_args(bad_args)
