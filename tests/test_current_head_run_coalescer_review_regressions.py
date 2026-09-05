"""Review regressions for current-head GitHub Actions run coalescing."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "ci" / "current_head_run_coalescer.py"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "pr-review-merge-scheduler.yml"


def load_module():
    """Load the production coalescer from the current checkout."""
    spec = importlib.util.spec_from_file_location("current_head_run_coalescer_review", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def full_repo(name: str = "ContextualWisdomLab/.github") -> dict[str, object]:
    """Return the full repository shape emitted by the pull-request endpoint."""
    return {"id": 1274066402, "full_name": name}


def minimal_repo(name: str = "ContextualWisdomLab/.github") -> dict[str, object]:
    """Return the minimal repository shape embedded in Actions run PR associations."""
    owner, repository = name.split("/", 1)
    return {
        "id": 1274066402,
        "name": repository,
        "url": f"https://api.github.com/repos/{owner}/{repository}",
    }


def pr_head(
    *,
    sha: str = "a" * 40,
    ref: str = "feature/current",
    repository: dict[str, object] | None = None,
) -> dict[str, object]:
    """Return one PR-style head identity."""
    return {
        "sha": sha,
        "ref": ref,
        "repo": repository or full_repo(),
    }


def live_pr(
    *,
    state: str = "open",
    base_ref: str = "main",
    base_sha: str = "b" * 40,
    base_repo: str = "ContextualWisdomLab/.github",
) -> dict[str, object]:
    """Return one live PR identity with an explicit exact base boundary."""
    return {
        "state": state,
        "head": pr_head(),
        "base": {"ref": base_ref, "sha": base_sha, "repo": full_repo(base_repo)},
    }


def run_record(
    run_id: int,
    *,
    status: str = "queued",
    event: str = "pull_request",
    top_head_sha: str = "a" * 40,
    top_head_branch: str = "feature/current",
    pr_number: int = 2,
    base_ref: str = "main",
    base_sha: str = "b" * 40,
    base_repo: str = "ContextualWisdomLab/.github",
    minimal_association: bool = False,
) -> dict[str, object]:
    """Return an Actions run with both workflow and associated-PR identities."""
    association_repo = minimal_repo() if minimal_association else full_repo()
    association_base_repo = minimal_repo(base_repo) if minimal_association else full_repo(base_repo)
    return {
        "id": run_id,
        "workflow_id": 10,
        "status": status,
        "event": event,
        "head_sha": top_head_sha,
        "head_branch": top_head_branch,
        "head_repository": full_repo(),
        "pull_requests": [
            {
                "number": pr_number,
                "head": pr_head(repository=association_repo),
                "base": {
                    "ref": base_ref,
                    "sha": base_sha,
                    "repo": association_base_repo,
                },
            }
        ],
    }


def test_real_actions_repository_shape_normalizes_to_pull_request_identity() -> None:
    """Minimal Actions associations normalize to the same repository name as live PRs."""
    module = load_module()
    minimal_head = pr_head(repository=minimal_repo())
    assert module._head_tuple(minimal_head) == (
        "ContextualWisdomLab/.github",
        "feature/current",
        "a" * 40,
    )
    minimal_base = {"ref": "main", "sha": "b" * 40, "repo": minimal_repo()}
    assert module._base_tuple(minimal_base) == (
        "ContextualWisdomLab/.github",
        "main",
        "b" * 40,
    )


@pytest.mark.parametrize(
    ("repository_shape", "expected"),
    [
        (None, ""),
        (full_repo(), "ContextualWisdomLab/.github"),
        ({"full_name": "bad", "url": minimal_repo()["url"]}, ""),
        ({}, ""),
        ({"url": 7}, ""),
        ({"url": "http://api.github.com/repos/ContextualWisdomLab/.github"}, ""),
        ({"url": "https://example.com/repos/ContextualWisdomLab/.github"}, ""),
        ({"url": "https://api.github.com/repos/ContextualWisdomLab/.github?x=1"}, ""),
        ({"url": "https://api.github.com/repos/ContextualWisdomLab"}, ""),
        ({"url": "https://api.github.com/repos/../.github"}, ""),
        (minimal_repo(), "ContextualWisdomLab/.github"),
    ],
)
def test_repository_shape_normalization_fails_closed(
    repository_shape: object, expected: str
) -> None:
    """Repository normalization accepts only full names or canonical GitHub API URLs."""
    module = load_module()
    assert module._repository_full_name(repository_shape) == expected


def test_minimal_actions_associations_pass_exact_scope_for_both_pr_events() -> None:
    """Real Actions association shapes remain eligible for PR and target-event coalescing."""
    module = load_module()
    for event in ("pull_request", "pull_request_target"):
        candidate = run_record(100, event=event, minimal_association=True)
        sibling = run_record(101, event=event, minimal_association=True)
        module.validate_candidate_against_live_state(
            candidate,
            live_pr=live_pr(),
            active_same_head_runs=[candidate, sibling],
            current_pr_number=2,
            associated_prs={},
        )


def test_pull_request_target_rejects_refreshed_association_on_an_old_run() -> None:
    """A minimal PR association cannot replace the original REST run revision."""
    module = load_module()
    target_run = run_record(
        100,
        event="pull_request_target",
        top_head_sha="c" * 40,
        top_head_branch="main",
        minimal_association=True,
    )
    assert not module._run_identity_matches(
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


def test_closed_predecessor_must_share_exact_base_sha_and_repository() -> None:
    """A closed predecessor on a different base snapshot cannot donate required evidence."""
    module = load_module()
    current = live_pr()
    sibling = run_record(101, pr_number=2)

    candidate_old_base = run_record(100, pr_number=1, base_sha="c" * 40)
    predecessor_old_base = live_pr(state="closed", base_sha="c" * 40)
    with pytest.raises(module.CoalescingRefused, match="independent pull request"):
        module.validate_candidate_against_live_state(
            candidate_old_base,
            live_pr=current,
            active_same_head_runs=[candidate_old_base, sibling],
            current_pr_number=2,
            associated_prs={1: predecessor_old_base},
        )

    candidate_other_repo = run_record(100, pr_number=1, base_repo="ContextualWisdomLab/TEPP")
    predecessor_other_repo = live_pr(
        state="closed",
        base_repo="ContextualWisdomLab/TEPP",
    )
    with pytest.raises(module.CoalescingRefused, match="independent pull request"):
        module.validate_candidate_against_live_state(
            candidate_other_repo,
            live_pr=current,
            active_same_head_runs=[candidate_other_repo, sibling],
            current_pr_number=2,
            associated_prs={1: predecessor_other_repo},
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


def test_authoritative_sibling_is_refetched_and_must_still_be_active(monkeypatch) -> None:
    """A sibling that completed after the bulk snapshot cannot justify cancellation."""
    module = load_module()
    candidate = run_record(100)
    stale_sibling = run_record(101)
    completed_sibling = run_record(101, status="completed")
    monkeypatch.setattr(module, "_fetch_pr", lambda *_args: live_pr())
    monkeypatch.setattr(module, "_active_runs", lambda *_args: [candidate, stale_sibling])

    def fetch_run(_repo: str, run_id: int):
        if run_id == 101:
            return completed_sibling
        return candidate

    monkeypatch.setattr(module, "_fetch_run", fetch_run)
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
        command = " ".join(args)
        if "/cancel" in command:
            stdout = ""
        elif command.endswith("actions/runs/123"):
            stdout = '{"status":"completed","conclusion":"cancelled"}'
        else:
            stdout = "{}"
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr(module.subprocess, "run", success)
    assert module._run_json(["gh", "api", "repos/owner/repo"]) == {}
    module._cancel_run("owner/repo", 123)
    assert len(calls) == 3
    assert all(call_kwargs.get("timeout") == module.API_TIMEOUT_SECONDS for _, call_kwargs in calls)


def test_workflow_covers_ready_transition_and_never_expands_head_ref_inside_shell() -> None:
    """Ready events coalesce duplicates and untrusted refs cross the shell via env only."""
    text = WORKFLOW.read_text(encoding="utf-8")
    trigger_line = next(line.strip() for line in text.splitlines() if line.strip().startswith("types:"))
    for event_name in ("opened", "synchronize", "reopened", "ready_for_review"):
        assert event_name in trigger_line
    assert "EXPECTED_HEAD_REF: ${{ github.event.pull_request.head.ref }}" in text
    run_block = text.split("      - name: Retire redundant queued exact-head runs\n", 1)[
        1
    ].split("run: |", 1)[1]
    assert '--expected-head-ref "$EXPECTED_HEAD_REF"' in run_block
    assert 'github.event.pull_request.head.ref' not in run_block
