"""Review regressions for current-head GitHub Actions run coalescing."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "ci" / "current_head_run_coalescer.py"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "current-head-run-coalescer.yml"


def load_module():
    """Load the production coalescer from the current checkout."""
    spec = importlib.util.spec_from_file_location("current_head_run_coalescer_review", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def pr_head(*, sha: str = "a" * 40, ref: str = "feature/current") -> dict[str, object]:
    """Return one PR-style head identity."""
    return {
        "sha": sha,
        "ref": ref,
        "repo": {"full_name": "ContextualWisdomLab/.github"},
    }


def live_pr(*, state: str = "open", base_ref: str = "main") -> dict[str, object]:
    """Return one live PR identity with an explicit base boundary."""
    return {
        "state": state,
        "head": pr_head(),
        "base": {"ref": base_ref, "sha": "b" * 40},
    }


def run_record(
    run_id: int,
    *,
    status: str = "queued",
    event: str = "pull_request",
    top_head_sha: str = "a" * 40,
    top_head_branch: str = "feature/current",
    pr_number: int = 2,
) -> dict[str, object]:
    """Return an Actions run with both workflow and associated-PR identities."""
    return {
        "id": run_id,
        "workflow_id": 10,
        "status": status,
        "event": event,
        "head_sha": top_head_sha,
        "head_branch": top_head_branch,
        "head_repository": {"full_name": "ContextualWisdomLab/.github"},
        "pull_requests": [
            {
                "number": pr_number,
                "head": pr_head(),
                "base": {
                    "ref": "main",
                    "sha": "b" * 40,
                    "repo": {"full_name": "ContextualWisdomLab/.github"},
                },
            }
        ],
    }


def test_pull_request_target_matches_associated_pr_head_not_trusted_base_head() -> None:
    """Target-event runs bind to associated PR head rather than workflow base head."""
    module = load_module()
    target_run = run_record(
        100,
        event="pull_request_target",
        top_head_sha="c" * 40,
        top_head_branch="main",
    )
    assert module._run_identity_matches(
        target_run,
        repository="ContextualWisdomLab/.github",
        branch="feature/current",
        head_sha="a" * 40,
    )


def test_distinct_open_pr_association_cannot_authorize_cross_pr_cancellation() -> None:
    """An open sibling PR sharing one branch/SHA keeps its own workflow evidence."""
    module = load_module()
    candidate = run_record(100, pr_number=1)
    sibling = run_record(101, pr_number=2)
    other_open_pr = live_pr(base_ref="develop")
    with pytest.raises(module.CoalescingRefused, match="independent pull request"):
        module.validate_candidate_against_live_state(
            candidate,
            live_pr=live_pr(),
            active_same_head_runs=[candidate, sibling],
            current_pr_number=2,
            associated_prs={1: other_open_pr},
        )


def test_final_candidate_fetch_preserves_run_that_started_after_snapshot(monkeypatch) -> None:
    """A queued snapshot candidate that starts before final mutation is preserved."""
    module = load_module()
    queued = run_record(100)
    started = run_record(100, status="in_progress")
    sibling = run_record(101)
    monkeypatch.setattr(module, "_fetch_pr", lambda *_args: live_pr())
    monkeypatch.setattr(module, "_active_runs", lambda *_args: [queued, sibling])
    monkeypatch.setattr(module, "_fetch_run", lambda *_args: started)
    cancelled: list[int] = []
    monkeypatch.setattr(module, "_cancel_run", lambda _repo, run_id: cancelled.append(run_id))

    assert module.coalesce(
        "ContextualWisdomLab/.github",
        2,
        "ContextualWisdomLab/.github",
        "feature/current",
        "a" * 40,
    ) == []
    assert cancelled == []


def test_transport_is_token_bound_and_individually_timeout_bounded(monkeypatch) -> None:
    """Read and cancellation transports require GH_TOKEN and a per-call timeout."""
    module = load_module()
    monkeypatch.delenv("GH_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="GH_TOKEN"):
        module._cancel_run("owner/repo", 123)

    monkeypatch.setenv("GH_TOKEN", "token")
    calls: list[tuple[list[str], dict[str, object]]] = []

    def success(args, **kwargs):
        calls.append((list(args), dict(kwargs)))
        stdout = "{}" if "/cancel" not in " ".join(args) else ""
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr(module.subprocess, "run", success)
    assert module._run_json(["gh", "api", "repos/owner/repo"]) == {}
    module._cancel_run("owner/repo", 123)
    assert len(calls) == 2
    assert all(call_kwargs.get("timeout") == module.API_TIMEOUT_SECONDS for _, call_kwargs in calls)


def test_workflow_covers_ready_transition_and_never_expands_head_ref_inside_shell() -> None:
    """Ready events coalesce duplicates and untrusted refs cross the shell via env only."""
    text = WORKFLOW.read_text(encoding="utf-8")
    trigger_line = next(line.strip() for line in text.splitlines() if line.strip().startswith("types:"))
    for event_name in ("opened", "synchronize", "reopened", "ready_for_review"):
        assert event_name in trigger_line
    assert "EXPECTED_HEAD_REF: ${{ github.event.pull_request.head.ref }}" in text
    run_block = text.split("run: |", 1)[1]
    assert '--expected-head-ref "$EXPECTED_HEAD_REF"' in run_block
    assert 'github.event.pull_request.head.ref' not in run_block
