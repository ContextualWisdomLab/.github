#!/usr/bin/env python3
"""Publish PR #1669 live-head cancellation repair directly from the exact writer head."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "scripts/ci/pr_review_merge_scheduler.py"
TESTS = ROOT / "tests/test_pr_review_merge_scheduler.py"
DOCTORING = ROOT / "docs/doctoring/scheduler-stale-headrefoid-cancellation.md"
OLD_HELPER = ROOT / "scripts/ci/temp_pr1669_live_head_revalidation_repair.py"
WORKFLOW = ROOT / ".github/workflows/_temp_pr1669_live_head_revalidation_repair.yml"
SELF = Path(__file__).resolve()


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    """Replace exactly one guarded fragment."""
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one source anchor, found {count}")
    return text.replace(old, new, 1)


def repair_source() -> None:
    """Validate classifier heads and revalidate live PR/run authority at cancellation time."""
    text = SOURCE.read_text(encoding="utf-8")
    text = text.replace(
        "docs/doctoring/2026-09-02-strix-current-head-cancellation.md",
        "docs/doctoring/scheduler-stale-headrefoid-cancellation.md",
    )

    stale_anchor = '''        return []
    head = str(raw_head).lower()
    number = int(pr["number"])
    stale: list[str] = []
'''
    stale_replacement = '''        return []
    try:
        head = validate_git_sha(str(raw_head)).lower()
    except (TypeError, ValueError) as exc:
        print(
            f"::warning::stale_pr_run_ids: PR #{pr.get('number')} in {repo} has an "
            f"invalid headRefOid; skipping stale-run cancellation ({exc})."
        )
        return []
    number = int(pr["number"])
    stale: list[str] = []
'''
    text = replace_once(text, stale_anchor, stale_replacement, label="stale classifier SHA validation")

    review_anchor = '''        return [], []
    head = str(raw_head).lower()
    number = int(pr["number"])
    dispatch_title_prefixes = tuple(
'''
    review_replacement = '''        return [], []
    try:
        head = validate_git_sha(str(raw_head)).lower()
    except (TypeError, ValueError) as exc:
        print(
            f"::warning::active_review_run_refs: PR #{pr.get('number')} in {repo} has an "
            f"invalid headRefOid; skipping current/stale classification ({exc})."
        )
        return [], []
    number = int(pr["number"])
    dispatch_title_prefixes = tuple(
'''
    text = replace_once(text, review_anchor, review_replacement, label="review classifier SHA validation")

    old = '''def cancel_stale_pr_runs(repo: str, pr: dict[str, Any], *, dry_run: bool) -> list[str]:
    """Force-cancel queued or running workflows for older heads of the same PR."""
    if dry_run:
        return []
    require_github_actions_control_actor("force-cancel-stale-pr-runs")
    run_ids = stale_pr_run_ids(repo, pr)
    force_cancel_workflow_runs(repo, run_ids)
    return run_ids


def cancel_stale_opencode_runs(repo: str, workflow: str, pr: dict[str, Any], *, dry_run: bool) -> list[str]:
    """Force-cancel older OpenCode runs for the same PR before retrying current head."""
    if dry_run:
        return []
    require_github_actions_control_actor("force-cancel-stale-opencode-review")
    _, stale_refs = active_opencode_run_refs(repo, workflow, pr)
    force_cancel_workflow_run_refs(stale_refs)
    return [run_id for _, run_id in stale_refs]
'''
    new = '''def _fresh_open_pr_for_cancellation(repo: str, number: int) -> dict[str, Any]:
    """Return fresh, still-open and still-ready pull-request authority.

    A destructive cancellation is not authorized by the scheduler's earlier
    GraphQL/event snapshot.  Read the live PR immediately before acting and
    fail closed when the PR is closed, draft, malformed, or unavailable.
    """
    payload = gh_api_json(f"repos/{repo}/pulls/{number}")
    if not isinstance(payload, dict) or str(payload.get("state") or "").lower() != "open":
        raise ValueError(f"PR #{number} in {repo} is not a resolvable open pull request")
    if payload.get("draft") is not False:
        raise ValueError(f"PR #{number} in {repo} is not live ready-for-review authority")
    validate_git_sha(str(((payload.get("head") or {}).get("sha")) or ""))
    return payload


def _fresh_active_run_for_cancellation(run_repo: str, run_id: str) -> dict[str, Any]:
    """Return fresh active workflow-run evidence immediately before cancellation."""
    payload = gh_api_json(f"repos/{run_repo}/actions/runs/{run_id}")
    if not isinstance(payload, dict) or str(payload.get("status") or "").lower() not in {
        "queued",
        "in_progress",
    }:
        raise ValueError(f"workflow run {run_repo}#{run_id} is not active")
    return payload


def _fresh_pr_head_for_cancellation(repo: str, number: int) -> str:
    """Return the validated head SHA from fresh ready/open PR authority."""
    payload = _fresh_open_pr_for_cancellation(repo, number)
    return validate_git_sha(str(((payload.get("head") or {}).get("sha")) or "")).lower()


def _direct_pr_run_still_superseded(repo: str, number: int, run_id: str) -> bool:
    """Return whether a direct PR run is still older than the freshly fetched live head."""
    try:
        run_data = _fresh_active_run_for_cancellation(repo, run_id)
        if run_data.get("event") == "repository_dispatch" or not workflow_run_mentions_pr(
            run_data, number
        ):
            raise ValueError("workflow run no longer has direct pull-request authority")
        run_head = validate_git_sha(str(run_data.get("head_sha") or "")).lower()
        # Keep live PR authority last so the destructive POST follows the newest
        # available head/readiness evidence rather than the classifier snapshot.
        live_head = _fresh_pr_head_for_cancellation(repo, number)
    except (KeyError, RuntimeError, TypeError, ValueError) as exc:
        print(
            f"::warning::Preserving workflow run {run_id} in {repo}: "
            f"live stale-run revalidation failed closed ({exc})."
        )
        return False
    return run_head != live_head


def _review_run_target_head(
    run_data: dict[str, Any], repo: str, workflow: str, number: int
) -> str:
    """Return a validated target head for one direct or central review run."""
    if run_data.get("event") == "repository_dispatch":
        titles = {"Required OpenCode Review", workflow, *OPENCODE_WORKFLOW_NAMES}
        display_title = str(run_data.get("display_title") or "")
        prefixes = tuple(
            f"{title} {repo}#{number}@" for title in sorted(titles, key=len, reverse=True)
        )
        prefix = next((candidate for candidate in prefixes if display_title.startswith(candidate)), None)
        if prefix is None:
            raise ValueError("repository_dispatch run has no trusted target identity")
        return validate_git_sha(display_title.removeprefix(prefix)).lower()
    if not workflow_run_mentions_pr(run_data, number):
        raise ValueError("review run no longer belongs to the target pull request")
    return validate_git_sha(str(run_data.get("head_sha") or "")).lower()


def _review_run_still_superseded(
    repo: str,
    workflow: str,
    number: int,
    run_repo: str,
    run_id: str,
) -> bool:
    """Return whether one review run remains stale against fresh ready/open PR authority."""
    try:
        run_data = _fresh_active_run_for_cancellation(run_repo, run_id)
        run_head = _review_run_target_head(run_data, repo, workflow, number)
        live_head = _fresh_pr_head_for_cancellation(repo, number)
    except (KeyError, RuntimeError, TypeError, ValueError) as exc:
        print(
            f"::warning::Preserving review run {run_repo}#{run_id}: "
            f"live stale-run revalidation failed closed ({exc})."
        )
        return False
    return run_head != live_head


def cancel_stale_pr_runs(repo: str, pr: dict[str, Any], *, dry_run: bool) -> list[str]:
    """Force-cancel only direct-run candidates still proven stale at the destructive boundary."""
    if dry_run:
        return []
    require_github_actions_control_actor("force-cancel-stale-pr-runs")
    number = int(pr["number"])
    candidates = [str(run_id) for run_id in stale_pr_run_ids(repo, pr)]

    def cancel_one(run_id: str) -> str | None:
        if not _direct_pr_run_still_superseded(repo, number, run_id):
            return None
        force_cancel_workflow_runs(repo, [run_id])
        return run_id

    if len(candidates) <= 1:
        results = [cancel_one(run_id) for run_id in candidates]
    else:
        max_workers = min(REST_MERGEABLE_STATE_WORKERS, len(candidates))
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            results = list(executor.map(cancel_one, candidates))
    return [run_id for run_id in results if run_id is not None]


def cancel_stale_opencode_runs(repo: str, workflow: str, pr: dict[str, Any], *, dry_run: bool) -> list[str]:
    """Force-cancel only review candidates still proven stale at the destructive boundary."""
    if dry_run:
        return []
    require_github_actions_control_actor("force-cancel-stale-opencode-review")
    number = int(pr["number"])
    _, stale_refs = active_opencode_run_refs(repo, workflow, pr)

    def cancel_one(run_ref: tuple[str, str]) -> str | None:
        run_repo, run_id = run_ref
        if not _review_run_still_superseded(repo, workflow, number, run_repo, run_id):
            return None
        force_cancel_workflow_runs(run_repo, [run_id])
        return run_id

    if len(stale_refs) <= 1:
        results = [cancel_one(run_ref) for run_ref in stale_refs]
    else:
        max_workers = min(REST_MERGEABLE_STATE_WORKERS, len(stale_refs))
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            results = list(executor.map(cancel_one, stale_refs))
    return [run_id for run_id in results if run_id is not None]
'''
    text = replace_once(text, old, new, label="destructive cancellation implementation")
    SOURCE.write_text(text, encoding="utf-8")


def inject_after_test_def(text: str, name: str, code: str) -> str:
    """Insert a compatibility mock into one named existing regression."""
    anchor = f"def {name}(monkeypatch):\n"
    return replace_once(text, anchor, anchor + code, label=name)


def repair_tests() -> None:
    """Update legacy cancellation tests and add exact-head race/state regressions."""
    text = TESTS.read_text(encoding="utf-8")
    text = text.replace(
        "docs/doctoring/2026-09-02-strix-current-head-cancellation.md",
        "docs/doctoring/scheduler-stale-headrefoid-cancellation.md",
    )
    text = inject_after_test_def(
        text,
        "test_cancel_stale_pr_runs_force_cancels_queued_and_in_progress_old_heads",
        '    monkeypatch.setattr(sched, "_direct_pr_run_still_superseded", lambda *_args: True)\n',
    )
    text = inject_after_test_def(
        text,
        "test_cancel_stale_opencode_runs_uses_bounded_executor_for_multiple_runs",
        '    monkeypatch.setattr(sched, "_review_run_still_superseded", lambda *_args: True)\n',
    )

    anchor = "\ndef test_inspect_pr_cancels_stale_queued_runs_before_decision(monkeypatch):\n"
    tests = r'''
+
+def test_stale_classifiers_fail_closed_on_truthy_malformed_head(monkeypatch):
+    """A truthy malformed snapshot head cannot turn every active run into stale work."""
+    monkeypatch.setattr(
+        sched,
+        "active_workflow_runs",
+        lambda *_args, **_kwargs: [{"id": 1, "head_sha": "a" * 40, "pull_requests": [{"number": 7}]}],
+    )
+    pr = make_pr(number=7, headRefOid="malformed-but-truthy")
+    assert sched.stale_pr_run_ids("owner/repo", pr) == []
+    assert sched.active_review_run_refs(
+        "owner/repo",
+        "OpenCode Review",
+        pr,
+        run_title="Required OpenCode Review",
+        workflow_aliases=frozenset(sched.OPENCODE_WORKFLOW_NAMES),
+    ) == ([], [])
+
+
+def test_cancel_stale_pr_run_preserves_new_live_head_after_snapshot_race(monkeypatch):
+    """A push after classification cannot make the new current-head run cancellable."""
+    old_head, new_head = "a" * 40, "b" * 40
+    candidate = {
+        "id": 77,
+        "event": "pull_request",
+        "status": "queued",
+        "head_sha": new_head,
+        "pull_requests": [{"number": 7}],
+    }
+    monkeypatch.setattr(sched, "stale_pr_run_ids", lambda *_args, **_kwargs: ["77"])
+    monkeypatch.setattr(sched, "require_github_actions_control_actor", lambda _action: None)
+    calls = []
+
+    def fake_api(path):
+        calls.append(path)
+        if path.endswith("/actions/runs/77"):
+            return candidate
+        return {"state": "open", "draft": False, "head": {"sha": new_head}}
+
+    cancelled = []
+    monkeypatch.setattr(sched, "gh_api_json", fake_api)
+    monkeypatch.setattr(sched, "force_cancel_workflow_runs", lambda *_args: cancelled.append(_args) or {})
+    assert sched.cancel_stale_pr_runs(
+        "owner/repo", make_pr(number=7, headRefOid=old_head), dry_run=False
+    ) == []
+    assert cancelled == []
+    assert calls[-1] == "repos/owner/repo/pulls/7"
+
+
+@pytest.mark.parametrize(
+    "live_pr",
+    [
+        {"state": "open", "draft": True, "head": {"sha": "b" * 40}},
+        {"state": "closed", "draft": False, "head": {"sha": "b" * 40}},
+        {"state": "open", "draft": False, "head": {"sha": "bad"}},
+    ],
+)
+def test_direct_cancellation_fails_closed_on_live_state_or_head_change(monkeypatch, live_pr):
+    """Draft/closed/malformed live authority preserves a cancellation candidate."""
+    run = {
+        "event": "pull_request",
+        "status": "queued",
+        "head_sha": "a" * 40,
+        "pull_requests": [{"number": 7}],
+    }
+
+    def fake_api(path):
+        return run if "/actions/runs/" in path else live_pr
+
+    monkeypatch.setattr(sched, "gh_api_json", fake_api)
+    assert sched._direct_pr_run_still_superseded("owner/repo", 7, "79") is False
+
+
+def test_direct_cancellation_allows_genuine_stale_ready_head(monkeypatch):
+    """Legitimate ready/non-draft supersession remains cancellable."""
+    run = {
+        "event": "pull_request",
+        "status": "in_progress",
+        "head_sha": "a" * 40,
+        "pull_requests": [{"number": 7}],
+    }
+    monkeypatch.setattr(
+        sched,
+        "gh_api_json",
+        lambda path: run
+        if "/actions/runs/" in path
+        else {"state": "open", "draft": False, "head": {"sha": "b" * 40}},
+    )
+    assert sched._direct_pr_run_still_superseded("owner/repo", 7, "80") is True
+
+
+def test_review_dispatch_race_preserves_new_live_head(monkeypatch):
+    """A central dispatch targeting the newly live head survives an old classifier snapshot."""
+    new_head = "c" * 40
+    run = {
+        "event": "repository_dispatch",
+        "status": "queued",
+        "display_title": f"Required OpenCode Review owner/repo#7@{new_head}",
+    }
+    monkeypatch.setattr(
+        sched,
+        "gh_api_json",
+        lambda path: run
+        if "/actions/runs/" in path
+        else {"state": "open", "draft": False, "head": {"sha": new_head}},
+    )
+    assert sched._review_run_still_superseded(
+        "owner/repo", "OpenCode Review", 7, "ContextualWisdomLab/.github", "91"
+    ) is False
+
+
+def test_review_revalidation_fails_closed_on_lookup_error(monkeypatch):
+    """Lookup failure has no destructive cancellation authority."""
+    monkeypatch.setattr(
+        sched, "gh_api_json", lambda _path: (_ for _ in ()).throw(RuntimeError("lookup failed"))
+    )
+    assert sched._review_run_still_superseded(
+        "owner/repo", "OpenCode Review", 7, "ContextualWisdomLab/.github", "92"
+    ) is False
'''.replace("\n+", "\n")
    text = replace_once(text, anchor, tests + anchor, label="race regression insertion")
    TESTS.write_text(text, encoding="utf-8")


def repair_doctoring() -> None:
    """Record the symmetric head/readiness race and exact destructive-boundary contract."""
    text = DOCTORING.read_text(encoding="utf-8")
    text = text.replace("`ContextualWisdomLab/naruon` PR #1528", "`ContextualWisdomLab/naruon#1528`")
    if "## Exact destructive-boundary contract" not in text:
        text += '''
+
+## Exact destructive-boundary contract
+
+The initial `headRefOid` guard is classification only.  Every direct or
+centrally dispatched stale-run candidate is re-fetched immediately before its
+force-cancel POST.  The fresh workflow run must still be active and still
+identify the same target PR/head, and the target PR must still be open,
+non-draft, and expose a valid live head that differs from the candidate.  A
+missing/malformed snapshot, head movement, ready-to-draft transition, close,
+lookup failure, inactive run, missing PR association, or malformed dispatch
+identity fails closed and preserves the run.  Genuine ready/non-draft stale
+runs remain cancellable.  Candidate revalidation/cancellation uses the same
+bounded executor width as the existing scheduler so this safety boundary does
+not reintroduce queue-serialization pressure.
'''.replace("\n+", "\n")
    DOCTORING.write_text(text, encoding="utf-8")


def self_remove() -> None:
    """Remove all temporary PR #1669 repair machinery from the publishable successor."""
    for path in (OLD_HELPER, WORKFLOW, SELF):
        if path.exists():
            path.unlink()


def main() -> int:
    """Apply guarded source/tests/docs repair and remove temporary machinery."""
    repair_source()
    repair_tests()
    repair_doctoring()
    self_remove()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
