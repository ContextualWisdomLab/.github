"""Regress post-PUT cleanup when protected main advances after mutation starts."""

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

    spec = importlib.util.spec_from_file_location("ruleset_governance_post_put_cleanup", SOURCE)
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
    """Return one live-shaped repository ruleset with reviewed governance drift."""

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


def test_ambiguous_put_settles_before_stale_main_failure(monkeypatch) -> None:
    """Main advancement after PUT cannot abort immutable-history settlement."""

    module = load_module()
    target = repository_target(module)
    first = live_payload()
    desired = module._desired_payload(first, target)
    converged = {**first, **desired}
    main_checks = 0
    history_reads = 0
    get_count = 0
    put_bodies: list[dict] = []

    monkeypatch.setattr(module, "_assert_canonical_governance", lambda *_args: None)
    monkeypatch.setattr(module, "_latest_history_version", lambda *_args: 41)
    monkeypatch.setattr(module, "_history_version_state", lambda *_args: converged)

    def assert_main(_expected_sha: str) -> None:
        nonlocal main_checks
        main_checks += 1
        if main_checks > 2:
            raise module.RulesetGovernanceError("protected main advanced")

    def history(*_args):
        nonlocal history_reads
        history_reads += 1
        return [{"version_id": 42}, {"version_id": 41}]

    def api(method, endpoint, *, body=None):
        nonlocal get_count
        if method == "GET" and endpoint == target.endpoint:
            get_count += 1
            return first if get_count <= 2 else converged
        if method == "PUT" and endpoint == target.endpoint:
            assert body is not None
            put_bodies.append(body)
            raise module.AmbiguousRulesetWriteError("accepted before transport loss")
        raise AssertionError((method, endpoint))

    monkeypatch.setattr(module, "_assert_current_main", assert_main)
    monkeypatch.setattr(module, "_gh_api_list", history)
    monkeypatch.setattr(module, "_gh_api", api)

    with pytest.raises(module.RulesetGovernanceError, match="protected main advanced"):
        module._reconcile_target(
            target,
            verify_only=False,
            expected_main_sha="a" * 40,
        )

    assert history_reads == 1
    assert main_checks == 3
    assert put_bodies == [desired]


def test_ambiguous_put_restores_displaced_admin_after_main_advances(monkeypatch) -> None:
    """Cleanup restores the displaced predecessor even after source freshness changes."""

    module = load_module()
    target = repository_target(module)
    first = live_payload()
    desired = module._desired_payload(first, target)
    converged = {**first, **desired}
    administrator = {
        **first,
        "name": "Administrator intervening state",
        "enforcement": "evaluate",
    }
    main_checks = 0
    get_count = 0
    history_reads = 0
    put_bodies: list[dict] = []

    monkeypatch.setattr(module, "_assert_canonical_governance", lambda *_args: None)
    monkeypatch.setattr(module, "_latest_history_version", lambda *_args: 41)

    def assert_main(_expected_sha: str) -> None:
        nonlocal main_checks
        main_checks += 1
        if main_checks > 2:
            raise module.RulesetGovernanceError("protected main advanced")

    def history(*_args):
        nonlocal history_reads
        history_reads += 1
        if history_reads == 1:
            return [
                {"version_id": 43},
                {"version_id": 42},
                {"version_id": 41},
            ]
        return [{"version_id": 44}, {"version_id": 43}]

    def history_state(_target, version_id):
        return {42: administrator, 43: converged, 44: administrator}[version_id]

    def api(method, endpoint, *, body=None):
        nonlocal get_count
        if method == "GET" and endpoint == target.endpoint:
            get_count += 1
            if get_count <= 2:
                return first
            if get_count == 3:
                return converged
            return administrator
        if method == "PUT" and endpoint == target.endpoint:
            assert body is not None
            put_bodies.append(body)
            if len(put_bodies) == 1:
                raise module.AmbiguousRulesetWriteError("accepted before transport loss")
            return {}
        raise AssertionError((method, endpoint))

    monkeypatch.setattr(module, "_assert_current_main", assert_main)
    monkeypatch.setattr(module, "_gh_api_list", history)
    monkeypatch.setattr(module, "_history_version_state", history_state)
    monkeypatch.setattr(module, "_gh_api", api)

    with pytest.raises(
        module.RulesetGovernanceError,
        match="restored newest displaced administrator state",
    ):
        module._reconcile_target(
            target,
            verify_only=False,
            expected_main_sha="a" * 40,
        )

    assert main_checks == 2
    assert history_reads == 2
    assert put_bodies == [desired, module._editable_projection(administrator)]


def test_successful_put_restores_displaced_admin_after_main_advances(monkeypatch) -> None:
    """A successful PUT also finishes predecessor restoration before stale-main failure."""

    module = load_module()
    target = repository_target(module)
    first = live_payload()
    desired = module._desired_payload(first, target)
    converged = {**first, **desired}
    administrator = {
        **first,
        "name": "Administrator intervening state",
        "enforcement": "evaluate",
    }
    main_checks = 0
    get_count = 0
    history_reads = 0
    put_bodies: list[dict] = []

    monkeypatch.setattr(module, "_assert_canonical_governance", lambda *_args: None)
    monkeypatch.setattr(module, "_latest_history_version", lambda *_args: 41)

    def assert_main(_expected_sha: str) -> None:
        nonlocal main_checks
        main_checks += 1
        if main_checks > 2:
            raise module.RulesetGovernanceError("protected main advanced")

    def history(*_args):
        nonlocal history_reads
        history_reads += 1
        if history_reads == 1:
            return [
                {"version_id": 43},
                {"version_id": 42},
                {"version_id": 41},
            ]
        return [{"version_id": 44}, {"version_id": 43}]

    def history_state(_target, version_id):
        return {42: administrator, 43: converged, 44: administrator}[version_id]

    def api(method, endpoint, *, body=None):
        nonlocal get_count
        if method == "GET" and endpoint == target.endpoint:
            get_count += 1
            if get_count <= 2:
                return first
            if get_count <= 4:
                return converged
            return administrator
        if method == "PUT" and endpoint == target.endpoint:
            assert body is not None
            put_bodies.append(body)
            return {}
        raise AssertionError((method, endpoint))

    monkeypatch.setattr(module, "_assert_current_main", assert_main)
    monkeypatch.setattr(module, "_gh_api_list", history)
    monkeypatch.setattr(module, "_history_version_state", history_state)
    monkeypatch.setattr(module, "_gh_api", api)

    with pytest.raises(
        module.RulesetGovernanceError,
        match="restored newest displaced administrator state",
    ):
        module._reconcile_target(
            target,
            verify_only=False,
            expected_main_sha="a" * 40,
        )

    assert main_checks == 2
    assert history_reads == 2
    assert put_bodies == [desired, module._editable_projection(administrator)]


def test_ambiguous_recovery_rejects_history_rewrite_after_settlement(monkeypatch) -> None:
    """A history rewrite after settlement is detected before restored state is trusted."""

    module = load_module()
    target = repository_target(module)
    current = live_payload()
    displaced = {**current, "name": "Administrator predecessor", "enforcement": "evaluate"}
    rewritten = {**current, "name": "Newer administrator state"}
    put_count = 0

    def history_state(_target, version_id):
        if version_id == 9:
            return displaced
        if version_id == 11:
            return rewritten
        raise AssertionError(version_id)

    def api(method, endpoint, *, body=None):
        nonlocal put_count
        if method == "GET" and endpoint == target.endpoint:
            return current
        if method == "PUT" and endpoint == target.endpoint:
            put_count += 1
            raise subprocess.TimeoutExpired(cmd=["gh", "api"], timeout=30)
        raise AssertionError((method, endpoint))

    monkeypatch.setattr(module, "_history_version_state", history_state)
    monkeypatch.setattr(module, "_assert_current_main", lambda *_args: None)
    monkeypatch.setattr(module, "_gh_api", api)
    monkeypatch.setattr(
        module,
        "_settle_ambiguous_recovery_history",
        lambda *_args, **_kwargs: [{"version_id": 11}, {"version_id": 10}],
    )

    with pytest.raises(
        module.RulesetGovernanceError,
        match="ambiguous ruleset recovery PUT left a newer state; refusing overwrite",
    ):
        module._recover_displaced_history_state(
            target,
            current_version=10,
            current_payload=module._editable_projection(current),
            displaced_version=9,
            expected_main_sha="a" * 40,
        )

    assert put_count == 1
