"""Credential-bound regressions for PR #1669 stale-run revalidation."""

from __future__ import annotations

from scripts.ci import pr_review_merge_scheduler as scheduler


def test_central_run_revalidation_uses_dispatch_credential(monkeypatch) -> None:
    """Central repository_dispatch run reads must not use a target-only read token."""
    central_repo = "ContextualWisdomLab/.github"
    monkeypatch.setenv("SCHEDULER_REQUIRED_WORKFLOW_REPOSITORY", central_repo)
    seen: list[tuple[str, str]] = []

    def target_read(path: str):
        seen.append(("target", path))
        raise AssertionError("target credential must not read central Actions runs")

    def dispatch_read(path: str):
        seen.append(("dispatch", path))
        return {"id": 321, "status": "queued", "event": "repository_dispatch"}

    monkeypatch.setattr(scheduler, "gh_api_json", target_read)
    monkeypatch.setattr(scheduler, "gh_api_json_via_dispatch_token", dispatch_read)

    payload = scheduler._fresh_active_run_for_cancellation(central_repo, "321")

    assert payload["id"] == 321
    assert seen == [("dispatch", f"repos/{central_repo}/actions/runs/321")]


def test_target_run_revalidation_keeps_target_read_credential(monkeypatch) -> None:
    """Direct target-repository run reads retain the target read credential boundary."""
    central_repo = "ContextualWisdomLab/.github"
    target_repo = "ContextualWisdomLab/example"
    monkeypatch.setenv("SCHEDULER_REQUIRED_WORKFLOW_REPOSITORY", central_repo)
    seen: list[tuple[str, str]] = []

    def target_read(path: str):
        seen.append(("target", path))
        return {"id": 654, "status": "in_progress", "event": "pull_request_target"}

    def dispatch_read(path: str):
        seen.append(("dispatch", path))
        raise AssertionError("dispatch credential must not read target Actions runs")

    monkeypatch.setattr(scheduler, "gh_api_json", target_read)
    monkeypatch.setattr(scheduler, "gh_api_json_via_dispatch_token", dispatch_read)

    payload = scheduler._fresh_active_run_for_cancellation(target_repo, "654")

    assert payload["id"] == 654
    assert seen == [("target", f"repos/{target_repo}/actions/runs/654")]
