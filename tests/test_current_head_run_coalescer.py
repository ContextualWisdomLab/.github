"""Regression tests for exact-current-head GitHub Actions run coalescing."""

from __future__ import annotations

import importlib.util
import json
import runpy
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "ci" / "current_head_run_coalescer.py"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "current-head-run-coalescer.yml"


def load_module():
    """Load the production coalescer only after proving the file exists."""
    assert SCRIPT.is_file(), "current-head duplicate coalescer is not implemented"
    spec = importlib.util.spec_from_file_location("current_head_run_coalescer", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_record(
    run_id: int,
    workflow_id: int,
    *,
    status: str = "queued",
    head_sha: str = "a" * 40,
    branch: str = "feature/current",
    repository: str = "ContextualWisdomLab/.github",
    event: str = "pull_request",
) -> dict[str, object]:
    """Return one bounded Actions run fixture."""
    return {
        "id": run_id,
        "workflow_id": workflow_id,
        "status": status,
        "head_sha": head_sha,
        "head_branch": branch,
        "event": event,
        "head_repository": {"full_name": repository},
    }


def live_pr(*, state: str = "open", head_sha: str = "a" * 40) -> dict[str, object]:
    """Return the exact live PR identity used by revalidation tests."""
    return {
        "state": state,
        "head": {
            "sha": head_sha,
            "ref": "feature/current",
            "repo": {"full_name": "ContextualWisdomLab/.github"},
        },
    }


def test_select_duplicate_queued_runs_keeps_one_authoritative_run_per_workflow() -> None:
    """Older queued duplicates are retired while one exact-head run survives."""
    module = load_module()
    runs = [
        run_record(100, 10),
        run_record(101, 10),
        run_record(102, 10),
        run_record(200, 20),
        run_record(201, 20),
    ]
    assert module.select_duplicate_queued_run_ids(
        runs,
        repository="ContextualWisdomLab/.github",
        branch="feature/current",
        head_sha="a" * 40,
    ) == [100, 101, 200]


def test_in_progress_run_is_never_selected_and_makes_queued_siblings_redundant() -> None:
    """A running authoritative workflow is preserved and queued duplicates retire."""
    module = load_module()
    runs = [
        run_record(100, 10, status="in_progress"),
        run_record(101, 10),
        run_record(102, 10),
    ]
    assert module.select_duplicate_queued_run_ids(
        runs,
        repository="ContextualWisdomLab/.github",
        branch="feature/current",
        head_sha="a" * 40,
    ) == [101, 102]


def test_other_identities_and_malformed_runs_are_not_coalesced() -> None:
    """Coalescing stays inside one exact current-head pull-request workflow identity."""
    module = load_module()
    runs = [
        run_record(100, 10),
        run_record(101, 11),
        run_record(102, 10, head_sha="b" * 40),
        run_record(103, 10, branch="other"),
        run_record(104, 10, repository="ContextualWisdomLab/TEPP"),
        run_record(105, 10, event="push"),
        run_record(0, 10),
        run_record(106, 0),
        {**run_record(107, 10), "status": "completed"},
    ]
    assert module.select_duplicate_queued_run_ids(
        runs,
        repository="ContextualWisdomLab/.github",
        branch="feature/current",
        head_sha="a" * 40,
    ) == []
    assert module._positive_int(True) is None
    assert module._positive_int("1") is None
    assert module._positive_int(0) is None
    assert module._positive_int(1) == 1


def test_revalidation_requires_a_distinct_newer_or_running_sibling() -> None:
    """The sole or newest queued current-head run is never cancelled."""
    module = load_module()
    candidate = run_record(100, 10)
    for active in ([candidate], [candidate, run_record(99, 10)]):
        with pytest.raises(module.CoalescingRefused, match="authoritative sibling"):
            module.validate_candidate_against_live_state(
                candidate,
                live_pr=live_pr(),
                active_same_head_runs=active,
            )
    module.validate_candidate_against_live_state(
        candidate,
        live_pr=live_pr(),
        active_same_head_runs=[candidate, run_record(101, 10)],
    )
    module.validate_candidate_against_live_state(
        candidate,
        live_pr=live_pr(),
        active_same_head_runs=[candidate, run_record(99, 10, status="in_progress")],
    )


def test_revalidation_fails_closed_for_status_state_identity_and_event_changes() -> None:
    """Every live identity transition preserves the candidate before mutation."""
    module = load_module()
    candidate = run_record(100, 10)
    sibling = run_record(101, 10)
    with pytest.raises(module.CoalescingRefused, match="no longer queued"):
        module.validate_candidate_against_live_state(
            run_record(100, 10, status="in_progress"),
            live_pr=live_pr(),
            active_same_head_runs=[sibling],
        )
    with pytest.raises(module.CoalescingRefused, match="no longer open"):
        module.validate_candidate_against_live_state(
            candidate, live_pr=live_pr(state="closed"), active_same_head_runs=[sibling]
        )
    with pytest.raises(module.CoalescingRefused, match="head moved"):
        module.validate_candidate_against_live_state(
            candidate, live_pr=live_pr(head_sha="b" * 40), active_same_head_runs=[sibling]
        )
    malformed = run_record(0, 10)
    with pytest.raises(module.CoalescingRefused, match="identity is malformed"):
        module.validate_candidate_against_live_state(
            malformed, live_pr=live_pr(), active_same_head_runs=[sibling]
        )
    wrong_event = run_record(100, 10, event="push")
    with pytest.raises(module.CoalescingRefused, match="not a pull-request"):
        module.validate_candidate_against_live_state(
            wrong_event, live_pr=live_pr(), active_same_head_runs=[sibling]
        )


def test_revalidation_ignores_non_authoritative_sibling_shapes() -> None:
    """Different workflow or malformed sibling records cannot authorize cancellation."""
    module = load_module()
    candidate = run_record(100, 10)
    siblings = [
        run_record(101, 11),
        run_record(102, 10, branch="other"),
        run_record(0, 10),
        candidate,
    ]
    with pytest.raises(module.CoalescingRefused, match="authoritative sibling"):
        module.validate_candidate_against_live_state(
            candidate, live_pr=live_pr(), active_same_head_runs=siblings
        )


def test_run_json_uses_token_decodes_success_and_bounds_failure(monkeypatch) -> None:
    """GitHub transport is token-bound, JSON-only, and bounded on command failure."""
    module = load_module()
    monkeypatch.delenv("GH_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="GH_TOKEN"):
        module._run_json(["gh", "api", "repos/o/r"])

    monkeypatch.setenv("GH_TOKEN", "token")
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout='{"ok":true}', stderr=""),
    )
    assert module._run_json(["gh", "api", "repos/o/r"]) == {"ok": True}

    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="", stderr="x" * 700),
    )
    with pytest.raises(RuntimeError) as exc_info:
        module._run_json(["gh", "api", "repos/o/r"])
    assert len(str(exc_info.value)) == 600


def test_fetch_helpers_fail_closed_and_paginate(monkeypatch) -> None:
    """PR/run fetches reject malformed payloads and Actions pagination is complete."""
    module = load_module()
    monkeypatch.setattr(module, "_run_json", lambda _args: {"state": "open"})
    assert module._fetch_pr("o/r", 1) == {"state": "open"}
    assert module._fetch_run("o/r", 2) == {"state": "open"}

    monkeypatch.setattr(module, "_run_json", lambda _args: [])
    with pytest.raises(RuntimeError, match="pull-request evidence"):
        module._fetch_pr("o/r", 1)
    with pytest.raises(RuntimeError, match="run identity evidence"):
        module._fetch_run("o/r", 1)

    hundred = [run_record(index + 1, 10) for index in range(100)]
    calls: list[list[str]] = []

    def pages(args):
        calls.append(list(args))
        status = next(item.split("=", 1)[1] for item in args if item.startswith("status="))
        page = int(next(item.split("=", 1)[1] for item in args if item.startswith("page=")))
        if status == "queued" and page == 1:
            return {"workflow_runs": hundred}
        if status == "queued" and page == 2:
            return {"workflow_runs": [run_record(101, 10)]}
        return {"workflow_runs": []}

    monkeypatch.setattr(module, "_run_json", pages)
    assert len(module._active_runs("o/r", "a" * 40)) == 101
    assert any("page=2" in call for call in calls)

    monkeypatch.setattr(module, "_run_json", lambda _args: {"workflow_runs": "bad"})
    with pytest.raises(RuntimeError, match="malformed Actions"):
        module._active_runs("o/r", "a" * 40)


def test_cancel_run_uses_ordinary_endpoint_and_surfaces_failure(monkeypatch) -> None:
    """Only GitHub's ordinary cancellation endpoint is used for queued duplicates."""
    module = load_module()
    calls: list[list[str]] = []

    def success(args, **_kwargs):
        calls.append(list(args))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(module.subprocess, "run", success)
    module._cancel_run("o/r", 123)
    assert calls == [["gh", "api", "-X", "POST", "repos/o/r/actions/runs/123/cancel"]]

    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="failed", stderr=""),
    )
    with pytest.raises(RuntimeError, match="failed"):
        module._cancel_run("o/r", 123)


def test_coalesce_validates_inputs_rechecks_each_candidate_and_preserves_races(monkeypatch, capsys) -> None:
    """The mutation path revalidates live state per candidate and tolerates a disappearing sibling."""
    module = load_module()
    for repo in ("../evil", "owner/..", "owner/repo/extra"):
        with pytest.raises(RuntimeError, match="repository identity"):
            module.coalesce(repo, 1, "owner/repo", "feature/current", "a" * 40)
    with pytest.raises(RuntimeError, match="expected head"):
        module.coalesce("owner/repo", 1, "owner/repo", "feature/current", "BAD")
    with pytest.raises(RuntimeError, match="pull-request identity"):
        module.coalesce("owner/repo", 0, "owner/repo", "feature/current", "a" * 40)
    with pytest.raises(RuntimeError, match="pull-request identity"):
        module.coalesce("owner/repo", 1, "owner/repo", "bad ref", "a" * 40)

    monkeypatch.setattr(module, "_fetch_pr", lambda *_args: live_pr(head_sha="b" * 40))
    with pytest.raises(module.CoalescingRefused, match="moved before"):
        module.coalesce(
            "ContextualWisdomLab/.github",
            1,
            "ContextualWisdomLab/.github",
            "feature/current",
            "a" * 40,
        )

    candidate = run_record(100, 10)
    sibling = run_record(101, 10)
    monkeypatch.setattr(module, "_fetch_pr", lambda *_args: live_pr())
    active_calls = iter([[candidate, sibling], [candidate]])
    monkeypatch.setattr(module, "_active_runs", lambda *_args: next(active_calls))
    monkeypatch.setattr(module, "_fetch_run", lambda *_args: candidate)
    cancelled: list[int] = []
    monkeypatch.setattr(module, "_cancel_run", lambda _repo, run_id: cancelled.append(run_id))
    assert module.coalesce(
        "ContextualWisdomLab/.github",
        1,
        "ContextualWisdomLab/.github",
        "feature/current",
        "a" * 40,
    ) == []
    assert cancelled == []
    assert "Preserving run 100" in capsys.readouterr().out


def test_coalesce_cancels_only_revalidated_redundant_candidates(monkeypatch, capsys) -> None:
    """A proven older queued duplicate is cancelled and reported exactly once."""
    module = load_module()
    candidate = run_record(100, 10)
    sibling = run_record(101, 10)
    monkeypatch.setattr(module, "_fetch_pr", lambda *_args: live_pr())
    monkeypatch.setattr(module, "_active_runs", lambda *_args: [candidate, sibling])
    monkeypatch.setattr(module, "_fetch_run", lambda *_args: candidate)
    cancelled: list[int] = []
    monkeypatch.setattr(module, "_cancel_run", lambda _repo, run_id: cancelled.append(run_id))
    assert module.coalesce(
        "ContextualWisdomLab/.github",
        1,
        "ContextualWisdomLab/.github",
        "feature/current",
        "a" * 40,
    ) == [100]
    assert cancelled == [100]
    assert "Cancelled redundant queued current-head run 100" in capsys.readouterr().out


def test_parse_args_main_and_script_help(monkeypatch) -> None:
    """CLI parsing forwards exact identity and the executable entrypoint is reachable."""
    module = load_module()
    argv = [
        "--repo",
        "owner/repo",
        "--pr-number",
        "7",
        "--expected-head-repo",
        "owner/repo",
        "--expected-head-ref",
        "feature/current",
        "--expected-head",
        "a" * 40,
    ]
    parsed = module.parse_args(argv)
    assert parsed.pr_number == 7
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(module, "coalesce", lambda *args: calls.append(args) or [])
    assert module.main(argv) == 0
    assert calls == [("owner/repo", 7, "owner/repo", "feature/current", "a" * 40)]

    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--help"])
    with pytest.raises(SystemExit) as exc_info:
        runpy.run_path(str(SCRIPT), run_name="__main__")
    assert exc_info.value.code == 0


def test_workflow_is_trusted_pr_target_with_minimum_actions_write() -> None:
    """The production workflow uses trusted source and the smallest mutation scope."""
    assert WORKFLOW.is_file(), "current-head duplicate coalescer workflow is not implemented"
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "pull_request_target:" in text
    assert "types: [opened, synchronize, reopened]" in text
    assert "actions: write" in text
    assert "contents: read" in text
    assert "pull-requests: read" in text
    assert "persist-credentials: false" in text
    assert "ref: ${{ github.workflow_sha }}" in text
    assert "current_head_run_coalescer.py" in text
    assert "cancel-in-progress: true" in text
    assert "github.event.pull_request.number" in text
    assert "github.event.pull_request.head.sha" in text
