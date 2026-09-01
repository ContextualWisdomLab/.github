"""Regression tests for exact-current-head GitHub Actions run coalescing."""

from __future__ import annotations

import importlib.util
from pathlib import Path

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


def test_in_progress_run_is_never_selected_and_makes_all_queued_siblings_redundant() -> None:
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


def test_other_heads_branches_repositories_workflows_and_events_are_not_coalesced() -> None:
    """Coalescing stays inside one exact current-head pull-request workflow identity."""
    module = load_module()
    runs = [
        run_record(100, 10),
        run_record(101, 11),
        run_record(102, 10, head_sha="b" * 40),
        run_record(103, 10, branch="other"),
        run_record(104, 10, repository="ContextualWisdomLab/TEPP"),
        run_record(105, 10, event="push"),
    ]

    assert module.select_duplicate_queued_run_ids(
        runs,
        repository="ContextualWisdomLab/.github",
        branch="feature/current",
        head_sha="a" * 40,
    ) == []


def test_revalidation_requires_a_distinct_authoritative_sibling() -> None:
    """The sole current-head run is preserved when no same-workflow sibling remains."""
    module = load_module()
    candidate = run_record(100, 10)
    with pytest.raises(module.CoalescingRefused, match="authoritative sibling"):
        module.validate_candidate_against_live_state(
            candidate,
            live_pr={
                "state": "open",
                "head": {
                    "sha": "a" * 40,
                    "ref": "feature/current",
                    "repo": {"full_name": "ContextualWisdomLab/.github"},
                },
            },
            active_same_head_runs=[candidate],
        )


def test_revalidation_rejects_moved_pr_and_nonqueued_candidate() -> None:
    """A head move or status transition fails closed before cancellation."""
    module = load_module()
    candidate = run_record(100, 10)
    sibling = run_record(101, 10)
    moved_pr = {
        "state": "open",
        "head": {
            "sha": "b" * 40,
            "ref": "feature/current",
            "repo": {"full_name": "ContextualWisdomLab/.github"},
        },
    }
    with pytest.raises(module.CoalescingRefused, match="head moved"):
        module.validate_candidate_against_live_state(
            candidate,
            live_pr=moved_pr,
            active_same_head_runs=[candidate, sibling],
        )

    running = run_record(100, 10, status="in_progress")
    with pytest.raises(module.CoalescingRefused, match="no longer queued"):
        module.validate_candidate_against_live_state(
            running,
            live_pr={
                "state": "open",
                "head": {
                    "sha": "a" * 40,
                    "ref": "feature/current",
                    "repo": {"full_name": "ContextualWisdomLab/.github"},
                },
            },
            active_same_head_runs=[running, sibling],
        )


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
