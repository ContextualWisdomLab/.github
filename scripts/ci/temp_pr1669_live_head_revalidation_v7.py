#!/usr/bin/env python3
"""Refresh legacy scheduler fixtures and retire dead pre-revalidation cancellation code."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TESTS = ROOT / "tests/test_pr_review_merge_scheduler.py"
SCHEDULER = ROOT / "scripts/ci/pr_review_merge_scheduler.py"
SELF = Path(__file__).resolve()
PATCH = '    monkeypatch.setattr(sched, "_review_run_still_superseded", lambda *_args: True)\n'

COVERAGE_TESTS = r'''


def test_pr1669_direct_revalidation_fails_closed_when_live_authority_is_unreadable(monkeypatch, capsys):
    """Direct cancellation must preserve the candidate when fresh authority cannot be read."""
    def fail_api(_path):
        raise RuntimeError("simulated live-authority outage")

    monkeypatch.setattr(sched, "gh_api_json", fail_api)
    assert sched._direct_pr_run_still_superseded("owner/repo", 7, "94") is False
    assert "Preserving workflow run 94 in owner/repo" in capsys.readouterr().out


def test_pr1669_review_revalidation_fails_closed_when_live_authority_is_unreadable(monkeypatch, capsys):
    """Review cancellation must preserve the candidate when fresh authority cannot be read."""
    def fail_api(_path):
        raise RuntimeError("simulated live-authority outage")

    monkeypatch.setattr(sched, "gh_api_json", fail_api)
    assert sched._review_run_still_superseded(
        "owner/repo", "OpenCode Review", 7, "ContextualWisdomLab/.github", "95"
    ) is False
    assert "Preserving review run ContextualWisdomLab/.github#95" in capsys.readouterr().out


def test_pr1669_revalidated_review_refs_cover_empty_and_parallel_mixed_candidates(monkeypatch):
    """The review helper preserves uncertain refs and cancels only concurrently proven stale refs."""
    pr = make_pr(number=7, headRefOid="b" * 40)
    assert sched._cancel_revalidated_review_run_refs(
        "owner/repo", "OpenCode Review", pr, []
    ) == ([], [])

    stale = {"96": True, "97": False}
    monkeypatch.setattr(
        sched,
        "_review_run_still_superseded",
        lambda _repo, _workflow, _number, _run_repo, run_id: stale[run_id],
    )
    cancelled = []
    monkeypatch.setattr(
        sched,
        "force_cancel_workflow_runs",
        lambda repo, run_ids: cancelled.append((repo, list(run_ids))),
    )
    preserved, cancelled_refs = sched._cancel_revalidated_review_run_refs(
        "owner/repo",
        "OpenCode Review",
        pr,
        [
            ("ContextualWisdomLab/.github", "96"),
            ("ContextualWisdomLab/.github", "97"),
        ],
    )
    assert preserved == [("ContextualWisdomLab/.github", "97")]
    assert cancelled_refs == [("ContextualWisdomLab/.github", "96")]
    assert cancelled == [("ContextualWisdomLab/.github", ["96"])]


def test_pr1669_parallel_direct_candidates_preserve_live_and_cancel_only_stale(monkeypatch):
    """Parallel direct-run cleanup must keep a revalidated current-head candidate."""
    monkeypatch.setattr(sched, "require_github_actions_control_actor", lambda _action: None)
    monkeypatch.setattr(sched, "stale_pr_run_ids", lambda *_args, **_kwargs: ["94", "95"])
    monkeypatch.setattr(
        sched,
        "_direct_pr_run_still_superseded",
        lambda _repo, _number, run_id: run_id == "94",
    )
    cancelled = []
    monkeypatch.setattr(
        sched,
        "force_cancel_workflow_runs",
        lambda repo, run_ids: cancelled.append((repo, list(run_ids))),
    )
    assert sched.cancel_stale_pr_runs("owner/repo", make_pr(number=7), dry_run=False) == ["94"]
    assert cancelled == [("owner/repo", ["94"])]


def test_pr1669_parallel_opencode_candidates_preserve_live_and_cancel_only_stale(monkeypatch):
    """Parallel OpenCode cleanup must keep a revalidated current-head review candidate."""
    monkeypatch.setattr(sched, "require_github_actions_control_actor", lambda _action: None)
    monkeypatch.setattr(
        sched,
        "active_opencode_run_refs",
        lambda *_args, **_kwargs: (
            [],
            [
                ("ContextualWisdomLab/.github", "96"),
                ("ContextualWisdomLab/.github", "97"),
            ],
        ),
    )
    monkeypatch.setattr(
        sched,
        "_review_run_still_superseded",
        lambda _repo, _workflow, _number, _run_repo, run_id: run_id == "96",
    )
    cancelled = []
    monkeypatch.setattr(
        sched,
        "force_cancel_workflow_runs",
        lambda repo, run_ids: cancelled.append((repo, list(run_ids))),
    )
    assert sched.cancel_stale_opencode_runs(
        "owner/repo", "OpenCode Review", make_pr(number=7), dry_run=False
    ) == ["96"]
    assert cancelled == [("ContextualWisdomLab/.github", ["96"])]
'''


def insert_after_signature(text: str, signature: str) -> str:
    """Insert one compatibility monkeypatch after one exact legacy test signature."""
    anchor = signature + "\n"
    if anchor + PATCH in text:
        return text
    if text.count(anchor) != 1:
        raise RuntimeError(f"expected exactly one legacy test signature: {signature}")
    return text.replace(anchor, anchor + PATCH, 1)


def retire_dead_batch_helper() -> None:
    """Delete the old batch helper after v6 removes its final production callers."""
    text = SCHEDULER.read_text(encoding="utf-8")
    name = "force_cancel_workflow_run_refs("
    if text.count(name) != 1:
        raise RuntimeError(
            "force_cancel_workflow_run_refs must have exactly its definition and no live callers "
            f"after v6; observed {text.count(name)} references"
        )
    block = '''def force_cancel_workflow_run_refs(run_refs: Sequence[tuple[str, str]]) -> None:\n    """Force-cancel repository-qualified runs while retaining bounded batches."""\n    runs_by_repo: dict[str, list[str]] = {}\n    for run_repo, run_id in run_refs:\n        runs_by_repo.setdefault(run_repo, []).append(run_id)\n    for run_repo, run_ids in runs_by_repo.items():\n        force_cancel_workflow_runs(run_repo, run_ids)\n\n\n'''
    if text.count(block) != 1:
        raise RuntimeError("dead batch helper body drifted")
    SCHEDULER.write_text(text.replace(block, "", 1), encoding="utf-8")


def main() -> int:
    """Preserve legacy intent, add boundary coverage, and remove dead batch cancellation code."""
    text = TESTS.read_text(encoding="utf-8")
    text = insert_after_signature(
        text,
        "def test_dispatch_opencode_review_force_cancels_same_pr_old_head_runs(monkeypatch):",
    )
    text = insert_after_signature(
        text,
        "def test_dispatch_strix_cancels_stale_central_run_and_keeps_current(monkeypatch, capsys):",
    )
    marker = "def test_pr1669_direct_revalidation_fails_closed_when_live_authority_is_unreadable"
    if marker not in text:
        text += COVERAGE_TESTS
    # v6's RED fixtures still observe the legacy helper to prove that the repaired dispatches
    # never use it. Allow those test-only monkeypatches to synthesize the now-retired symbol.
    old = '''        "force_cancel_workflow_run_refs",\n        lambda refs: batch_cancellations.append(list(refs)),\n    )'''
    new = '''        "force_cancel_workflow_run_refs",\n        lambda refs: batch_cancellations.append(list(refs)),\n        raising=False,\n    )'''
    if text.count(old) != 2:
        raise RuntimeError(f"expected two legacy batch-helper test probes, found {text.count(old)}")
    text = text.replace(old, new)
    TESTS.write_text(text, encoding="utf-8")
    retire_dead_batch_helper()
    SELF.unlink()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
