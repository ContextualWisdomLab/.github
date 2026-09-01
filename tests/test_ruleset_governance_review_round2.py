"""Second-round and follow-up regressions for ruleset owner-plane reconciliation."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts" / "ci" / "reconcile_ruleset_governance.py"
WORKFLOW = ROOT / ".github" / "workflows" / "ruleset-governance-reconcile.yml"


def load_module():
    """Load the production reconciler from the exact checkout."""
    spec = importlib.util.spec_from_file_location("ruleset_governance_round2", SOURCE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def repository_target(module):
    """Return the exact owner-repository target used by the reviewed manifest."""
    return module.RulesetTarget(
        scope="repository",
        owner="ContextualWisdomLab",
        repository=".github",
        ruleset_id=17921150,
        name="Lock default branch",
    )


def repository_payload(*, include_deletion: bool = True) -> dict:
    """Return a canonical owner-repository ruleset payload for focused regressions."""
    rules = []
    if include_deletion:
        rules.append({"type": "deletion"})
    rules.extend(
        [
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
        ]
    )
    return {
        "id": 17921150,
        "name": "Lock default branch",
        "target": "branch",
        "source_type": "Repository",
        "source": "ContextualWisdomLab/.github",
        "enforcement": "active",
        "bypass_actors": [],
        "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
        "rules": rules,
    }


def historical_state(*, name: str = "Admin renamed", enforcement: str = "evaluate") -> dict:
    """Return a predecessor whose editable identity differs but provenance is unchanged."""
    return {
        "id": 17921150,
        "name": name,
        "target": "branch",
        "source_type": "Repository",
        "source": "ContextualWisdomLab/.github",
        "enforcement": enforcement,
        "bypass_actors": [{"actor_id": 5, "actor_type": "Team", "bypass_mode": "pull_request"}],
        "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
        "rules": [{"type": "non_fast_forward"}],
    }


def test_history_predecessor_allows_editable_name_and_enforcement(monkeypatch) -> None:
    """Collision recovery must be able to restore a legitimate administrator predecessor."""
    module = load_module()
    target = repository_target(module)
    predecessor = historical_state()
    monkeypatch.setattr(
        module,
        "_gh_api",
        lambda method, endpoint, **_kwargs: {"state": predecessor}
        if method == "GET" and endpoint == target.history_version_endpoint(7)
        else (_ for _ in ()).throw(AssertionError((method, endpoint))),
    )

    assert module._history_version_state(target, 7) == predecessor


def test_history_predecessor_still_rejects_wrong_ruleset_provenance(monkeypatch) -> None:
    """Relaxing editable fields must never allow a history record from another ruleset."""
    module = load_module()
    target = repository_target(module)
    predecessor = historical_state()
    predecessor["id"] = 999
    monkeypatch.setattr(
        module,
        "_gh_api",
        lambda *_args, **_kwargs: {"state": predecessor},
    )

    try:
        module._history_version_state(target, 7)
    except module.RulesetGovernanceError as exc:
        assert "identity drift" in str(exc)
    else:
        raise AssertionError("wrong ruleset provenance was accepted")


def test_owner_plane_is_serial_and_disabled_schedule_does_not_consume_runner() -> None:
    """Mutation is non-cancellable while disabled hourly validation skips shared capacity."""
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "cancel-in-progress: ${{ github.event_name == 'pull_request' }}" in text
    validate_block = text.split("jobs:\n  validate:\n", 1)[1].split("\n  apply:\n", 1)[0]
    assert "github.event_name != 'schedule'" in validate_block
    assert "vars.CWL_RULESET_RECONCILE_ENABLED == 'true'" in validate_block
    assert "runs-on: ubuntu-slim" in validate_block
    apply_block = text.split("\n  apply:\n", 1)[1]
    assert "vars.CWL_RULESET_RECONCILE_ENABLED == 'true'" in apply_block
    assert "runs-on: ubuntu-24.04" in apply_block


def test_missing_empty_required_reviewers_is_normalized_to_declared_empty_list() -> None:
    """GitHub may omit an empty reviewer list; desired state must add it instead of aborting."""
    module = load_module()
    live = repository_payload()
    parameters = live["rules"][-1]["parameters"]
    del parameters["required_reviewers"]

    desired = module._desired_payload(live, repository_target(module))

    assert desired["rules"][-1]["parameters"]["required_reviewers"] == []


def test_recovery_revalidates_protected_main_before_every_recovery_put(monkeypatch) -> None:
    """A stale run must stop before a recovery PUT after protected main advances."""
    module = load_module()
    target = repository_target(module)
    current_payload = repository_payload()
    displaced_payload = historical_state()
    puts: list[dict] = []
    main_checks: list[str] = []

    monkeypatch.setattr(module, "_history_version_state", lambda *_args: displaced_payload)

    def fake_api(method, endpoint, *, body=None):
        if method == "GET" and endpoint == target.endpoint:
            return current_payload
        if method == "PUT" and endpoint == target.endpoint:
            puts.append(body)
            return {}
        raise AssertionError((method, endpoint))

    def stale_main(expected_sha: str) -> None:
        main_checks.append(expected_sha)
        raise module.RulesetGovernanceError("protected main advanced")

    monkeypatch.setattr(module, "_gh_api", fake_api)
    monkeypatch.setattr(module, "_assert_current_main", stale_main)

    with pytest.raises(module.RulesetGovernanceError, match="protected main advanced"):
        module._recover_displaced_history_state(
            target,
            current_version=10,
            current_payload=current_payload,
            displaced_version=9,
            expected_main_sha="a" * 40,
        )

    assert main_checks == ["a" * 40]
    assert puts == []


def test_verify_only_rejects_drift_outside_reconciler_projection(monkeypatch) -> None:
    """Canonical audit drift cannot be reported as converged merely because review fields match."""
    module = load_module()
    target = repository_target(module)
    live = repository_payload(include_deletion=False)
    monkeypatch.setattr(module, "_gh_api", lambda *_args, **_kwargs: live)

    with pytest.raises(module.RulesetGovernanceError, match="canonical governance drift"):
        module._reconcile_target(target, verify_only=True)


def test_focused_workflow_runs_every_permanent_governance_regression_suite() -> None:
    """Every permanent audit/reconciler regression participates in path and pytest coverage."""
    text = WORKFLOW.read_text(encoding="utf-8")
    expected = (
        "tests/test_ruleset_governance_reconciliation.py",
        "tests/test_ruleset_governance_review_regressions.py",
        "tests/test_ruleset_governance_review_round2.py",
        "tests/test_central_required_workflow_ruleset_audit.py",
        "tests/test_ruleset_audit_completeness_regression.py",
        "tests/test_ruleset_merge_method_shape_regression.py",
        "tests/test_solo_maintainer_ruleset_policy.py",
    )
    test_command = text.split("-m pytest -q \\\n", 1)[1].split("\n          python -m coverage report", 1)[0]
    for path in expected:
        assert text.count(f'- "{path}"') >= 2
        assert path in test_command
