"""Second-round regressions for ruleset owner-plane collision recovery."""

from __future__ import annotations

import importlib.util
from pathlib import Path


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
