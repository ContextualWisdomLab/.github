"""Regressions for adversarial review findings on ruleset reconciliation."""

from __future__ import annotations

import importlib.util
import json
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


def _target():
    """Return the reviewed repository ruleset target used by race tests."""

    return module.RulesetTarget(
        "repository",
        "ContextualWisdomLab",
        ".github",
        17921150,
        "Lock default branch",
    )


def _live() -> dict[str, object]:
    """Return one live ruleset with only the reviewed merge-method drift."""

    target = _target()
    return {
        "id": target.ruleset_id,
        "name": target.name,
        "target": "branch",
        "source_type": target.source_type,
        "source": target.source,
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
                    "require_extra_approval_for_unattributed_changes": True,
                    "allowed_merge_methods": ["merge", "squash", "rebase"],
                },
            },
        ],
    }


def _manifest(tmp_path: Path) -> Path:
    """Write the exact two-target manifest accepted by the production parser."""

    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "organization": "ContextualWisdomLab",
                "targets": [
                    {
                        "scope": "repository",
                        "owner": "ContextualWisdomLab",
                        "repository": ".github",
                        "ruleset_id": 17921150,
                        "name": "Lock default branch",
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
        ),
        encoding="utf-8",
    )
    return path


def test_stale_main_revision_fails_before_any_ruleset_mutation(monkeypatch) -> None:
    """A resumed owner-plane run cannot apply policy from an obsolete main SHA."""

    calls: list[str] = []
    monkeypatch.setattr(
        module,
        "_gh_api",
        lambda method, endpoint, **kwargs: calls.append(method) or _live(),
    )
    monkeypatch.setattr(module, "_current_main_sha", lambda: "b" * 40)

    with pytest.raises(module.RulesetGovernanceError, match="protected main advanced"):
        module._reconcile_target(
            _target(),
            verify_only=False,
            expected_main_sha="a" * 40,
        )
    assert calls == ["GET"]


def test_current_main_guard_covers_live_success_and_malformed_evidence(monkeypatch) -> None:
    """The live ref reader accepts one exact SHA and rejects malformed ref evidence."""

    monkeypatch.setattr(
        module,
        "_gh_api",
        lambda *_args, **_kwargs: {"object": {"sha": "A" * 40}},
    )
    assert module._current_main_sha() == "a" * 40
    module._assert_current_main("a" * 40)

    with pytest.raises(module.RulesetGovernanceError, match="expected protected main SHA"):
        module._assert_current_main("BAD")

    monkeypatch.setattr(
        module,
        "_gh_api",
        lambda *_args, **_kwargs: {"object": {"sha": "not-a-sha"}},
    )
    with pytest.raises(module.RulesetGovernanceError, match="malformed SHA"):
        module._current_main_sha()

    monkeypatch.setattr(module, "_gh_api", lambda *_args, **_kwargs: {"object": []})
    with pytest.raises(module.RulesetGovernanceError, match="main ref object"):
        module._current_main_sha()


def test_current_main_is_rechecked_around_put_and_after_convergence(monkeypatch) -> None:
    """Stable protected main is checked before final read, PUT, and completion."""

    first = _live()
    desired = module._desired_payload(first, _target())
    converged = {**first, **desired}
    replies = iter([first, first, {}, converged])
    checks: list[str] = []
    monkeypatch.setattr(module, "_gh_api", lambda *args, **kwargs: next(replies))
    monkeypatch.setattr(
        module,
        "_current_main_sha",
        lambda: checks.append("main") or "a" * 40,
    )

    assert module._reconcile_target(
        _target(),
        verify_only=False,
        expected_main_sha="a" * 40,
    ) is True
    assert checks == ["main", "main", "main"]


def test_actions_apply_requires_and_forwards_expected_main_sha(tmp_path, monkeypatch) -> None:
    """The privileged Actions CLI path cannot silently omit its protected-main identity."""

    manifest = _manifest(tmp_path)
    monkeypatch.setenv("GH_TOKEN", "protected")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    with pytest.raises(module.RulesetGovernanceError, match="expected protected main SHA"):
        module.main(["--manifest", str(manifest)])

    seen: list[tuple[bool, str | None]] = []

    def fake_reconcile(targets, *, verify_only, expected_main_sha=None):
        assert len(targets) == 2
        seen.append((verify_only, expected_main_sha))
        return 0

    monkeypatch.setattr(module, "reconcile", fake_reconcile)
    assert module.main(
        ["--manifest", str(manifest), "--expected-main-sha", "a" * 40]
    ) == 0
    assert seen == [(False, "a" * 40)]


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
