"""Regression coverage for repository-correct stale-review run revalidation authority."""

from __future__ import annotations

from scripts.ci import pr_review_merge_scheduler as sched


CENTRAL_REPO = "ContextualWisdomLab/.github"
TARGET_REPO = "ContextualWisdomLab/fast-mlsirm"


def test_central_repository_dispatch_run_uses_dispatch_read_authority(monkeypatch) -> None:
    """Central Actions evidence must not be read through a target-repository credential."""
    calls: list[tuple[str, str]] = []
    monkeypatch.setenv("SCHEDULER_REQUIRED_WORKFLOW_REPOSITORY", CENTRAL_REPO)
    monkeypatch.setattr(
        sched,
        "gh_api_json",
        lambda path: calls.append(("target", path)) or (_ for _ in ()).throw(
            AssertionError("target credential must not read central Actions evidence")
        ),
    )
    monkeypatch.setattr(
        sched,
        "gh_api_json_via_dispatch_token",
        lambda path: calls.append(("dispatch", path)) or {"status": "queued"},
    )

    payload = sched._fresh_active_run_for_cancellation(CENTRAL_REPO, "95")

    assert payload == {"status": "queued"}
    assert calls == [("dispatch", f"repos/{CENTRAL_REPO}/actions/runs/95")]


def test_target_repository_run_retains_target_read_authority(monkeypatch) -> None:
    """Direct target Actions evidence must keep the target-repository read boundary."""
    calls: list[tuple[str, str]] = []
    monkeypatch.setenv("SCHEDULER_REQUIRED_WORKFLOW_REPOSITORY", CENTRAL_REPO)
    monkeypatch.setattr(
        sched,
        "gh_api_json",
        lambda path: calls.append(("target", path)) or {"status": "in_progress"},
    )
    monkeypatch.setattr(
        sched,
        "gh_api_json_via_dispatch_token",
        lambda path: calls.append(("dispatch", path)) or (_ for _ in ()).throw(
            AssertionError("dispatch credential must not read target Actions evidence")
        ),
    )

    payload = sched._fresh_active_run_for_cancellation(TARGET_REPO, "96")

    assert payload == {"status": "in_progress"}
    assert calls == [("target", f"repos/{TARGET_REPO}/actions/runs/96")]


def test_unconfigured_central_repository_fails_closed_to_target_authority(monkeypatch) -> None:
    """Without a configured central owner, the helper must not invent dispatch authority."""
    calls: list[tuple[str, str]] = []
    monkeypatch.delenv("SCHEDULER_REQUIRED_WORKFLOW_REPOSITORY", raising=False)
    monkeypatch.setattr(
        sched,
        "gh_api_json",
        lambda path: calls.append(("target", path)) or {"status": "queued"},
    )
    monkeypatch.setattr(
        sched,
        "gh_api_json_via_dispatch_token",
        lambda path: calls.append(("dispatch", path)) or {"status": "queued"},
    )

    payload = sched._fresh_active_run_for_cancellation(TARGET_REPO, "97")

    assert payload == {"status": "queued"}
    assert calls == [("target", f"repos/{TARGET_REPO}/actions/runs/97")]
