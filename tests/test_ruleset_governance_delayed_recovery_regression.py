"""Regress delayed ambiguous ruleset recovery without duplicate privileged writes."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts" / "ci" / "reconcile_ruleset_governance.py"


def load_module():
    """Load the exact production ruleset reconciler from the checkout."""

    spec = importlib.util.spec_from_file_location(
        "ruleset_governance_delayed_recovery_regression", SOURCE
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def repository_target(module):
    """Return the exact central repository ruleset target."""

    return module.RulesetTarget(
        scope="repository",
        owner="ContextualWisdomLab",
        repository=".github",
        ruleset_id=17921150,
        name="Lock default branch",
    )


def live_payload() -> dict:
    """Return one live-shaped ruleset state used by the recovery regression."""

    return {
        "id": 17921150,
        "name": "Lock default branch",
        "target": "branch",
        "source_type": "Repository",
        "source": "ContextualWisdomLab/.github",
        "enforcement": "active",
        "bypass_actors": [],
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
                    "allowed_merge_methods": ["merge", "squash"],
                },
            },
        ],
    }


def test_delayed_recovery_acceptance_settles_before_any_second_put(monkeypatch) -> None:
    """A delayed recovery commit must become visible before another PUT is attempted."""

    module = load_module()
    target = repository_target(module)
    current = live_payload()
    displaced = {**current, "name": "Administrator predecessor", "enforcement": "evaluate"}
    history_reads = 0
    put_count = 0

    monkeypatch.setattr(module, "_assert_current_main", lambda *_args: None)
    monkeypatch.setattr(module.time, "sleep", lambda *_args: None)
    monkeypatch.setattr(module, "_history_version_state", lambda *_args: displaced)

    def fake_history(*_args):
        nonlocal history_reads
        history_reads += 1
        if history_reads == 1:
            return [{"version_id": 10}]
        return [{"version_id": 11}, {"version_id": 10}]

    def fake_api(method, endpoint, **_kwargs):
        nonlocal put_count
        if method == "GET" and endpoint == target.endpoint:
            return displaced if history_reads >= 2 else current
        if method == "PUT" and endpoint == target.endpoint:
            put_count += 1
            raise subprocess.TimeoutExpired(cmd=["gh", "api"], timeout=30)
        raise AssertionError((method, endpoint))

    monkeypatch.setattr(module, "_gh_api_list", fake_history)
    monkeypatch.setattr(module, "_gh_api", fake_api)

    module._recover_displaced_history_state(
        target,
        current_version=10,
        current_payload=module._editable_projection(current),
        displaced_version=9,
        expected_main_sha="a" * 40,
    )

    assert history_reads == 2
    assert put_count == 1


def test_recovery_chain_exhaustion_fails_closed_after_bounded_attempts(monkeypatch) -> None:
    """A perpetual collision chain reaches the bounded terminal error, never an unbounded loop."""

    module = load_module()
    target = repository_target(module)
    live_state = live_payload()
    history_reads = 0
    put_count = 0

    def payload_for(version: int) -> dict:
        return {
            **live_payload(),
            "name": f"Administrator predecessor {version}",
            "enforcement": "evaluate",
        }

    monkeypatch.setattr(module, "_assert_current_main", lambda *_args: None)

    def fake_history_state(_target, version):
        if version >= 100:
            return live_state
        return payload_for(version)

    def fake_history(*_args):
        nonlocal history_reads
        index = history_reads
        history_reads += 1
        return [
            {"version_id": 100 + index},
            {"version_id": 8 - index},
        ]

    def fake_api(method, endpoint, *, body=None):
        nonlocal live_state, put_count
        if method == "GET" and endpoint == target.endpoint:
            return live_state
        if method == "PUT" and endpoint == target.endpoint:
            assert body is not None
            put_count += 1
            live_state = body
            return {}
        raise AssertionError((method, endpoint))

    monkeypatch.setattr(module, "_history_version_state", fake_history_state)
    monkeypatch.setattr(module, "_gh_api_list", fake_history)
    monkeypatch.setattr(module, "_gh_api", fake_api)

    with pytest.raises(module.RulesetGovernanceError, match="exceeded bounded attempts"):
        module._recover_displaced_history_state(
            target,
            current_version=10,
            current_payload=module._editable_projection(live_state),
            displaced_version=9,
            expected_main_sha="a" * 40,
        )

    assert history_reads == module.COLLISION_RECOVERY_LIMIT
    assert put_count == module.COLLISION_RECOVERY_LIMIT


def test_verify_only_reconcile_dispatches_without_mutation_sha(monkeypatch) -> None:
    """Read-only reconciliation keeps its documented no-mutation-SHA path covered."""

    module = load_module()
    target = repository_target(module)
    calls: list[tuple[str, bool, str | None]] = []

    def fake_reconcile_target(seen_target, *, verify_only, expected_main_sha=None):
        calls.append((seen_target.scope, verify_only, expected_main_sha))
        return False

    monkeypatch.setattr(module, "_reconcile_target", fake_reconcile_target)

    assert module.reconcile((target,), verify_only=True) == 0
    assert calls == [("repository", True, None)]
