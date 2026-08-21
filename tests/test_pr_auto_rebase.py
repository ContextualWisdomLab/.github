import json
import runpy
import sys
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from scripts.ci import pr_auto_rebase as rebase


NOW = datetime(2026, 7, 8, 12, 0, tzinfo=timezone.utc)
BOT_COMMIT = {"author": {"name": "opencode-agent", "user": {"login": "opencode-agent"}}}
HUMAN_COMMIT = {"author": {"name": "Ada Lovelace", "user": {"login": "ada"}}}


def make_pr(**overrides):
    value = {
        "number": 1,
        "isDraft": False,
        "mergeStateStatus": "BEHIND",
        "baseRefName": "main",
        "baseRefOid": "b" * 40,
        "headRefName": "feature",
        "headRefOid": "a" * 40,
        "isCrossRepository": False,
        "maintainerCanModify": False,
        "labels": {"nodes": []},
        "headRepository": {"nameWithOwner": "owner/repo"},
        "commits": {"nodes": [{"commit": {"committedDate": "2026-07-01T00:00:00Z", **BOT_COMMIT}}]},
    }
    value.update(overrides)
    return value


def with_manual_label(**overrides):
    """Return a PR payload already carrying the needs-manual-rebase label."""
    overrides.setdefault("labels", {"nodes": [{"name": rebase.MANUAL_REBASE_LABEL}]})
    return make_pr(**overrides)


def skip_reason(pr, *, base_branch="main", human_window_minutes=30):
    return rebase.candidate_skip_reason(
        "owner/repo", pr, base_branch=base_branch, now=NOW, human_window_minutes=human_window_minutes
    )


def test_fetch_open_prs_zero_limit_avoids_graphql(monkeypatch):
    """A zero internal bound returns immediately without a transport call."""

    monkeypatch.setattr(
        rebase, "gh_graphql", lambda *a, **k: pytest.fail("must not query")
    )
    assert rebase.fetch_open_prs("owner/repo", 0) == []


# --- candidate selection -------------------------------------------------


def test_behind_and_dirty_prs_are_candidates():
    """A bot branch that is behind or dirty against its base is a rebase candidate."""
    assert skip_reason(make_pr(mergeStateStatus="BEHIND")) is None
    assert skip_reason(make_pr(mergeStateStatus="DIRTY")) is None
    assert skip_reason(make_pr(mergeStateStatus="CONFLICTING")) is None


def test_draft_pr_is_excluded():
    """Draft PRs are never rebased."""
    assert "draft" in skip_reason(make_pr(isDraft=True))


def test_fork_head_is_excluded():
    """Cross-repository fork heads are excluded because they are not pushable."""
    reason = skip_reason(make_pr(headRepository={"nameWithOwner": "fork/repo"}))
    assert "fork" in reason and "fork/repo" in reason


def test_already_clean_pr_is_excluded():
    """A mergeable, up-to-date PR is never touched."""
    assert "up to date" in skip_reason(make_pr(mergeStateStatus="CLEAN"))


def test_not_behind_not_dirty_is_excluded():
    """A PR that is neither behind nor dirty (e.g. BLOCKED) is not a candidate."""
    assert "not behind" in skip_reason(make_pr(mergeStateStatus="BLOCKED"))
    assert "not behind" in skip_reason(make_pr(mergeStateStatus="UNKNOWN"))


def test_base_branch_mismatch_is_excluded():
    """PRs targeting a different base branch are skipped."""
    reason = skip_reason(make_pr(baseRefName="develop"))
    assert "base branch is develop" in reason


def test_recent_human_commit_is_excluded():
    """A branch whose newest commit is a recent human commit is skipped."""
    pr = make_pr(commits={"nodes": [{"commit": {"committedDate": "2026-07-08T11:45:00Z", **HUMAN_COMMIT}}]})
    reason = skip_reason(pr)
    assert "active work" in reason and "ada" in reason


def test_stale_human_commit_is_a_candidate():
    """A human commit older than the window no longer blocks auto-rebase."""
    pr = make_pr(commits={"nodes": [{"commit": {"committedDate": "2026-07-08T10:00:00Z", **HUMAN_COMMIT}}]})
    assert skip_reason(pr) is None


def test_missing_base_branch_is_excluded():
    """A PR with no base branch is skipped."""
    assert "no base branch" in skip_reason(make_pr(baseRefName=""))


def test_human_commit_with_unparseable_date_is_a_candidate():
    """A human commit with an unreadable timestamp does not block rebase."""
    pr = make_pr(commits={"nodes": [{"commit": {"committedDate": "not-a-date", **HUMAN_COMMIT}}]})
    assert skip_reason(pr) is None


def test_recent_bot_commit_is_a_candidate():
    """A recent bot commit does not trigger the human-activity guard."""
    pr = make_pr(commits={"nodes": [{"commit": {"committedDate": "2026-07-08T11:59:00Z", **BOT_COMMIT}}]})
    assert skip_reason(pr) is None


def test_zero_human_window_disables_guard():
    """A zero human window means recent human commits are still rebased."""
    pr = make_pr(commits={"nodes": [{"commit": {"committedDate": "2026-07-08T11:59:00Z", **HUMAN_COMMIT}}]})
    assert skip_reason(pr, human_window_minutes=0) is None


def test_has_manual_rebase_label_detects_label():
    """The label predicate matches only the manual-rebase label."""
    assert rebase.has_manual_rebase_label(with_manual_label())
    assert not rebase.has_manual_rebase_label(make_pr())
    assert not rebase.has_manual_rebase_label(make_pr(labels={"nodes": [{"name": "other"}]}))


def test_labeled_dirty_pr_is_skipped_without_consuming_slot():
    """A still-DIRTY PR already labeled needs-manual-rebase is skipped, not re-processed."""
    reason = skip_reason(with_manual_label(mergeStateStatus="DIRTY"))
    assert rebase.MANUAL_REBASE_LABEL in reason
    assert "rate-limit slot" in reason
    # CONFLICTING is the other dirty state and is skipped too.
    assert rebase.MANUAL_REBASE_LABEL in skip_reason(with_manual_label(mergeStateStatus="CONFLICTING"))


def test_labeled_but_no_longer_dirty_is_a_candidate():
    """A previously-labeled PR that is only BEHIND (conflict resolved) is a candidate again."""
    assert skip_reason(with_manual_label(mergeStateStatus="BEHIND")) is None


def test_commit_author_bot_detection():
    """Bot detection covers known logins, ``[bot]`` suffixes, and humans."""
    assert rebase.commit_author_is_bot(BOT_COMMIT)
    assert rebase.commit_author_is_bot({"author": {"name": "x", "user": {"login": "dependabot[bot]"}}})
    assert rebase.commit_author_is_bot({"author": {"name": "renovate[bot]", "user": None}})
    assert not rebase.commit_author_is_bot(HUMAN_COMMIT)
    assert not rebase.commit_author_is_bot({"author": {"name": "Ada", "user": None}})


# --- rebase decision (mock git) -----------------------------------------


def test_perform_rebase_clean_force_pushes(monkeypatch):
    """A conflict-free rebase uses the shared leased publication boundary."""
    calls = []
    monkeypatch.setattr(rebase, "scheduler_token", lambda: "tok")
    monkeypatch.setattr(rebase, "fetch_pr_refs", lambda *a, **k: calls.append(("fetch", a[2], a[3])))
    monkeypatch.setattr(rebase, "try_rebase", lambda workdir, base_ref: True)
    monkeypatch.setattr(
        rebase,
        "publish_head",
        lambda workdir, repo, number, head_ref, expected, **kwargs: calls.append(
            ("publish", number, head_ref, expected, kwargs)
        )
        or SimpleNamespace(mode="direct", pull_number=None, url=None),
    )
    monkeypatch.setattr(rebase, "label_conflicted_pr", lambda *a, **k: pytest.fail("should not label a clean rebase"))

    decision = rebase.perform_rebase("owner/repo", make_pr(), dry_run=False)

    assert decision.action == "rebased"
    publication = next(call for call in calls if call[0] == "publish")
    assert publication[1:4] == (1, "feature", "a" * 40)
    assert publication[4] == {"token": "tok", "kind": "rebase", "force_with_lease": True}
    assert calls[0] == ("fetch", "feature", "main")


def test_perform_rebase_conflict_labels_without_push(monkeypatch):
    """A conflicting rebase labels the PR and never force-pushes."""
    labeled = []
    monkeypatch.setattr(rebase, "scheduler_token", lambda: "tok")
    monkeypatch.setattr(rebase, "fetch_pr_refs", lambda *a, **k: None)
    monkeypatch.setattr(rebase, "try_rebase", lambda workdir, base_ref: False)
    monkeypatch.setattr(rebase, "publish_head", lambda *a, **k: pytest.fail("must not publish a conflicted branch"))
    monkeypatch.setattr(
        rebase,
        "label_conflicted_pr",
        lambda repo, pr, base_ref, dry_run: labeled.append((repo, pr["number"], base_ref, dry_run))
        or ("labeled needs-manual-rebase", "posted hand-off comment"),
    )

    decision = rebase.perform_rebase("owner/repo", make_pr(), dry_run=False)

    assert decision.action == "labeled"
    assert labeled == [("owner/repo", 1, "main", False)]
    assert "posted hand-off comment" in decision.notes


def test_perform_rebase_removes_stale_label_then_rebases(monkeypatch):
    """A labeled PR that is no longer dirty has the stale label removed, then rebases."""
    removed = []
    monkeypatch.setattr(rebase, "scheduler_token", lambda: "tok")
    monkeypatch.setattr(rebase, "fetch_pr_refs", lambda *a, **k: None)
    monkeypatch.setattr(rebase, "try_rebase", lambda workdir, base_ref: True)
    monkeypatch.setattr(
        rebase,
        "publish_head",
        lambda *a, **k: SimpleNamespace(mode="direct", pull_number=None, url=None),
    )
    monkeypatch.setattr(
        rebase,
        "remove_manual_rebase_label",
        lambda repo, number, dry_run: removed.append((repo, number, dry_run)),
    )

    decision = rebase.perform_rebase("owner/repo", with_manual_label(mergeStateStatus="BEHIND"), dry_run=False)

    assert removed == [("owner/repo", 1, False)]
    assert decision.action == "rebased"
    assert any("removed stale" in note for note in decision.notes)


def test_remove_manual_rebase_label_delete_and_tolerance(monkeypatch):
    """Removing the label DELETEs the endpoint, tolerates 404, and reraises other errors."""
    monkeypatch.setattr(rebase, "run", lambda argv: pytest.fail("dry-run must not call gh"))
    rebase.remove_manual_rebase_label("owner/repo", 1, dry_run=True)

    captured = {}
    monkeypatch.setattr(rebase, "run", lambda argv: captured.setdefault("argv", argv) or "")
    rebase.remove_manual_rebase_label("owner/repo", 7, dry_run=False)
    assert captured["argv"][:4] == ["gh", "api", "-X", "DELETE"]
    assert captured["argv"][4] == f"repos/owner/repo/issues/7/labels/{rebase.MANUAL_REBASE_LABEL}"

    monkeypatch.setattr(rebase, "run", lambda argv: (_ for _ in ()).throw(RuntimeError("HTTP 404: Not Found")))
    rebase.remove_manual_rebase_label("owner/repo", 7, dry_run=False)  # tolerated

    monkeypatch.setattr(rebase, "run", lambda argv: (_ for _ in ()).throw(RuntimeError("HTTP 500: boom")))
    with pytest.raises(RuntimeError, match="boom"):
        rebase.remove_manual_rebase_label("owner/repo", 7, dry_run=False)


def test_label_conflicted_pr_creates_label_and_comments_once(monkeypatch):
    """Conflict labeling ensures the label, adds it, and comments only once."""
    events = []
    monkeypatch.setattr(rebase, "ensure_manual_rebase_label", lambda repo, dry_run: events.append(("ensure", dry_run)))
    monkeypatch.setattr(
        rebase, "add_manual_rebase_label", lambda repo, number, dry_run: events.append(("add", number))
    )
    monkeypatch.setattr(rebase, "conflict_comment_exists", lambda repo, number: False)

    posted = []
    monkeypatch.setattr(rebase, "run", lambda argv: posted.append(argv) or "")
    notes = rebase.label_conflicted_pr("owner/repo", make_pr(), "main", dry_run=False)
    assert ("ensure", False) in events and ("add", 1) in events
    assert "posted hand-off comment" in notes
    assert posted[-1][:5] == ["gh", "api", "-X", "POST", "repos/owner/repo/issues/1/comments"]

    # Second pass: an existing marker comment means no duplicate comment.
    monkeypatch.setattr(rebase, "conflict_comment_exists", lambda repo, number: True)
    posted.clear()
    notes = rebase.label_conflicted_pr("owner/repo", make_pr(), "main", dry_run=False)
    assert notes[-1] == "hand-off comment already present"
    assert posted == []


def test_conflict_comment_exists_matches_marker(monkeypatch):
    """The one-time comment guard looks for the auto-rebase marker."""
    payload = [[{"body": f"prefix {rebase.CONFLICT_COMMENT_MARKER} suffix"}]]
    monkeypatch.setattr(rebase, "run", lambda argv: json.dumps(payload))
    assert rebase.conflict_comment_exists("owner/repo", 1)
    monkeypatch.setattr(rebase, "run", lambda argv: json.dumps([[{"body": "unrelated"}]]))
    assert not rebase.conflict_comment_exists("owner/repo", 1)


def test_ensure_label_tolerates_existing(monkeypatch):
    """Creating the label swallows an already-exists error but reraises others."""
    monkeypatch.setattr(
        rebase, "run", lambda argv: (_ for _ in ()).throw(RuntimeError("HTTP 422: already_exists"))
    )
    rebase.ensure_manual_rebase_label("owner/repo", dry_run=False)  # does not raise

    monkeypatch.setattr(rebase, "run", lambda argv: (_ for _ in ()).throw(RuntimeError("HTTP 500: boom")))
    with pytest.raises(RuntimeError, match="boom"):
        rebase.ensure_manual_rebase_label("owner/repo", dry_run=False)


# --- queue, rate limit, and dry-run -------------------------------------


def test_process_queue_rate_limits_oldest_first(monkeypatch, capsys):
    """The rate limit caps rebases per run and processes oldest PRs first."""
    prs = [make_pr(number=n) for n in (1, 2, 3)]
    monkeypatch.setattr(rebase, "fetch_open_prs", lambda repo, max_prs: prs)
    performed = []
    monkeypatch.setattr(
        rebase,
        "perform_rebase",
        lambda repo, pr, dry_run: performed.append(pr["number"])
        or rebase.Decision(pr["number"], "rebased", "ok"),
    )

    args = rebase.parse_args(["--repo", "owner/repo", "--base-branch", "main", "--max-per-run", "2"])
    assert rebase.process_queue(args) == 0

    assert performed == [1, 2]
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert payload["counts"]["rebased"] == 2
    assert payload["counts"]["skip"] == 1
    skipped = [d for d in payload["decisions"] if d["action"] == "skip"]
    assert skipped[0]["pr"] == 3 and "rate limit" in skipped[0]["reason"]


def test_process_queue_labeled_dirty_pr_does_not_starve_newer(monkeypatch, capsys):
    """A labeled, still-DIRTY old PR is skipped and does not consume the rate-limit slot."""
    prs = [
        with_manual_label(number=1, mergeStateStatus="DIRTY"),  # old, conflicted, already labeled
        make_pr(number=2),  # newer, genuinely rebasable
    ]
    monkeypatch.setattr(rebase, "fetch_open_prs", lambda repo, max_prs: prs)
    performed = []
    monkeypatch.setattr(
        rebase,
        "perform_rebase",
        lambda repo, pr, dry_run: performed.append(pr["number"])
        or rebase.Decision(pr["number"], "rebased", "ok"),
    )

    args = rebase.parse_args(["--repo", "owner/repo", "--base-branch", "main", "--max-per-run", "1"])
    assert rebase.process_queue(args) == 0

    # PR #1 never reaches git work; the single slot goes to the newer PR #2.
    assert performed == [2]
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    actions = {d["pr"]: d["action"] for d in payload["decisions"]}
    assert actions == {1: "skip", 2: "rebased"}
    skip = next(d for d in payload["decisions"] if d["pr"] == 1)
    assert rebase.MANUAL_REBASE_LABEL in skip["reason"]


def test_process_queue_dry_run_plans_without_mutation(monkeypatch, capsys):
    """Dry-run reports candidates and the cap without calling perform_rebase."""
    prs = [make_pr(number=1), make_pr(number=2, isDraft=True)]
    monkeypatch.setattr(rebase, "fetch_open_prs", lambda repo, max_prs: prs)
    monkeypatch.setattr(rebase, "perform_rebase", lambda *a, **k: pytest.fail("dry-run must not mutate"))

    args = rebase.parse_args(["--repo", "owner/repo", "--base-branch", "main", "--dry-run"])
    assert rebase.process_queue(args) == 0

    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert payload["dry_run"] is True
    actions = {d["pr"]: d["action"] for d in payload["decisions"]}
    assert actions == {1: "would_rebase", 2: "skip"}


def test_process_queue_records_errors(monkeypatch, capsys):
    """A rebase failure is captured as a scrubbed error decision, not a crash."""
    leaked_token = "g" + "hs" + "_supersecret"
    monkeypatch.setattr(rebase, "fetch_open_prs", lambda repo, max_prs: [make_pr(number=5)])
    monkeypatch.setattr(
        rebase,
        "perform_rebase",
        lambda repo, pr, dry_run: (_ for _ in ()).throw(RuntimeError(f"token {leaked_token} leaked\nsecond line")),
    )
    args = rebase.parse_args(["--repo", "owner/repo", "--base-branch", "main"])
    assert rebase.process_queue(args) == 0
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    error = [d for d in payload["decisions"] if d["action"] == "error"][0]
    assert leaked_token not in error["reason"]
    assert "second line" not in error["reason"]


def test_scheduler_token_requires_gh_token(monkeypatch):
    """The git credential must come from GH_TOKEN wired by the workflow."""
    monkeypatch.delenv("GH_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="GH_TOKEN is required"):
        rebase.scheduler_token()
    monkeypatch.setenv("GH_TOKEN", "tok")
    assert rebase.scheduler_token() == "tok"


def test_authenticated_remote_url_uses_app_token():
    """Git remotes use the app token via the x-access-token user."""
    url = rebase.authenticated_remote_url("owner/repo", "tok")
    assert url == "https://x-access-token:tok@github.com/owner/repo.git"


# --- CLI ----------------------------------------------------------------


def test_parse_args_validates_inputs(monkeypatch):
    """CLI parsing rejects malformed repositories and negative bounds."""
    for bad_args in (
        ["--base-branch", "main"],
        ["--repo", "bad repo", "--base-branch", "main"],
        ["--repo", "owner/repo"],
        ["--repo", "owner/repo", "--base-branch", "main", "--max-prs", "0"],
        ["--repo", "owner/repo", "--base-branch", "main", "--max-per-run", "-1"],
        ["--repo", "owner/repo", "--base-branch", "main", "--human-window-minutes", "-1"],
    ):
        monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
        monkeypatch.delenv("DEFAULT_BRANCH", raising=False)
        with pytest.raises(SystemExit):
            rebase.parse_args(bad_args)


def test_main_self_test_and_module_entrypoint(monkeypatch):
    """The self-test path exits cleanly through main and the module entrypoint."""
    assert rebase.main(["--self-test"]) == 0
    assert rebase.parse_args(["--self-test"]).self_test
    monkeypatch.setattr(sys, "argv", ["pr_auto_rebase.py", "--self-test"])
    with pytest.raises(SystemExit) as exc:
        runpy.run_path("scripts/ci/pr_auto_rebase.py", run_name="__main__")
    assert exc.value.code == 0


def test_main_delegates_to_process_queue(monkeypatch):
    """Non-self-test main runs the queue for the configured repository."""
    seen = []
    monkeypatch.setattr(rebase, "process_queue", lambda args: seen.append(args.repo) or 0)
    assert rebase.main(["--repo", "owner/repo", "--base-branch", "main"]) == 0
    assert seen == ["owner/repo"]


# --- gh/git I/O helpers --------------------------------------------------


def test_fetch_open_prs_paginates(monkeypatch):
    """Open PRs are fetched oldest-first across GraphQL pages up to max_prs."""
    pages = [
        {
            "data": {
                "repository": {
                    "pullRequests": {
                        "pageInfo": {"hasNextPage": True, "endCursor": "c1"},
                        "nodes": [make_pr(number=1)],
                    }
                }
            }
        },
        {
            "data": {
                "repository": {
                    "pullRequests": {
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "nodes": [make_pr(number=2)],
                    }
                }
            }
        },
    ]
    seen_cursors = []

    def fake_graphql(query, **fields):
        seen_cursors.append(fields.get("cursor"))
        return pages[len(seen_cursors) - 1]

    monkeypatch.setattr(rebase, "gh_graphql", fake_graphql)
    prs = rebase.fetch_open_prs("owner/repo", 100)
    assert [pr["number"] for pr in prs] == [1, 2]
    assert seen_cursors == [None, "c1"]


def test_git_runs_with_and_without_env(monkeypatch):
    """The git helper wraps argv with -C and applies an env override when given."""
    calls = []
    monkeypatch.setattr(rebase, "run", lambda argv: calls.append(("plain", argv)) or "out")
    monkeypatch.setattr(
        rebase, "run_with_env", lambda argv, env: calls.append(("env", argv, env.get("GIT_TERMINAL_PROMPT"))) or "out"
    )
    assert rebase.git("/w", ["status"]) == "out"
    assert calls[0] == ("plain", ["git", "-C", "/w", "status"])
    rebase.git("/w", ["init"], env={"GIT_TERMINAL_PROMPT": "0"})
    assert calls[1][0] == "env" and calls[1][2] == "0"


def test_fetch_pr_refs_sequence(monkeypatch):
    """The work-repo bootstrap inits, fetches only the two refs, and checks out head."""
    seq = []
    monkeypatch.setattr(rebase, "git", lambda workdir, args, env=None: seq.append(args))
    rebase.fetch_pr_refs("/w", "owner/repo", "feature", "main", token="tok")
    assert seq[0] == ["init", "--quiet"]
    fetch = next(a for a in seq if a and a[0] == "fetch")
    assert "+refs/heads/main:refs/remotes/origin/main" in fetch
    assert "+refs/heads/feature:refs/remotes/origin/feature" in fetch
    assert seq[-1] == ["checkout", "-B", "feature", "refs/remotes/origin/feature"]


def test_try_rebase_success_and_conflict(monkeypatch):
    """try_rebase returns True on clean apply and False (after abort) on conflict."""
    monkeypatch.setattr(rebase, "git", lambda workdir, args, env=None: "")
    assert rebase.try_rebase("/w", "main") is True

    aborted = []

    def conflicting_git(workdir, args, env=None):
        if args[0] == "rebase" and args[1] != "--abort":
            raise RuntimeError("conflict")
        aborted.append(args)
        return ""

    monkeypatch.setattr(rebase, "git", conflicting_git)
    assert rebase.try_rebase("/w", "main") is False
    assert aborted == [["rebase", "--abort"]]

    def abort_also_fails(workdir, args, env=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(rebase, "git", abort_also_fails)
    assert rebase.try_rebase("/w", "main") is False


def test_perform_rebase_reports_protected_stacked_publication(monkeypatch):
    """A PR-only rule returns an explicit stack rather than a false rebase success."""

    monkeypatch.setattr(rebase, "scheduler_token", lambda: "tok")
    monkeypatch.setattr(rebase, "fetch_pr_refs", lambda *a, **k: None)
    monkeypatch.setattr(rebase, "try_rebase", lambda workdir, base_ref: True)
    monkeypatch.setattr(
        rebase,
        "publish_head",
        lambda *a, **k: SimpleNamespace(
            mode="stacked",
            pull_number=44,
            url="https://github.com/owner/repo/pull/44",
        ),
    )

    decision = rebase.perform_rebase("owner/repo", make_pr(), dry_run=False)

    assert decision.action == "stacked"
    assert "stacked PR #44" in decision.reason
    assert "stack https://github.com/owner/repo/pull/44" in decision.notes


def test_label_helpers_dry_run_short_circuit(monkeypatch):
    """Dry-run label mutations perform no gh calls."""
    monkeypatch.setattr(rebase, "run", lambda argv: pytest.fail("dry-run must not call gh"))
    rebase.ensure_manual_rebase_label("owner/repo", dry_run=True)
    rebase.add_manual_rebase_label("owner/repo", 1, dry_run=True)


def test_add_manual_rebase_label_calls_labels_api(monkeypatch):
    """Adding the label posts to the issue labels endpoint."""
    captured = {}
    monkeypatch.setattr(rebase, "run", lambda argv: captured.setdefault("argv", argv) or "")
    rebase.add_manual_rebase_label("owner/repo", 3, dry_run=False)
    assert captured["argv"][:5] == ["gh", "api", "-X", "POST", "repos/owner/repo/issues/3/labels"]
    assert f"labels[]={rebase.MANUAL_REBASE_LABEL}" in captured["argv"]


def test_ensure_manual_rebase_label_creates_label(monkeypatch):
    """Creating the label posts name, color, and description."""
    captured = {}
    monkeypatch.setattr(rebase, "run", lambda argv: captured.setdefault("argv", argv) or "")
    rebase.ensure_manual_rebase_label("owner/repo", dry_run=False)
    assert captured["argv"][:5] == ["gh", "api", "-X", "POST", "repos/owner/repo/labels"]
    assert f"name={rebase.MANUAL_REBASE_LABEL}" in captured["argv"]


def test_post_conflict_comment_dry_run_and_existing(monkeypatch):
    """Comment posting is skipped in dry-run and when a marker already exists."""
    monkeypatch.setattr(rebase, "run", lambda argv: pytest.fail("must not post"))
    assert rebase.post_conflict_comment("owner/repo", make_pr(), "main", dry_run=True) is False

    monkeypatch.setattr(rebase, "conflict_comment_exists", lambda repo, number: True)
    assert rebase.post_conflict_comment("owner/repo", make_pr(), "main", dry_run=False) is False


def test_post_conflict_comment_posts_marker(monkeypatch):
    """A first-time conflict posts a marker comment with manual steps."""
    monkeypatch.setattr(rebase, "conflict_comment_exists", lambda repo, number: False)
    captured = {}
    monkeypatch.setattr(rebase, "run", lambda argv: captured.setdefault("argv", argv) or "")
    assert rebase.post_conflict_comment("owner/repo", make_pr(number=9), "main", dry_run=False) is True
    body = captured["argv"][-1]
    assert body.startswith("body=")
    assert rebase.CONFLICT_COMMENT_MARKER in body
    assert "gh pr checkout 9" in body


def test_candidate_state_note_variants():
    """The selection note distinguishes behind, dirty, and other merge states."""
    assert rebase.candidate_state_note(make_pr(mergeStateStatus="BEHIND")) == "behind base"
    assert rebase.candidate_state_note(make_pr(mergeStateStatus="DIRTY")) == "dirty against base"
    assert rebase.candidate_state_note(make_pr(mergeStateStatus="UNSTABLE")) == "merge state UNSTABLE"


def test_summarize_error_scrubs_and_bounds():
    """Error summaries are single-line, scrubbed, and length-bounded."""
    assert rebase.summarize_error(RuntimeError("")) == "error"
    long = rebase.summarize_error(RuntimeError("x" * 500))
    assert len(long) == 300


def test_last_commit_handles_missing_nodes():
    """The last-commit helper tolerates PRs without commit nodes."""
    assert rebase.last_commit({}) == {}
    assert rebase.last_commit({"commits": {"nodes": []}}) == {}


def test_write_actions_summary_appends_table(monkeypatch, tmp_path):
    """The step summary writer emits a decision table when a summary path is set."""
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    rebase.print_summary(
        [
            rebase.Decision(1, "rebased", "clean rebase onto main", ("previous head abcdef",)),
            rebase.Decision(2, "labeled", "rebase onto main conflicts"),
        ],
        dry_run=False,
        base_branch="main",
    )
    body = summary.read_text()
    assert "## PR auto-rebase scheduler" in body
    assert "| #1 | rebased |" in body
    assert "| #2 | labeled |" in body


def test_write_actions_summary_noop_without_path(monkeypatch):
    """No step summary file means no summary write."""
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    rebase.write_actions_summary([], counts={}, dry_run=True, base_branch="main")
