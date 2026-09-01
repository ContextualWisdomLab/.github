"""Regressions for adversarial review findings on ruleset reconciliation."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "ci" / "reconcile_ruleset_governance.py"
WORKFLOW = ROOT / ".github" / "workflows" / "ruleset-governance-reconcile.yml"
DOCTORING = ROOT / "docs" / "doctoring" / "ruleset-owner-plane-reconciliation.md"
SPEC = importlib.util.spec_from_file_location("ruleset_governance_review", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def test_stale_main_revision_fails_before_any_ruleset_mutation(monkeypatch) -> None:
    """A resumed owner-plane run cannot apply policy from an obsolete main SHA."""

    target = module.RulesetTarget(
        "repository",
        "ContextualWisdomLab",
        ".github",
        17921150,
        "Lock default branch",
    )
    live = {
        "id": target.ruleset_id,
        "name": target.name,
        "target": "branch",
        "source_type": target.source_type,
        "source": target.source,
        "enforcement": "active",
        "bypass_actors": [{"actor_id": None, "actor_type": "OrganizationAdmin", "bypass_mode": "always"}],
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
                    "require_extra_approval_for_unattributed_changes": True,
                    "allowed_merge_methods": ["merge", "squash", "rebase"],
                },
            },
        ],
    }
    calls: list[str] = []

    monkeypatch.setattr(module, "_gh_api", lambda method, endpoint, **kwargs: calls.append(method) or live)
    monkeypatch.setattr(module, "_current_main_sha", lambda: "b" * 40)

    with pytest.raises(module.RulesetGovernanceError, match="protected main advanced"):
        module._reconcile_target(
            target,
            verify_only=False,
            expected_main_sha="a" * 40,
        )
    assert calls == ["GET"]


def test_owner_plane_workflow_supersedes_stale_runs_and_quotes_main_sha() -> None:
    """Only the newest trusted-main owner-plane run may reach mutation."""

    text = WORKFLOW.read_text(encoding="utf-8")
    assert "cancel-in-progress: true" in text
    assert "EXPECTED_MAIN_SHA: ${{ github.sha }}" in text
    assert '--expected-main-sha "$EXPECTED_MAIN_SHA"' in text
    assert "github.event_name != 'pull_request'" in text


def test_docs_state_github_has_no_ruleset_put_compare_and_swap() -> None:
    """Doctoring must not claim an atomic compare-and-swap GitHub does not provide."""

    text = DOCTORING.read_text(encoding="utf-8")
    assert "does not support conditional unsafe REST updates" in text
    assert "exclusive owner-plane maintenance" in text
    assert "cannot make the final GET-to-PUT interval atomic" in text


def test_module_docstring_does_not_promise_impossible_atomicity() -> None:
    """Production documentation must describe best-effort drift checks, not CAS semantics."""

    assert "never silently overwritten" not in (module.__doc__ or "")
