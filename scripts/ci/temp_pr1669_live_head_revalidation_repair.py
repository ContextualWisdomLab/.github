#!/usr/bin/env python3
"""Repair PR #1669 so every destructive stale-run cancellation revalidates live head state."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "scripts/ci/pr_review_merge_scheduler.py"
TESTS = ROOT / "tests/test_pr_review_merge_scheduler.py"
DOCTORING = ROOT / "docs/doctoring/scheduler-stale-headrefoid-cancellation.md"
WORKFLOW = ROOT / ".github/workflows/_temp_pr1669_live_head_revalidation_repair.yml"
SELF = Path(__file__).resolve()


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    """Replace exactly one guarded source fragment."""
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one source anchor, found {count}")
    return text.replace(old, new, 1)


def repair_source() -> None:
    """Add fail-safe per-candidate live-head revalidation before force cancellation."""
    text = SOURCE.read_text(encoding="utf-8")
    text = text.replace(
        "docs/doctoring/2026-09-02-strix-current-head-cancellation.md",
        "docs/doctoring/scheduler-stale-headrefoid-cancellation.md",
    )
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
    new = '''def _fresh_open_pr_head_for_cancellation(repo: str, number: int) -> str:
    """Return the freshly fetched head SHA for one still-open pull request.

    Destructive workflow cancellation must not trust the scheduler's earlier PR
    snapshot: a push can move the head after classification.  Any unavailable,
    closed, or malformed live PR fails closed by raising to the caller, which
    preserves the candidate run.
    """
    payload = gh_api_json(f"repos/{repo}/pulls/{number}")
    if not isinstance(payload, dict) or str(payload.get("state") or "").lower() != "open":
        raise ValueError(f"PR #{number} in {repo} is not a resolvable open pull request")
    return validate_git_sha(((payload.get("head") or {}).get("sha"))).lower()


def _fresh_active_run_for_cancellation(run_repo: str, run_id: str) -> dict[str, Any]:
    """Return fresh active workflow-run evidence immediately before cancellation."""
    payload = gh_api_json(f"repos/{run_repo}/actions/runs/{run_id}")
    if not isinstance(payload, dict) or str(payload.get("status") or "").lower() not in {
        "queued",
        "in_progress",
    }:
        raise ValueError(f"workflow run {run_repo}#{run_id} is not active")
    return payload


def _direct_pr_run_still_superseded(repo: str, number: int, run_id: str) -> bool:
    """Return whether a direct PR-associated run is still older than the fresh PR head."""
    try:
        run_data = _fresh_active_run_for_cancellation(repo, run_id)
        if run_data.get("event") == "repository_dispatch" or not workflow_run_mentions_pr(
            run_data, number
        ):
            raise ValueError("workflow run no longer has direct pull-request authority")
        run_head = validate_git_sha(str(run_data.get("head_sha") or "")).lower()
        # Keep the live PR read last so the destructive POST follows the newest
        # available authority evidence rather than the classification snapshot.
        live_head = _fresh_open_pr_head_for_cancellation(repo, number)
    except (KeyError, RuntimeError, TypeError, ValueError) as exc:
        print(
            f"::warning::Preserving workflow run {run_id} in {repo}: "
            f"live stale-run revalidation failed closed ({exc})."
        )
        return False
    return run_head != live_head


def _review_run_target_head(
    run_data: dict[str, Any],
    repo: str,
    workflow: str,
    number: int,
) -> str:
    """Return the target PR head encoded by a direct or central review run."""
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
    """Return whether a direct or dispatched review run is stale against the fresh PR head."""
    try:
        run_data = _fresh_active_run_for_cancellation(run_repo, run_id)
        run_head = _review_run_target_head(run_data, repo, workflow, number)
        # Read target PR authority last; repository_dispatch ``head_sha`` is the
        # control-plane default branch and therefore cannot replace this check.
        live_head = _fresh_open_pr_head_for_cancellation(repo, number)
    except (KeyError, RuntimeError, TypeError, ValueError) as exc:
        print(
            f"::warning::Preserving review run {run_repo}#{run_id}: "
            f"live stale-run revalidation failed closed ({exc})."
        )
        return False
    return run_head != live_head


def cancel_stale_pr_runs(repo: str, pr: dict[str, Any], *, dry_run: bool) -> list[str]:
    """Force-cancel only candidates still proven stale against a freshly fetched PR head."""
    if dry_run:
        return []
    require_github_actions_control_actor("force-cancel-stale-pr-runs")
    number = int(pr["number"])
    cancelled: list[str] = []
    for run_id in stale_pr_run_ids(repo, pr):
        if not _direct_pr_run_still_superseded(repo, number, run_id):
            continue
        force_cancel_workflow_runs(repo, [run_id])
        cancelled.append(run_id)
    return cancelled


def cancel_stale_opencode_runs(repo: str, workflow: str, pr: dict[str, Any], *, dry_run: bool) -> list[str]:
    """Force-cancel only review candidates still stale against a freshly fetched PR head."""
    if dry_run:
        return []
    require_github_actions_control_actor("force-cancel-stale-opencode-review")
    number = int(pr["number"])
    _, stale_refs = active_opencode_run_refs(repo, workflow, pr)
    cancelled: list[str] = []
    for run_repo, run_id in stale_refs:
        if not _review_run_still_superseded(repo, workflow, number, run_repo, run_id):
            continue
        force_cancel_workflow_runs(run_repo, [run_id])
        cancelled.append(run_id)
    return cancelled
'''
    text = replace_once(text, old, new, label="destructive cancellation block")
    SOURCE.write_text(text, encoding="utf-8")


def repair_tests() -> None:
    """Add regressions for direct and repository-dispatch head movement after classification."""
    text = TESTS.read_text(encoding="utf-8")
    text = text.replace(
        "docs/doctoring/2026-09-02-strix-current-head-cancellation.md",
        "docs/doctoring/scheduler-stale-headrefoid-cancellation.md",
    )
    anchor = "\ndef test_inspect_pr_cancels_stale_queued_runs_before_decision(monkeypatch):\n"
    tests = r'''

def test_cancel_stale_pr_runs_preserves_new_live_head_run_after_snapshot_race(monkeypatch):
    """A push after classification cannot make the new current-head run cancellable."""
    old_head = "a" * 40
    new_head = "b" * 40
    candidate = {
        "id": 77,
        "name": "Strix Security Scan",
        "event": "pull_request",
        "status": "queued",
        "head_sha": new_head,
        "pull_requests": [{"number": 7}],
    }
    monkeypatch.setattr(sched, "active_workflow_runs", lambda *_args, **_kwargs: [candidate])
    monkeypatch.setattr(sched, "require_github_actions_control_actor", lambda _action: None)
    calls = []

    def fake_api(path):
        calls.append(path)
        if path == "repos/owner/repo/actions/runs/77":
            return candidate
        if path == "repos/owner/repo/pulls/7":
            return {"state": "open", "head": {"sha": new_head}}
        raise AssertionError(path)

    cancelled = []
    monkeypatch.setattr(sched, "gh_api_json", fake_api)
    monkeypatch.setattr(
        sched,
        "force_cancel_workflow_runs",
        lambda repo, run_ids: cancelled.extend((repo, run_id) for run_id in run_ids) or {},
    )

    assert sched.cancel_stale_pr_runs(
        "owner/repo", make_pr(number=7, headRefOid=old_head), dry_run=False
    ) == []
    assert cancelled == []
    assert calls[-1] == "repos/owner/repo/pulls/7"


def test_cancel_stale_pr_runs_cancels_only_after_fresh_stale_proof(monkeypatch):
    """A genuinely old direct PR run remains cancellable after fresh authority proof."""
    old_head = "a" * 40
    live_head = "b" * 40
    candidate = {
        "id": 78,
        "name": "Strix Security Scan",
        "event": "pull_request",
        "status": "in_progress",
        "head_sha": old_head,
        "pull_requests": [{"number": 7}],
    }
    monkeypatch.setattr(sched, "active_workflow_runs", lambda *_args, **_kwargs: [candidate])
    monkeypatch.setattr(sched, "require_github_actions_control_actor", lambda _action: None)

    def fake_api(path):
        if path == "repos/owner/repo/actions/runs/78":
            return candidate
        if path == "repos/owner/repo/pulls/7":
            return {"state": "open", "head": {"sha": live_head}}
        raise AssertionError(path)

    cancelled = []
    monkeypatch.setattr(sched, "gh_api_json", fake_api)
    monkeypatch.setattr(
        sched,
        "force_cancel_workflow_runs",
        lambda repo, run_ids: cancelled.extend((repo, run_id) for run_id in run_ids) or {},
    )

    assert sched.cancel_stale_pr_runs(
        "owner/repo", make_pr(number=7, headRefOid=live_head), dry_run=False
    ) == ["78"]
    assert cancelled == [("owner/repo", "78")]


def test_direct_stale_revalidation_fails_closed_for_untrusted_or_unavailable_evidence(monkeypatch):
    """Non-direct, inactive, closed, malformed, and unavailable evidence preserves a run."""
    head = "b" * 40
    base = {
        "id": 79,
        "status": "queued",
        "head_sha": "a" * 40,
        "pull_requests": [{"number": 7}],
    }
    cases = [
        ({**base, "event": "repository_dispatch"}, {"state": "open", "head": {"sha": head}}),
        ({**base, "event": "pull_request", "status": "completed"}, {"state": "open", "head": {"sha": head}}),
        ({**base, "event": "pull_request", "pull_requests": []}, {"state": "open", "head": {"sha": head}}),
        ({**base, "event": "pull_request", "head_sha": "bad"}, {"state": "open", "head": {"sha": head}}),
        ({**base, "event": "pull_request"}, {"state": "closed", "head": {"sha": head}}),
        ({**base, "event": "pull_request"}, {"state": "open", "head": {"sha": "bad"}}),
    ]
    for run_data, pr_data in cases:
        monkeypatch.setattr(
            sched,
            "gh_api_json",
            lambda path, run_data=run_data, pr_data=pr_data: (
                run_data if "/actions/runs/" in path else pr_data
            ),
        )
        assert sched._direct_pr_run_still_superseded("owner/repo", 7, "79") is False

    monkeypatch.setattr(
        sched, "gh_api_json", lambda _path: (_ for _ in ()).throw(RuntimeError("read failed"))
    )
    assert sched._direct_pr_run_still_superseded("owner/repo", 7, "79") is False


def test_cancel_stale_opencode_preserves_dispatched_new_head_after_snapshot_race(monkeypatch):
    """A newly dispatched review is preserved when the target PR moved after classification."""
    new_head = "c" * 40
    run = {
        "id": 91,
        "name": "OpenCode Review",
        "event": "repository_dispatch",
        "status": "queued",
        "display_title": f"Required OpenCode Review owner/repo#7@{new_head}",
    }
    monkeypatch.setattr(sched, "require_github_actions_control_actor", lambda _action: None)
    monkeypatch.setattr(
        sched,
        "active_opencode_run_refs",
        lambda *_args, **_kwargs: ([], [("ContextualWisdomLab/.github", "91")]),
    )

    def fake_api(path):
        if path == "repos/ContextualWisdomLab/.github/actions/runs/91":
            return run
        if path == "repos/owner/repo/pulls/7":
            return {"state": "open", "head": {"sha": new_head}}
        raise AssertionError(path)

    cancelled = []
    monkeypatch.setattr(sched, "gh_api_json", fake_api)
    monkeypatch.setattr(
        sched,
        "force_cancel_workflow_runs",
        lambda repo, run_ids: cancelled.extend((repo, run_id) for run_id in run_ids) or {},
    )

    assert sched.cancel_stale_opencode_runs(
        "owner/repo", "OpenCode Review", make_pr(number=7, headRefOid="a" * 40), dry_run=False
    ) == []
    assert cancelled == []


def test_cancel_stale_opencode_cancels_genuinely_old_dispatched_review(monkeypatch):
    """A central repository_dispatch review remains cancellable when fresh PR head differs."""
    old_head = "a" * 40
    live_head = "b" * 40
    run = {
        "id": 92,
        "name": "OpenCode Review",
        "event": "repository_dispatch",
        "status": "in_progress",
        "display_title": f"OpenCode Review owner/repo#7@{old_head}",
    }
    monkeypatch.setattr(sched, "require_github_actions_control_actor", lambda _action: None)
    monkeypatch.setattr(
        sched,
        "active_opencode_run_refs",
        lambda *_args, **_kwargs: ([], [("ContextualWisdomLab/.github", "92")]),
    )

    def fake_api(path):
        if path == "repos/ContextualWisdomLab/.github/actions/runs/92":
            return run
        if path == "repos/owner/repo/pulls/7":
            return {"state": "open", "head": {"sha": live_head}}
        raise AssertionError(path)

    cancelled = []
    monkeypatch.setattr(sched, "gh_api_json", fake_api)
    monkeypatch.setattr(
        sched,
        "force_cancel_workflow_runs",
        lambda repo, run_ids: cancelled.extend((repo, run_id) for run_id in run_ids) or {},
    )

    assert sched.cancel_stale_opencode_runs(
        "owner/repo", "OpenCode Review", make_pr(number=7, headRefOid=live_head), dry_run=False
    ) == ["92"]
    assert cancelled == [("ContextualWisdomLab/.github", "92")]


def test_review_revalidation_handles_direct_and_malformed_dispatch_evidence(monkeypatch):
    """Direct review runs revalidate; malformed dispatch identity fails closed."""
    live_head = "b" * 40
    direct = {
        "id": 93,
        "event": "pull_request_target",
        "status": "queued",
        "head_sha": "a" * 40,
        "pull_requests": [{"number": 7}],
    }
    malformed_dispatch = {
        "id": 94,
        "event": "repository_dispatch",
        "status": "queued",
        "display_title": "untrusted title",
    }

    def direct_api(path):
        if path.endswith("/actions/runs/93"):
            return direct
        return {"state": "open", "head": {"sha": live_head}}

    monkeypatch.setattr(sched, "gh_api_json", direct_api)
    assert sched._review_run_still_superseded(
        "owner/repo", "OpenCode Review", 7, "owner/repo", "93"
    ) is True

    monkeypatch.setattr(
        sched,
        "gh_api_json",
        lambda path: malformed_dispatch if path.endswith("/actions/runs/94") else {"state": "open", "head": {"sha": live_head}},
    )
    assert sched._review_run_still_superseded(
        "owner/repo", "OpenCode Review", 7, "ContextualWisdomLab/.github", "94"
    ) is False


def test_review_target_head_rejects_direct_run_without_pr_association():
    """A direct review run without live target-PR association has no cancellation authority."""
    with pytest.raises(ValueError, match="no longer belongs"):
        sched._review_run_target_head(
            {"event": "pull_request", "head_sha": "a" * 40, "pull_requests": []},
            "owner/repo",
            "OpenCode Review",
            7,
        )
'''
    text = replace_once(text, anchor, tests + anchor, label="test insertion anchor")
    TESTS.write_text(text, encoding="utf-8")


def repair_doctoring() -> None:
    """Correct cross-repository references and record the residual push-race repair."""
    text = DOCTORING.read_text(encoding="utf-8")
    text = text.replace("`ContextualWisdomLab/naruon` PR #1528", "`ContextualWisdomLab/naruon#1528`")
    repair = '''## Repair

`stale_pr_run_ids()` and `active_review_run_refs()` first fail safe when the
classification snapshot has no `headRefOid`. A current-head review then found
a second member of the same TOCTOU class: even a valid snapshot can become
stale when a push lands after classification but before the destructive
`force-cancel` POST.

The destructive boundary now treats classifier output only as a *candidate*.
Immediately before each cancellation it re-fetches the exact run and the
open target PR. Direct PR-associated runs must still be active, still belong
to the same PR, and carry a valid run head different from the freshly fetched
PR head. Central `repository_dispatch` OpenCode runs must still be active and
must carry a trusted `Required OpenCode Review owner/repo#number@sha` (or
accepted workflow-alias) title whose target SHA differs from the freshly
fetched PR head. The target PR read is intentionally the last authority read
before cancellation; unavailable, closed, malformed, reassociated, already
completed, or now-current evidence preserves the run. This mirrors the
fail-safe final revalidation already used by
`scripts/ci/revalidate_queue_cancellation.sh` rather than assuming an earlier
snapshot remains authoritative.
'''
    start = text.index("## Repair\n")
    end = text.index("\n## Evidence\n", start)
    text = text[:start] + repair.rstrip() + text[end:]
    evidence_marker = "## Evidence\n\n"
    addition = (
        "The current-head review regression additionally moves a PR from an earlier "
        "snapshot SHA to the candidate run SHA between classification and cancellation. "
        "Both direct pull-request runs and central `repository_dispatch` review runs are "
        "preserved in that race, while genuinely older runs remain cancellable after the "
        "fresh proof. Malformed, inactive, closed, unassociated, and unreadable evidence "
        "also fails closed.\n\n"
    )
    text = replace_once(text, evidence_marker, evidence_marker + addition, label="doctoring evidence")
    DOCTORING.write_text(text, encoding="utf-8")


def self_remove() -> None:
    """Remove temporary repair machinery from the publishable successor tree."""
    WORKFLOW.unlink()
    SELF.unlink()


def main() -> int:
    """Apply guarded repairs and remove temporary machinery after source mutation."""
    repair_source()
    repair_tests()
    repair_doctoring()
    self_remove()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
