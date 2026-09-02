"""Regress ambiguous ruleset mutation timeouts and manual owner-plane safeguards."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts" / "ci" / "reconcile_ruleset_governance.py"


def load_module():
    """Load the production reconciler from the exact checkout."""

    spec = importlib.util.spec_from_file_location("ruleset_governance_timeout_regression", SOURCE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def repository_target(module):
    """Return the exact central owner-repository target used by the manifest."""

    return module.RulesetTarget(
        scope="repository",
        owner="ContextualWisdomLab",
        repository=".github",
        ruleset_id=17921150,
        name="Lock default branch",
    )


def live_payload() -> dict:
    """Return one live-shaped repository ruleset with deliberate governance drift."""

    return {
        "id": 17921150,
        "name": "Lock default branch",
        "target": "branch",
        "source_type": "Repository",
        "source": "ContextualWisdomLab/.github",
        "enforcement": "active",
        "bypass_actors": [
            {"actor_id": None, "actor_type": "OrganizationAdmin", "bypass_mode": "always"}
        ],
        "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
        "rules": [
            {"type": "deletion"},
            {"type": "non_fast_forward"},
            {
                "type": "pull_request",
                "parameters": {
                    "required_approving_review_count": 0,
                    "dismiss_stale_reviews_on_push": True,
                    "required_reviewers": [],
                    "require_code_owner_review": False,
                    "require_last_push_approval": False,
                    "required_review_thread_resolution": True,
                    "allowed_merge_methods": ["merge", "squash", "rebase"],
                },
            },
        ],
    }


def exercise_ambiguous_put(monkeypatch, *, history_outcome: str) -> tuple[object, list[tuple]]:
    """Prepare one privileged mutation whose PUT times out after an unknown server outcome."""

    module = load_module()
    target = repository_target(module)
    first = live_payload()
    desired = module._desired_payload(first, target)
    converged = {**first, **desired}
    calls: list[tuple] = []
    get_count = 0

    monkeypatch.setattr(module, "_assert_canonical_governance", lambda *_args: None)
    monkeypatch.setattr(module, "_assert_current_main", lambda *_args: None)
    monkeypatch.setattr(module, "_latest_history_version", lambda *_args: 41)

    def fake_api(method, endpoint, *, body=None):
        nonlocal get_count
        calls.append((method, endpoint, body))
        if method == "GET" and endpoint == target.endpoint:
            get_count += 1
            if get_count <= 2:
                return first
            return converged
        if method == "PUT" and endpoint == target.endpoint:
            raise subprocess.TimeoutExpired(cmd=["gh", "api"], timeout=30)
        raise AssertionError((method, endpoint))

    def verify_history(
        seen_target,
        baseline_version,
        seen_desired,
        *,
        expected_main_sha=None,
    ):
        calls.append(("HISTORY", baseline_version, seen_desired, expected_main_sha))
        assert seen_target == target
        assert baseline_version == 41
        assert seen_desired == desired
        # Once a PUT is issued, history settlement must finish without a stale-main veto.
        assert expected_main_sha is None
        if history_outcome == "not-accepted":
            raise module.RulesetGovernanceError("ruleset mutation is not visible in history")
        if history_outcome == "collision":
            raise module.RulesetGovernanceError(
                "concurrent ruleset history detected; restored newest displaced administrator state"
            )

    monkeypatch.setattr(module, "_gh_api", fake_api)
    monkeypatch.setattr(module, "_verify_ruleset_history_transition", verify_history)
    return module, calls


def test_put_timeout_before_acceptance_enters_history_path_and_fails_closed(monkeypatch) -> None:
    """An unaccepted ambiguous PUT must be disproved from history rather than leak TimeoutExpired."""

    module, calls = exercise_ambiguous_put(monkeypatch, history_outcome="not-accepted")
    with pytest.raises(module.RulesetGovernanceError, match="not visible in history"):
        module._reconcile_target(
            repository_target(module),
            verify_only=False,
            expected_main_sha="a" * 40,
        )
    assert any(call[0] == "HISTORY" for call in calls)


def test_put_timeout_after_acceptance_without_collision_verifies_and_converges(monkeypatch) -> None:
    """A committed timed-out PUT succeeds only after immutable history and live convergence agree."""

    module, calls = exercise_ambiguous_put(monkeypatch, history_outcome="accepted")
    assert (
        module._reconcile_target(
            repository_target(module),
            verify_only=False,
            expected_main_sha="a" * 40,
        )
        is True
    )
    assert sum(call[0] == "HISTORY" for call in calls) == 1
    assert sum(call[0] == "PUT" for call in calls) == 1


def test_put_timeout_after_acceptance_with_collision_preserves_recovery_failure(monkeypatch) -> None:
    """A timed-out PUT that displaced another version must run recovery and remain fail-closed."""

    module, calls = exercise_ambiguous_put(monkeypatch, history_outcome="collision")
    with pytest.raises(module.RulesetGovernanceError, match="restored newest displaced"):
        module._reconcile_target(
            repository_target(module),
            verify_only=False,
            expected_main_sha="a" * 40,
        )
    assert any(call[0] == "HISTORY" for call in calls)


def test_ambiguous_put_without_history_guard_is_rejected(monkeypatch) -> None:
    """Internal callers cannot turn a timed-out unguarded mutation into a claimed success."""

    module = load_module()
    target = repository_target(module)
    desired = module._desired_payload(live_payload(), target)
    with pytest.raises(module.RulesetGovernanceError, match="requires protected-main history guard"):
        module._confirm_ambiguous_put(
            target,
            baseline_version=1,
            desired=desired,
            expected_main_sha=None,
        )


def test_reconcile_timeout_without_history_baseline_fails_closed(monkeypatch) -> None:
    """A direct unguarded internal mutation still rejects an ambiguous PUT timeout."""

    module = load_module()
    target = repository_target(module)
    first = live_payload()
    get_count = 0
    monkeypatch.setattr(module, "_assert_canonical_governance", lambda *_args: None)

    def fake_api(method, endpoint, *, body=None):
        nonlocal get_count
        if method == "GET" and endpoint == target.endpoint:
            get_count += 1
            return first
        if method == "PUT" and endpoint == target.endpoint:
            raise subprocess.TimeoutExpired(cmd=["gh", "api"], timeout=30)
        raise AssertionError((method, endpoint, body))

    monkeypatch.setattr(module, "_gh_api", fake_api)
    with pytest.raises(module.RulesetGovernanceError, match="requires protected-main history guard"):
        module._reconcile_target(target, verify_only=False)
    assert get_count == 2


def test_transport_timeout_distinguishes_reads_from_ambiguous_puts(monkeypatch) -> None:
    """Read timeouts become redacted domain errors while PUT timeouts remain distinguishable."""

    module = load_module()

    def timeout_run(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd=["gh", "api"], timeout=30)

    monkeypatch.setattr(subprocess, "run", timeout_run)
    with pytest.raises(module.RulesetGovernanceError, match="request timed out"):
        module._run_gh_json("GET", "repos/ContextualWisdomLab/.github/rulesets/17921150")
    with pytest.raises(subprocess.TimeoutExpired):
        module._run_gh_json(
            "PUT",
            "repos/ContextualWisdomLab/.github/rulesets/17921150",
            body={"name": "Lock default branch"},
        )


def test_recovery_timeout_without_history_fails_closed(monkeypatch) -> None:
    """An ambiguous recovery timeout cannot proceed when immutable history is unavailable."""

    module = load_module()
    target = repository_target(module)
    current = live_payload()
    displaced = {**current, "name": "Admin predecessor"}
    monkeypatch.setattr(module, "_history_version_state", lambda *_args: displaced)
    monkeypatch.setattr(module, "_assert_current_main", lambda *_args: None)
    monkeypatch.setattr(
        module,
        "_gh_api",
        lambda method, endpoint, **_kwargs: current
        if method == "GET"
        else (_ for _ in ()).throw(subprocess.TimeoutExpired(cmd=["gh", "api"], timeout=30)),
    )
    monkeypatch.setattr(module, "_gh_api_list", lambda *_args: [])

    with pytest.raises(module.RulesetGovernanceError, match="exposed no history"):
        module._recover_displaced_history_state(
            target,
            current_version=10,
            current_payload=module._editable_projection(current),
            displaced_version=9,
            expected_main_sha="a" * 40,
        )


def test_recovery_timeout_before_acceptance_fails_after_settlement_without_retry(monkeypatch) -> None:
    """An absent recovery transition fails closed after settlement without issuing another PUT."""

    module = load_module()
    target = repository_target(module)
    current = live_payload()
    displaced = {**current, "name": "Admin predecessor"}
    put_count = 0
    history_reads = 0
    sleep_calls = 0
    monkeypatch.setattr(module, "_history_version_state", lambda *_args: displaced)
    monkeypatch.setattr(module, "_assert_current_main", lambda *_args: None)

    def fake_sleep(_seconds):
        nonlocal sleep_calls
        sleep_calls += 1

    def fake_api(method, endpoint, **_kwargs):
        nonlocal put_count
        if method == "GET":
            return current
        if method == "PUT":
            put_count += 1
            raise subprocess.TimeoutExpired(cmd=["gh", "api"], timeout=30)
        raise AssertionError((method, endpoint))

    def fake_history(*_args):
        nonlocal history_reads
        history_reads += 1
        return [{"version_id": 10}]

    monkeypatch.setattr(module.time, "sleep", fake_sleep)
    monkeypatch.setattr(module, "_gh_api", fake_api)
    monkeypatch.setattr(module, "_gh_api_list", fake_history)

    with pytest.raises(
        module.RulesetGovernanceError,
        match="ambiguous ruleset recovery PUT outcome remains unresolved after settlement window",
    ):
        module._recover_displaced_history_state(
            target,
            current_version=10,
            current_payload=module._editable_projection(current),
            displaced_version=9,
            expected_main_sha="a" * 40,
        )
    assert put_count == 1
    assert history_reads == module.AMBIGUOUS_WRITE_SETTLEMENT_POLLS
    assert sleep_calls == module.AMBIGUOUS_WRITE_SETTLEMENT_POLLS - 1


def test_recovery_timeout_with_new_version_requires_predecessor(monkeypatch) -> None:
    """A visible timed-out recovery write still needs its immutable predecessor proof."""

    module = load_module()
    target = repository_target(module)
    current = live_payload()
    displaced = {**current, "name": "Admin predecessor"}
    monkeypatch.setattr(module, "_history_version_state", lambda *_args: displaced)
    monkeypatch.setattr(module, "_assert_current_main", lambda *_args: None)
    monkeypatch.setattr(
        module,
        "_gh_api",
        lambda method, endpoint, **_kwargs: current
        if method == "GET"
        else (_ for _ in ()).throw(subprocess.TimeoutExpired(cmd=["gh", "api"], timeout=30)),
    )
    monkeypatch.setattr(module, "_gh_api_list", lambda *_args: [{"version_id": 11}])

    with pytest.raises(module.RulesetGovernanceError, match="exposed no predecessor"):
        module._recover_displaced_history_state(
            target,
            current_version=10,
            current_payload=module._editable_projection(current),
            displaced_version=9,
            expected_main_sha="a" * 40,
        )


def test_recovery_timeout_refuses_unexpected_newer_history_state(monkeypatch) -> None:
    """A timed-out recovery never overwrites a newer state that is not its intended restore body."""

    module = load_module()
    target = repository_target(module)
    current = live_payload()
    displaced = {**current, "name": "Admin predecessor"}
    unrelated = {**current, "name": "Newer administrator state"}
    monkeypatch.setattr(module, "_assert_current_main", lambda *_args: None)

    def history_state(_target, version_id):
        return unrelated if version_id == 11 else displaced

    monkeypatch.setattr(module, "_history_version_state", history_state)
    monkeypatch.setattr(
        module,
        "_gh_api",
        lambda method, endpoint, **_kwargs: current
        if method == "GET"
        else (_ for _ in ()).throw(subprocess.TimeoutExpired(cmd=["gh", "api"], timeout=30)),
    )
    monkeypatch.setattr(
        module,
        "_gh_api_list",
        lambda *_args: [{"version_id": 11}, {"version_id": 10}],
    )

    with pytest.raises(
        module.RulesetGovernanceError,
        match="ambiguous ruleset recovery PUT left a newer state after settlement window; refusing overwrite",
    ):
        module._recover_displaced_history_state(
            target,
            current_version=10,
            current_payload=module._editable_projection(current),
            displaced_version=9,
            expected_main_sha="a" * 40,
        )


def test_recovery_timeout_after_acceptance_without_collision_converges(monkeypatch) -> None:
    """A timed-out recovery accepted by GitHub completes only with matching history and live state."""

    module = load_module()
    target = repository_target(module)
    current = live_payload()
    displaced = {**current, "name": "Admin predecessor", "enforcement": "evaluate"}
    get_count = 0
    monkeypatch.setattr(module, "_assert_current_main", lambda *_args: None)
    monkeypatch.setattr(module, "_history_version_state", lambda *_args: displaced)

    def fake_api(method, endpoint, **_kwargs):
        nonlocal get_count
        if method == "GET":
            get_count += 1
            return current if get_count == 1 else displaced
        if method == "PUT":
            raise subprocess.TimeoutExpired(cmd=["gh", "api"], timeout=30)
        raise AssertionError((method, endpoint))

    monkeypatch.setattr(module, "_gh_api", fake_api)
    monkeypatch.setattr(
        module,
        "_gh_api_list",
        lambda *_args: [{"version_id": 11}, {"version_id": 10}],
    )

    module._recover_displaced_history_state(
        target,
        current_version=10,
        current_payload=module._editable_projection(current),
        displaced_version=9,
        expected_main_sha="a" * 40,
    )


def test_recovery_timeout_after_acceptance_with_collision_continues_chain(monkeypatch) -> None:
    """A timed-out restore that displaced another version continues to the newest predecessor."""

    module = load_module()
    target = repository_target(module)
    current = live_payload()
    first_restore = {**current, "name": "First restore", "enforcement": "evaluate"}
    second_restore = {**current, "name": "Newest displaced", "enforcement": "evaluate"}
    get_states = iter([current, first_restore, first_restore, second_restore])
    put_count = 0
    list_count = 0
    monkeypatch.setattr(module, "_assert_current_main", lambda *_args: None)

    def history_state(_target, version_id):
        return {9: first_restore, 8: second_restore, 11: first_restore, 12: second_restore}[version_id]

    def fake_api(method, endpoint, **_kwargs):
        nonlocal put_count
        if method == "GET":
            return next(get_states)
        if method == "PUT":
            put_count += 1
            if put_count == 1:
                raise subprocess.TimeoutExpired(cmd=["gh", "api"], timeout=30)
            return {}
        raise AssertionError((method, endpoint))

    def fake_history(*_args):
        nonlocal list_count
        list_count += 1
        if list_count == 1:
            return [{"version_id": 11}, {"version_id": 8}]
        return [{"version_id": 12}, {"version_id": 11}]

    monkeypatch.setattr(module, "_history_version_state", history_state)
    monkeypatch.setattr(module, "_gh_api", fake_api)
    monkeypatch.setattr(module, "_gh_api_list", fake_history)

    module._recover_displaced_history_state(
        target,
        current_version=10,
        current_payload=module._editable_projection(current),
        displaced_version=9,
        expected_main_sha="a" * 40,
    )
    assert put_count == 2


def test_manual_mutation_requires_exact_protected_main_guard(monkeypatch) -> None:
    """Non-Actions operators cannot invoke the weaker mutation mode without a main SHA guard."""

    module = load_module()
    target = repository_target(module)
    monkeypatch.setenv("GH_TOKEN", "redacted-test-token")
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setattr(module, "load_manifest", lambda _path: (target,))
    monkeypatch.setattr(module, "reconcile", lambda *_args, **_kwargs: 0)

    with pytest.raises(module.RulesetGovernanceError, match="expected protected main SHA"):
        module.main([])


def test_verify_only_remains_available_without_mutation_main_guard(monkeypatch, capsys) -> None:
    """Read-only live verification remains usable without granting mutation authority."""

    module = load_module()
    target = repository_target(module)
    observed: list[tuple] = []
    monkeypatch.setenv("GH_TOKEN", "redacted-test-token")
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setattr(module, "load_manifest", lambda _path: (target,))

    def fake_reconcile(targets, *, verify_only, expected_main_sha=None):
        observed.append((targets, verify_only, expected_main_sha))
        return 0

    monkeypatch.setattr(module, "reconcile", fake_reconcile)
    assert module.main(["--verify-only"]) == 0
    assert observed == [((target,), True, None)]
    assert "verified 1 ruleset governance targets" in capsys.readouterr().out