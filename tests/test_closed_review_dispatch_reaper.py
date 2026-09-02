"""Regression tests for central stale semantic-review dispatch retirement."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "ci"
    / "closed_review_dispatch_reaper.py"
)
spec = importlib.util.spec_from_file_location("closed_review_dispatch_reaper", SCRIPT)
assert spec is not None and spec.loader is not None
reaper = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = reaper
spec.loader.exec_module(reaper)


def _run(
    name: str,
    title: str,
    *,
    event: str = "repository_dispatch",
    run_id: int = 7,
) -> dict[str, object]:
    """Build one minimal Actions run payload for the trusted parser."""
    return {
        "id": run_id,
        "name": name,
        "display_title": title,
        "event": event,
    }


def test_parse_known_review_dispatch_title() -> None:
    """Exact central review run names bind repository, PR, head, and run id."""
    target = reaper.parse_review_dispatch(
        _run(
            "OpenCode Review Dispatch",
            "OpenCode Review Dispatch "
            "ContextualWisdomLab/contextual-orchestrator#946@" + "a" * 40,
        )
    )

    assert target is not None
    assert target.repository == "ContextualWisdomLab/contextual-orchestrator"
    assert target.pr_number == 946
    assert target.head_sha == "a" * 40
    assert target.run_id == "7"


def test_unknown_or_malformed_run_is_not_authoritative() -> None:
    """Unknown workflows and malformed target identities never authorize cancellation."""
    assert (
        reaper.parse_review_dispatch(
            _run(
                "Other",
                "OpenCode Review Dispatch ContextualWisdomLab/x#1@" + "a" * 40,
            )
        )
        is None
    )
    assert (
        reaper.parse_review_dispatch(
            _run(
                "OpenCode Review Dispatch",
                "OpenCode Review Dispatch attacker/x#1@" + "a" * 40,
            )
        )
        is None
    )
    assert (
        reaper.parse_review_dispatch(
            _run(
                "OpenCode Review Dispatch",
                "OpenCode Review Dispatch ContextualWisdomLab/x#1@short",
            )
        )
        is None
    )


def test_closed_target_is_cancelled() -> None:
    """A central dispatch cannot consume capacity after its target PR closes."""
    cancelled: list[str] = []
    summary = reaper.reap_review_dispatches(
        [
            _run(
                "OpenCode Review Dispatch",
                "OpenCode Review Dispatch ContextualWisdomLab/x#2@" + "b" * 40,
            )
        ],
        fetch_pr=lambda _repo, _pr: {
            "state": "closed",
            "head": {"sha": "b" * 40},
        },
        cancel=cancelled.append,
    )

    assert cancelled == ["7"]
    assert summary.cancelled_closed == 1
    assert summary.cancelled_stale_head == 0


def test_stale_head_is_cancelled_but_current_head_is_preserved() -> None:
    """Only the older dispatched head is retired for an open pull request."""
    cancelled: list[str] = []
    runs = [
        _run(
            "Required Noema Review",
            "Required Noema Review ContextualWisdomLab/x#3@" + "c" * 40,
            run_id=8,
        ),
        _run(
            "Strix Security Scan",
            "Strix Security Scan ContextualWisdomLab/x#3@" + "d" * 40,
            run_id=9,
        ),
    ]
    summary = reaper.reap_review_dispatches(
        runs,
        fetch_pr=lambda _repo, _pr: {
            "state": "open",
            "head": {"sha": "d" * 40},
        },
        cancel=cancelled.append,
    )

    assert cancelled == ["8"]
    assert summary.cancelled_stale_head == 1
    assert summary.preserved_current == 1


def test_unavailable_pr_metadata_never_cancels() -> None:
    """Missing live identity proof preserves the run rather than guessing stale."""
    cancelled: list[str] = []
    summary = reaper.reap_review_dispatches(
        [
            _run(
                "OpenCode Review Dispatch",
                "OpenCode Review Dispatch ContextualWisdomLab/private#4@" + "e" * 40,
            )
        ],
        fetch_pr=lambda _repo, _pr: (_ for _ in ()).throw(RuntimeError("denied")),
        cancel=cancelled.append,
    )

    assert cancelled == []
    assert summary.metadata_unavailable == 1


def test_non_repository_dispatch_run_never_cancels() -> None:
    """The reaper never mutates pull-request-target evidence."""
    cancelled: list[str] = []
    summary = reaper.reap_review_dispatches(
        [
            _run(
                "Required Noema Review",
                "Required Noema Review ContextualWisdomLab/x#3@" + "d" * 40,
                event="pull_request_target",
            )
        ],
        fetch_pr=lambda _repo, _pr: {
            "state": "closed",
            "head": {"sha": "d" * 40},
        },
        cancel=cancelled.append,
    )

    assert cancelled == []
    assert summary.ignored == 1


def test_reaper_workflow_uses_trusted_source_and_actions_write() -> None:
    """Workflow authority stays central, minimal, and detached from PR source."""
    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "workflows"
        / "central-review-dispatch-reaper.yml"
    ).read_text(encoding="utf-8")

    assert "actions: write" in workflow
    assert "id-token: write" in workflow
    assert "repository: ContextualWisdomLab/.github" in workflow
    assert "ref: ${{ github.workflow_sha }}" in workflow
    assert "persist-credentials: false" in workflow
    assert "pull_request" not in workflow.split("permissions:", 1)[0]
    assert "SCHEDULER_READ_TOKEN:" in workflow
    assert "scripts/ci/closed_review_dispatch_reaper.py" in workflow
