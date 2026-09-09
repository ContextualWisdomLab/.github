"""Regression tests for exact-current-head GitHub Actions run coalescing."""

from __future__ import annotations

import importlib.util
import runpy
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "ci" / "current_head_run_coalescer.py"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "pr-review-merge-scheduler.yml"


def load_module():
    """Load the production coalescer only after proving the file exists."""
    assert SCRIPT.is_file(), "current-head duplicate coalescer is not implemented"
    spec = importlib.util.spec_from_file_location("current_head_run_coalescer", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def pr_association(
    number: int = 1,
    *,
    head_sha: str = "a" * 40,
    branch: str = "feature/current",
    repository: str = "ContextualWisdomLab/.github",
    base_ref: str = "main",
) -> dict[str, object]:
    """Return one Actions run pull-request association fixture."""
    return {
        "number": number,
        "head": {"sha": head_sha, "ref": branch, "repo": {"full_name": repository}},
        "base": {"ref": base_ref, "sha": "c" * 40, "repo": {"full_name": repository}},
    }


def run_record(
    run_id: int,
    workflow_id: int,
    *,
    status: str = "queued",
    head_sha: str = "a" * 40,
    branch: str = "feature/current",
    repository: str = "ContextualWisdomLab/.github",
    event: str = "pull_request",
    pr_number: int = 1,
    execution_head_sha: str | None = None,
    associations: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    """Return one bounded Actions run fixture with authoritative PR association."""
    return {
        "id": run_id,
        "workflow_id": workflow_id,
        "status": status,
        "head_sha": execution_head_sha or head_sha,
        "head_branch": branch,
        "event": event,
        "head_repository": {"full_name": repository},
        "pull_requests": associations
        if associations is not None
        else [
            pr_association(
                pr_number,
                head_sha=head_sha,
                branch=branch,
                repository=repository,
            )
        ],
    }


def live_pr(
    *,
    state: str = "open",
    head_sha: str = "a" * 40,
    number: int = 1,
    base_ref: str = "main",
) -> dict[str, object]:
    """Return the exact live PR identity used by revalidation tests."""
    return {
        "number": number,
        "state": state,
        "head": {
            "sha": head_sha,
            "ref": "feature/current",
            "repo": {"full_name": "ContextualWisdomLab/.github"},
        },
        "base": {
            "sha": "c" * 40,
            "ref": base_ref,
            "repo": {"full_name": "ContextualWisdomLab/.github"},
        },
    }


def test_select_duplicate_queued_runs_keeps_one_authoritative_run_per_workflow() -> None:
    """Older queued duplicates are retired while one exact-head run survives."""
    module = load_module()
    runs = [run_record(100, 10), run_record(101, 10), run_record(102, 10), run_record(200, 20), run_record(201, 20)]
    assert module.select_duplicate_queued_run_ids(
        runs,
        repository="ContextualWisdomLab/.github",
        branch="feature/current",
        head_sha="a" * 40,
    ) == [100, 101, 200]


def test_in_progress_run_is_never_selected_and_makes_queued_siblings_redundant() -> None:
    """A running authoritative workflow is preserved and queued duplicates retire."""
    module = load_module()
    runs = [run_record(100, 10, status="in_progress"), run_record(101, 10), run_record(102, 10)]
    assert module.select_duplicate_queued_run_ids(
        runs,
        repository="ContextualWisdomLab/.github",
        branch="feature/current",
        head_sha="a" * 40,
    ) == [101, 102]


def test_group_with_no_queued_runs_has_nothing_to_coalesce() -> None:
    """A workflow group whose only active runs are in-progress selects nothing.

    ``_run_identity_matches`` only admits runs whose ``status`` is queued or
    in-progress, so a group can legitimately contain zero queued entries when
    every admitted run for that workflow happens to already be running --
    the ``if not queued: continue`` guard exists precisely for that shape.
    """
    module = load_module()
    runs = [run_record(100, 10, status="in_progress"), run_record(101, 10, status="in_progress")]
    assert module.select_duplicate_queued_run_ids(
        runs,
        repository="ContextualWisdomLab/.github",
        branch="feature/current",
        head_sha="a" * 40,
    ) == []


def test_pull_request_target_uses_associated_pr_head_not_execution_head() -> None:
    """Trusted-base pull_request_target runs coalesce by their associated PR head."""
    module = load_module()
    target = run_record(100, 10, event="pull_request_target", execution_head_sha="b" * 40)
    newer = run_record(101, 10, event="pull_request_target", execution_head_sha="b" * 40)
    assert module.select_duplicate_queued_run_ids(
        [target, newer],
        repository="ContextualWisdomLab/.github",
        branch="feature/current",
        head_sha="a" * 40,
    ) == [100]


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
    assert module._pull_request_associations({"pull_requests": "bad"}) == []
    assert module._association_number({"number": "1"}) is None


def test_revalidation_requires_a_distinct_newer_or_running_sibling() -> None:
    """The sole or newest queued current-head run is never cancelled."""
    module = load_module()
    candidate = run_record(100, 10)
    for active in ([candidate], [candidate, run_record(99, 10)]):
        with pytest.raises(module.CoalescingRefused, match="authoritative sibling"):
            module.validate_candidate_against_live_state(candidate, live_pr=live_pr(), active_same_head_runs=active)
    module.validate_candidate_against_live_state(
        candidate, live_pr=live_pr(), active_same_head_runs=[candidate, run_record(101, 10)]
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
            run_record(100, 10, status="in_progress"), live_pr=live_pr(), active_same_head_runs=[sibling]
        )
    with pytest.raises(module.CoalescingRefused, match="no longer open"):
        module.validate_candidate_against_live_state(candidate, live_pr=live_pr(state="closed"), active_same_head_runs=[sibling])
    with pytest.raises(module.CoalescingRefused, match="head moved"):
        module.validate_candidate_against_live_state(candidate, live_pr=live_pr(head_sha="b" * 40), active_same_head_runs=[sibling])
    with pytest.raises(module.CoalescingRefused, match="identity is malformed"):
        module.validate_candidate_against_live_state(run_record(0, 10), live_pr=live_pr(), active_same_head_runs=[sibling])
    with pytest.raises(module.CoalescingRefused, match="head moved"):
        module.validate_candidate_against_live_state(run_record(100, 10, event="push"), live_pr=live_pr(), active_same_head_runs=[sibling])


def test_pr_scope_rejects_other_open_pr_and_accepts_closed_matching_predecessor() -> None:
    """Concurrent PRs keep independent evidence while a closed predecessor may coalesce."""
    module = load_module()
    current = live_pr()
    other_assoc = [pr_association(2)]
    candidate = run_record(100, 10, pr_number=2, associations=other_assoc)
    sibling = run_record(101, 10)
    other_open = live_pr(number=2)
    with pytest.raises(module.CoalescingRefused, match="independent pull request"):
        module.validate_candidate_against_live_state(
            candidate,
            live_pr=current,
            active_same_head_runs=[candidate, sibling],
            current_pr_number=1,
            associated_prs={2: other_open},
        )
    other_closed = live_pr(state="closed", number=2)
    module.validate_candidate_against_live_state(
        candidate,
        live_pr=current,
        active_same_head_runs=[candidate, sibling],
        current_pr_number=1,
        associated_prs={2: other_closed},
    )
    wrong_base = live_pr(state="closed", number=2, base_ref="release")
    with pytest.raises(module.CoalescingRefused, match="independent pull request"):
        module.validate_candidate_against_live_state(
            candidate,
            live_pr=current,
            active_same_head_runs=[candidate, sibling],
            current_pr_number=1,
            associated_prs={2: wrong_base},
        )


def test_pr_scope_unsafe_sibling_cannot_supply_authoritative_evidence() -> None:
    """A sibling belonging to an independent open PR is skipped, not authoritative.

    Regression for the ``validate_candidate_against_live_state`` sibling loop
    specifically (not the standalone ``_run_pr_scope_is_safe`` calls above):
    a sibling that passes id/workflow/head-identity but belongs to a
    different, still-open PR must be excluded from the authoritative-sibling
    search entirely, not merely fail some other unrelated check. The bad
    sibling's id (150) exceeds the candidate's (100), so if it were wrongly
    treated as authoritative this would pass instead of failing closed.
    """
    module = load_module()
    candidate = run_record(100, 10, pr_number=1)
    other_open = live_pr(number=2)
    bad_sibling = run_record(150, 10, pr_number=2, associations=[pr_association(2)])
    with pytest.raises(module.CoalescingRefused, match="authoritative sibling"):
        module.validate_candidate_against_live_state(
            candidate,
            live_pr=live_pr(),
            active_same_head_runs=[candidate, bad_sibling],
            current_pr_number=1,
            associated_prs={2: other_open},
        )


def test_pr_scope_rejects_a_run_with_no_pull_request_associations() -> None:
    """An orphaned run with zero PR associations cannot claim any PR's scope."""
    module = load_module()
    assert not module._run_pr_scope_is_safe(
        run_record(100, 10, associations=[]),
        live_pr=live_pr(),
        current_pr_number=1,
        associated_prs={},
    )


def test_pr_scope_rejects_a_malformed_live_pr() -> None:
    """A live PR missing head/base identity cannot authorize any scope decision."""
    module = load_module()
    malformed_live_pr = {
        "number": 1,
        "state": "open",
        "head": {"sha": "", "ref": "feature/current", "repo": {"full_name": "ContextualWisdomLab/.github"}},
        "base": {"sha": "c" * 40, "ref": "main", "repo": {"full_name": "ContextualWisdomLab/.github"}},
    }
    assert not module._run_pr_scope_is_safe(
        run_record(100, 10),
        live_pr=malformed_live_pr,
        current_pr_number=1,
        associated_prs={},
    )


def test_pr_scope_rejects_an_association_with_a_malformed_number() -> None:
    """An association carrying no positive-integer PR number is untrusted."""
    module = load_module()
    malformed_association = {
        **pr_association(1),
        "number": None,
    }
    assert not module._run_pr_scope_is_safe(
        run_record(100, 10, associations=[malformed_association]),
        live_pr=live_pr(),
        current_pr_number=1,
        associated_prs={},
    )


def test_pr_scope_rejects_an_association_whose_head_does_not_match_live_head() -> None:
    """An association reporting a different head than the live PR is untrusted."""
    module = load_module()
    mismatched_association = pr_association(1, head_sha="b" * 40)
    assert not module._run_pr_scope_is_safe(
        run_record(100, 10, associations=[mismatched_association]),
        live_pr=live_pr(),
        current_pr_number=1,
        associated_prs={},
    )


def test_pr_scope_rejects_an_association_whose_base_does_not_match_live_base() -> None:
    """An association reporting a different base branch than the live PR is untrusted."""
    module = load_module()
    mismatched_association = pr_association(1, base_ref="release")
    assert not module._run_pr_scope_is_safe(
        run_record(100, 10, associations=[mismatched_association]),
        live_pr=live_pr(),
        current_pr_number=1,
        associated_prs={},
    )


def test_pr_scope_rejects_a_predecessor_number_missing_from_associated_prs() -> None:
    """A closed-predecessor PR number with no fetched live state is untrusted."""
    module = load_module()
    candidate = run_record(100, 10, pr_number=2, associations=[pr_association(2)])
    assert not module._run_pr_scope_is_safe(
        candidate,
        live_pr=live_pr(),
        current_pr_number=1,
        associated_prs={},
    )


def test_pr_scope_rejects_a_predecessor_whose_live_head_does_not_match() -> None:
    """A fetched closed predecessor whose live head has since moved is untrusted."""
    module = load_module()
    candidate = run_record(100, 10, pr_number=2, associations=[pr_association(2)])
    moved_predecessor = live_pr(state="closed", number=2, head_sha="b" * 40)
    assert not module._run_pr_scope_is_safe(
        candidate,
        live_pr=live_pr(),
        current_pr_number=1,
        associated_prs={2: moved_predecessor},
    )


def test_revalidation_ignores_non_authoritative_sibling_shapes() -> None:
    """Different workflow or malformed sibling records cannot authorize cancellation."""
    module = load_module()
    candidate = run_record(100, 10)
    siblings = [run_record(101, 11), run_record(102, 10, branch="other"), run_record(0, 10), candidate]
    with pytest.raises(module.CoalescingRefused, match="authoritative sibling"):
        module.validate_candidate_against_live_state(candidate, live_pr=live_pr(), active_same_head_runs=siblings)


def test_run_json_uses_token_timeout_decodes_success_and_bounds_failure(monkeypatch) -> None:
    """GitHub transport is token-bound, JSON-only, individually timed, and bounded."""
    module = load_module()
    monkeypatch.delenv("GH_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="GH_TOKEN"):
        module._run_json(["gh", "api", "repos/o/r"])

    monkeypatch.setenv("GH_TOKEN", "token")
    seen: dict[str, object] = {}

    def success(*args, **kwargs):
        seen.update(kwargs)
        return SimpleNamespace(returncode=0, stdout='{"ok":true}', stderr="")

    monkeypatch.setattr(module.subprocess, "run", success)
    assert module._run_json(["gh", "api", "repos/o/r"]) == {"ok": True}
    assert seen["timeout"] == module.API_TIMEOUT_SECONDS

    def timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd="gh", timeout=30)

    monkeypatch.setattr(module.subprocess, "run", timeout)
    with pytest.raises(RuntimeError, match="timed out"):
        module._run_json(["gh", "api", "repos/o/r"])

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
    assert not any(item.startswith("head_sha=") for call in calls for item in call)

    monkeypatch.setattr(module, "_run_json", lambda _args: {"workflow_runs": "bad"})
    with pytest.raises(RuntimeError, match="malformed Actions"):
        module._active_runs("o/r", "a" * 40)


def test_cancel_run_uses_explicit_transport_and_ordinary_endpoint(monkeypatch) -> None:
    """Cancellation uses the ordinary endpoint and proves terminal state."""
    module = load_module()
    calls: list[list[str]] = []
    monkeypatch.setattr(module, "_run_json", lambda args: calls.append(list(args)))
    states = iter(
        [
            {"status": "in_progress", "conclusion": None},
            {"status": "completed", "conclusion": "cancelled"},
        ]
    )
    monkeypatch.setattr(module, "_fetch_run", lambda _repo, _run_id: next(states))
    sleeps: list[float] = []
    monkeypatch.setattr(module.time, "sleep", sleeps.append)
    module._cancel_run("o/r", 123)
    assert calls == [["gh", "api", "-X", "POST", "repos/o/r/actions/runs/123/cancel"]]
    assert "force-cancel" not in " ".join(calls[0])
    assert sleeps == [module.CANCELLATION_POLL_INTERVAL_SECONDS]


def test_cancel_run_fails_when_terminal_cancellation_is_unproven(monkeypatch) -> None:
    """An accepted cancellation is not reported complete while GitHub stays active."""
    module = load_module()
    monkeypatch.setattr(module, "_run_json", lambda _args: None)
    monkeypatch.setattr(
        module,
        "_fetch_run",
        lambda _repo, _run_id: {"status": "in_progress", "conclusion": None},
    )
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)

    with pytest.raises(RuntimeError, match="did not reach completed/cancelled"):
        module._cancel_run("o/r", 123)


def test_associated_pr_fetches_only_same_head_noncurrent_numbers(monkeypatch) -> None:
    """Predecessor lookup ignores unrelated active runs and fetches each same-head PR once."""
    module = load_module()
    calls: list[int] = []
    monkeypatch.setattr(module, "_fetch_pr", lambda _repo, number: calls.append(number) or live_pr(number=number, state="closed"))
    runs = [
        run_record(100, 10),
        run_record(101, 10, pr_number=2),
        run_record(102, 10, pr_number=2),
        run_record(103, 10, pr_number=999, head_sha="b" * 40),
    ]
    result = module._associated_prs(
        "o/r",
        runs,
        1,
        repository="ContextualWisdomLab/.github",
        branch="feature/current",
        head_sha="a" * 40,
    )
    assert list(result) == [2]
    assert calls == [2]


def test_refresh_siblings_refetches_only_same_workflow_head_peers(monkeypatch) -> None:
    """Sibling refresh is bounded to exact-head peers and fails closed without a candidate."""
    module = load_module()
    candidate = run_record(100, 10)
    sibling = run_record(101, 10)
    other_workflow = run_record(102, 11)
    other_head = run_record(103, 10, head_sha="b" * 40)
    assert module._refresh_siblings(
        "o/r", [sibling], 100, repository="ContextualWisdomLab/.github", branch="feature/current", head_sha="a" * 40
    ) == []
    assert module._refresh_siblings(
        "o/r", [{**candidate, "workflow_id": 0}], 100, repository="ContextualWisdomLab/.github", branch="feature/current", head_sha="a" * 40
    ) == []
    calls: list[int] = []
    monkeypatch.setattr(module, "_fetch_run", lambda _repo, run_id: calls.append(run_id) or sibling)
    refreshed = module._refresh_siblings(
        "o/r",
        [candidate, sibling, other_workflow, other_head],
        100,
        repository="ContextualWisdomLab/.github",
        branch="feature/current",
        head_sha="a" * 40,
    )
    assert [item["id"] for item in refreshed] == [101]
    assert calls == [101]


def test_coalesce_validates_inputs_rechecks_each_candidate_and_preserves_races(monkeypatch, capsys) -> None:
    """The mutation path revalidates live state per candidate and preserves races."""
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
        module.coalesce("ContextualWisdomLab/.github", 1, "ContextualWisdomLab/.github", "feature/current", "a" * 40)

    candidate = run_record(100, 10)
    sibling = run_record(101, 10)
    monkeypatch.setattr(module, "_fetch_pr", lambda *_args: live_pr())
    active_calls = iter([[candidate, sibling], [candidate]])
    monkeypatch.setattr(module, "_active_runs", lambda *_args: next(active_calls))
    monkeypatch.setattr(module, "_fetch_run", lambda *_args: candidate)
    cancelled: list[int] = []
    monkeypatch.setattr(module, "_cancel_run", lambda _repo, run_id: cancelled.append(run_id))
    assert module.coalesce("ContextualWisdomLab/.github", 1, "ContextualWisdomLab/.github", "feature/current", "a" * 40) == []
    assert cancelled == []
    assert "Preserving run 100" in capsys.readouterr().out


def test_coalesce_refetches_candidate_last_and_preserves_started_run(monkeypatch) -> None:
    """A candidate that starts after sibling validation is not cancelled."""
    module = load_module()
    candidate = run_record(100, 10)
    sibling = run_record(101, 10)
    monkeypatch.setattr(module, "_fetch_pr", lambda *_args: live_pr())
    monkeypatch.setattr(module, "_active_runs", lambda *_args: [candidate, sibling])

    def fetch_run(_repo: str, run_id: int):
        return sibling if run_id == 101 else run_record(100, 10, status="in_progress")

    monkeypatch.setattr(module, "_fetch_run", fetch_run)
    cancelled: list[int] = []
    monkeypatch.setattr(module, "_cancel_run", lambda _repo, run_id: cancelled.append(run_id))
    assert module.coalesce("ContextualWisdomLab/.github", 1, "ContextualWisdomLab/.github", "feature/current", "a" * 40) == []
    assert cancelled == []


def test_coalesce_cancels_only_revalidated_redundant_candidates(monkeypatch, capsys) -> None:
    """A proven older queued duplicate is cancelled and reported exactly once."""
    module = load_module()
    candidate = run_record(100, 10)
    sibling = run_record(101, 10)
    monkeypatch.setattr(module, "_fetch_pr", lambda *_args: live_pr())
    monkeypatch.setattr(module, "_active_runs", lambda *_args: [candidate, sibling])
    monkeypatch.setattr(
        module,
        "_fetch_run",
        lambda _repo, run_id: sibling if run_id == 101 else candidate,
    )
    cancelled: list[int] = []
    monkeypatch.setattr(module, "_cancel_run", lambda _repo, run_id: cancelled.append(run_id))
    assert module.coalesce("ContextualWisdomLab/.github", 1, "ContextualWisdomLab/.github", "feature/current", "a" * 40) == [100]
    assert cancelled == [100]
    assert "Cancelled redundant queued current-head run 100" in capsys.readouterr().out


def test_coalesce_fails_before_reporting_unproven_cancellation(monkeypatch, capsys) -> None:
    """A cancellation that never reaches terminal state must not be reported."""
    module = load_module()
    candidate = run_record(100, 10)
    sibling = run_record(101, 10)
    monkeypatch.setattr(module, "_fetch_pr", lambda *_args: live_pr())
    monkeypatch.setattr(module, "_active_runs", lambda *_args: [candidate, sibling])
    monkeypatch.setattr(module, "_fetch_run", lambda _repo, run_id: sibling if run_id == 101 else candidate)
    monkeypatch.setattr(
        module,
        "_cancel_run",
        lambda _repo, _run_id: (_ for _ in ()).throw(
            RuntimeError("terminal cancellation unproven")
        ),
    )

    with pytest.raises(RuntimeError, match="terminal cancellation unproven"):
        module.coalesce(
            "ContextualWisdomLab/.github",
            1,
            "ContextualWisdomLab/.github",
            "feature/current",
            "a" * 40,
        )
    assert "Cancelled redundant" not in capsys.readouterr().out


def test_parse_args_main_and_script_help(monkeypatch) -> None:
    """CLI parsing forwards exact identity and the executable entrypoint is reachable."""
    module = load_module()
    argv = [
        "--repo", "owner/repo", "--pr-number", "7", "--expected-head-repo", "owner/repo",
        "--expected-head-ref", "feature/current", "--expected-head", "a" * 40,
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


def test_main_treats_coalescing_refused_as_a_safe_no_op(monkeypatch, capsys) -> None:
    """A stale, superseded run must exit 0, matching the workflow's documented design.

    The merge scheduler's coalescing step treats `CoalescingRefused` as
    "a safe no-op" whenever a queued instance's remembered head no longer matches
    the live head. `coalesce()`'s own top-level live-state check (before any
    per-candidate loop even starts) raises exactly that exception in this case --
    but `main()` did not catch it, so it propagated as an uncaught exception and
    crashed the job with a non-zero exit (reproduced live on
    `ContextualWisdomLab/.github#1503`, run 33766056421, job 100684095620: a stale
    queued run whose head had since moved failed the required `coalesce` check
    with `CoalescingRefused: pull request head moved before duplicate
    classification` instead of exiting cleanly).
    """
    module = load_module()
    argv = [
        "--repo", "owner/repo", "--pr-number", "7", "--expected-head-repo", "owner/repo",
        "--expected-head-ref", "feature/current", "--expected-head", "a" * 40,
    ]

    def refuse(*_args: object) -> list[int]:
        raise module.CoalescingRefused("pull request head moved before duplicate classification")

    monkeypatch.setattr(module, "coalesce", refuse)
    assert module.main(argv) == 0
    assert "pull request head moved before duplicate classification" in capsys.readouterr().out


def test_workflow_is_integrated_into_trusted_scheduler_job() -> None:
    """The production step reuses trusted source and scheduler permissions."""
    assert WORKFLOW.is_file(), "current-head duplicate coalescer step is not implemented"
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "pull_request_target:" in text
    trigger_line = next(
        line.strip() for line in text.splitlines() if line.strip().startswith("types:")
    )
    for event_name in (
        "opened",
        "synchronize",
        "reopened",
        "ready_for_review",
        "converted_to_draft",
    ):
        assert event_name in trigger_line
    assert "actions: write" in text
    assert "contents: read" in text
    assert "pull-requests: write" in text
    assert "Materialize trusted scheduler" in text
    assert "TRUSTED_SOURCE_REF" in text
    assert "current_head_run_coalescer.py" in text
    assert "EXPECTED_HEAD_REF: ${{ github.event.pull_request.head.ref }}" in text
    assert '--expected-head-ref "$EXPECTED_HEAD_REF"' in text
    run_block = text.split("      - name: Retire redundant queued exact-head runs\n", 1)[
        1
    ].split("run: |", 1)[1]
    assert "${{ github.event.pull_request.head.ref }}" not in run_block


def test_workflow_survives_repeated_pushes_before_any_run_starts() -> None:
    """A superseded coalescer run for an OLDER push is safe to cancel outright.

    Unlike a review job (where a cancelled run wastes real inference work),
    coalescing is an idempotent cleanup pass that now runs as steps inside
    the scheduler's own `scan-pr-queue` job rather than a dedicated workflow
    file (folded in by "ci(actions): fold head coalescing into scheduler").
    The scheduler's existing workflow-level concurrency group -- scoped by
    repository and PR number, not also head SHA -- already retires an older
    push's still-queued scheduler run before a new one can consume another
    job slot under the organization's Actions ceiling, so no separate
    coalescer-specific concurrency group is needed anymore. The coalescing
    step's own first action re-fetches the PR and gates every mutation on
    the exact current HEAD, so cancelling an older push's queued run never
    loses real cleanup work: the newest invocation re-derives the correct
    current state from scratch.
    """
    text = WORKFLOW.read_text(encoding="utf-8")
    concurrency_block = text.split("concurrency:", 1)[1].split("jobs:", 1)[0]

    assert (
        "group: >-\n"
        "    central-pr-review-merge-scheduler-${{ github.repository }}-${{\n"
        "    github.event_name == 'pull_request_target' && format('pr-{0}', github.event.pull_request.number) ||"
        in concurrency_block
    )
    assert "github.event.pull_request.head.sha" not in concurrency_block
    assert (
        "cancel-in-progress: ${{ github.event_name == 'pull_request_target' "
        "|| github.event_name == 'pull_request_review' "
        "|| github.event_name == 'repository_dispatch' }}"
        in concurrency_block
    )
