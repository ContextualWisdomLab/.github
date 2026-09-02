#!/usr/bin/env python3
"""Align PR #1669 legacy tests with per-candidate live revalidation."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCHEDULER_TESTS = ROOT / "tests/test_pr_review_merge_scheduler.py"
OWNER_TEST = ROOT / "tests/test_pr1669_cancel_stale_opencode_runs.py"
SELF = Path(__file__).resolve()

STALE_PATCH = '    monkeypatch.setattr(sched, "force_cancel_workflow_run_refs", lambda refs: None)\n'

OWNER_BEFORE = '''"""Permanent coverage for PR #1669's stale OpenCode cancellation owner path."""\n\nfrom scripts.ci import pr_review_merge_scheduler as sched\n\n\ndef test_cancel_stale_opencode_runs_uses_revalidated_refs(monkeypatch):\n    """Cancel only the refs returned by the live-state-aware review classifier."""\n    actor_calls: list[str] = []\n    cancelled_refs: list[tuple[str, str]] = []\n    stale_refs = [("owner/repo", "101"), ("owner/repo", "202")]\n\n    monkeypatch.setattr(\n        sched,\n        "require_github_actions_control_actor",\n        lambda action: actor_calls.append(action),\n    )\n    monkeypatch.setattr(\n        sched,\n        "active_opencode_run_refs",\n        lambda _repo, _workflow, _pr: ([], stale_refs),\n    )\n    monkeypatch.setattr(\n        sched,\n        "force_cancel_workflow_run_refs",\n        lambda refs: cancelled_refs.extend(refs),\n    )\n\n    run_ids = sched.cancel_stale_opencode_runs(\n        "owner/repo",\n        "OpenCode Review",\n        {"number": 7, "headRefOid": "a" * 40},\n        dry_run=False,\n    )\n\n    assert actor_calls == ["force-cancel-stale-opencode-review"]\n    assert cancelled_refs == stale_refs\n    assert run_ids == ["101", "202"]\n'''

OWNER_AFTER = '''"""Permanent coverage for PR #1669's stale OpenCode cancellation owner path."""\n\nfrom scripts.ci import pr_review_merge_scheduler as sched\n\n\ndef test_cancel_stale_opencode_runs_uses_revalidated_refs(monkeypatch):\n    """Revalidate every candidate and cancel only refs still proven stale."""\n    actor_calls: list[str] = []\n    revalidated: list[tuple[str, str, int, str, str]] = []\n    cancelled: list[tuple[str, list[str]]] = []\n    stale_refs = [("owner/repo", "101"), ("owner/repo", "202")]\n\n    monkeypatch.setattr(\n        sched,\n        "require_github_actions_control_actor",\n        lambda action: actor_calls.append(action),\n    )\n    monkeypatch.setattr(\n        sched,\n        "active_opencode_run_refs",\n        lambda _repo, _workflow, _pr: ([], stale_refs),\n    )\n\n    def still_superseded(repo, workflow, number, run_repo, run_id):\n        revalidated.append((repo, workflow, number, run_repo, run_id))\n        return True\n\n    monkeypatch.setattr(sched, "_review_run_still_superseded", still_superseded)\n    monkeypatch.setattr(\n        sched,\n        "force_cancel_workflow_runs",\n        lambda repo, run_ids: cancelled.append((repo, list(run_ids))),\n    )\n\n    run_ids = sched.cancel_stale_opencode_runs(\n        "owner/repo",\n        "OpenCode Review",\n        {"number": 7, "headRefOid": "a" * 40},\n        dry_run=False,\n    )\n\n    assert actor_calls == ["force-cancel-stale-opencode-review"]\n    assert sorted(revalidated) == [\n        ("owner/repo", "OpenCode Review", 7, "owner/repo", "101"),\n        ("owner/repo", "OpenCode Review", 7, "owner/repo", "202"),\n    ]\n    assert sorted(cancelled) == [\n        ("owner/repo", ["101"]),\n        ("owner/repo", ["202"]),\n    ]\n    assert sorted(run_ids) == ["101", "202"]\n'''


def main() -> int:
    """Remove stale batch-helper probes after v7 retires that dead production helper."""
    scheduler_tests = SCHEDULER_TESTS.read_text(encoding="utf-8")
    if scheduler_tests.count(STALE_PATCH) != 1:
        raise RuntimeError(
            "expected exactly one stale batch-helper monkeypatch in bounded discovery test; "
            f"found {scheduler_tests.count(STALE_PATCH)}"
        )
    SCHEDULER_TESTS.write_text(
        scheduler_tests.replace(STALE_PATCH, "", 1),
        encoding="utf-8",
    )

    owner_test = OWNER_TEST.read_text(encoding="utf-8")
    if owner_test != OWNER_BEFORE:
        raise RuntimeError("PR1669 owner regression fixture drifted from the exact expected input")
    OWNER_TEST.write_text(OWNER_AFTER, encoding="utf-8")

    SELF.unlink()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
