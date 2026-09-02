"""Adversarial regressions for the third ruleset-governance review round."""

from __future__ import annotations

import importlib.util
import json
import math
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts" / "ci" / "reconcile_ruleset_governance.py"
WORKFLOW = ROOT / ".github" / "workflows" / "ruleset-governance-reconcile.yml"


def load_module():
    """Load the production reconciler from the exact checkout."""

    spec = importlib.util.spec_from_file_location("ruleset_governance_round3", SOURCE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def repository_target(module):
    """Return the documented repository-owned governance target."""

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


def test_nonzero_put_transport_result_is_ambiguous_but_read_failure_is_not(monkeypatch) -> None:
    """A failed PUT transport cannot prove server rejection, while read failures stay ordinary errors."""

    module = load_module()
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=1,
            stdout="possibly accepted before connection loss",
            stderr="transport failed",
        ),
    )

    with pytest.raises(module.AmbiguousRulesetWriteError):
        module._run_gh_json("PUT", "repos/ContextualWisdomLab/.github/rulesets/17921150", body={"x": 1})
    with pytest.raises(module.RulesetGovernanceError, match="GitHub API request failed"):
        module._run_gh_json("GET", "repos/ContextualWisdomLab/.github/rulesets/17921150")


def test_delayed_ambiguous_write_is_observed_after_baseline_only_first_poll(monkeypatch) -> None:
    """A first baseline-only history observation cannot be treated as definitive rejection."""

    module = load_module()
    target = repository_target(module)
    first = live_payload()
    desired = module._desired_payload(first, target)
    converged = {**first, **desired}
    history_reads = iter(
        [
            [{"version_id": 41}, {"version_id": 40}],
            [{"version_id": 42}, {"version_id": 41}],
        ]
    )
    sleeps: list[float] = []

    monkeypatch.setattr(module, "_assert_current_main", lambda *_args: None)
    monkeypatch.setattr(module, "_assert_canonical_governance", lambda *_args: None)
    monkeypatch.setattr(module, "_gh_api_list", lambda *_args: next(history_reads))
    monkeypatch.setattr(module, "_history_version_state", lambda _target, version: converged if version == 42 else first)
    monkeypatch.setattr(module, "_gh_api", lambda method, endpoint, **_kwargs: converged)
    monkeypatch.setattr(module.time, "sleep", lambda seconds: sleeps.append(seconds))

    observed = module._confirm_ambiguous_put(
        target,
        baseline_version=41,
        desired=desired,
        expected_main_sha="a" * 40,
    )
    assert module._editable_projection(observed) == desired
    assert sleeps


def test_baseline_only_settlement_exhaustion_fails_as_unresolved_not_rejected(monkeypatch) -> None:
    """A bounded settlement horizon may fail closed, but cannot claim a delayed write was rejected."""

    module = load_module()
    target = repository_target(module)
    first = live_payload()
    desired = module._desired_payload(first, target)
    monkeypatch.setattr(module, "_assert_current_main", lambda *_args: None)
    monkeypatch.setattr(
        module,
        "_gh_api_list",
        lambda *_args: [{"version_id": 41}, {"version_id": 40}],
    )
    monkeypatch.setattr(module, "_gh_api", lambda method, endpoint, **_kwargs: first)
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)

    with pytest.raises(module.RulesetGovernanceError, match="outcome remains unresolved"):
        module._confirm_ambiguous_put(
            target,
            baseline_version=41,
            desired=desired,
            expected_main_sha="a" * 40,
        )


def test_manifest_is_pinned_to_the_two_documented_privileged_targets(tmp_path: Path) -> None:
    """Reviewed manifest structure cannot redirect Administration-write authority to another target."""

    module = load_module()
    manifest = {
        "schema_version": 1,
        "organization": "ContextualWisdomLab",
        "targets": [
            {
                "scope": "repository",
                "owner": "ContextualWisdomLab",
                "repository": "another-repository",
                "ruleset_id": 99999999,
                "name": "Another privileged ruleset",
            },
            {
                "scope": "organization",
                "owner": "ContextualWisdomLab",
                "repository": None,
                "ruleset_id": 18156473,
                "name": "CWL Central required workflows",
            },
        ],
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(module.RulesetGovernanceError, match="exact reviewed governance targets"):
        module.load_manifest(path)


def test_workflow_covers_runtime_auditor_round3_suite_and_disabled_status() -> None:
    """Runtime dependencies trigger the focused gate and disabled schedules remain visible cheaply."""

    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert workflow.count('"scripts/ci/audit_central_required_workflows.py"') >= 2
    assert workflow.count('"tests/test_ruleset_governance_review_round3.py"') >= 2
    assert "tests/test_ruleset_governance_review_round3.py" in workflow.split("python -m coverage run", 1)[1]
    assert "report-disabled:" in workflow
    assert "CWL_RULESET_RECONCILE_ENABLED != 'true'" in workflow
    assert "Ruleset reconciliation is disabled" in workflow


def test_apply_timeout_covers_derived_worst_case_critical_section() -> None:
    """Actions cannot terminate the owner-plane process before its derived critical-section budget."""

    module = load_module()
    workflow = WORKFLOW.read_text(encoding="utf-8")
    apply_section = workflow.split("  apply:\n", 1)[1]
    timeout_match = re.search(r"timeout-minutes:\s*(\d+)", apply_section)
    assert timeout_match is not None
    configured_minutes = int(timeout_match.group(1))
    required_minutes = math.ceil(module.worst_case_apply_seconds(target_count=2) / 60)
    assert configured_minutes >= required_minutes
