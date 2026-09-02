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


def _converged() -> dict[str, object]:
    """Return the reviewed desired state for the repository target."""

    live = _live()
    return {**live, **module._desired_payload(live, _target())}


def _desired() -> dict[str, object]:
    """Return exactly the editable payload submitted to GitHub PUT."""

    return module._desired_payload(_live(), _target())


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
    desired = _converged()
    replies = iter([first, first, {}, desired])
    checks: list[str] = []
    monkeypatch.setattr(module, "_gh_api", lambda *args, **kwargs: next(replies))
    monkeypatch.setattr(module, "_current_main_sha", lambda: checks.append("main") or "a" * 40)
    monkeypatch.setattr(module, "_latest_history_version", lambda _target: 1)
    monkeypatch.setattr(
        module,
        "_verify_ruleset_history_transition",
        lambda _target, _baseline, _desired, **_kwargs: None,
    )

    assert module._reconcile_target(
        _target(),
        verify_only=False,
        expected_main_sha="a" * 40,
    ) is True
    assert checks == ["main", "main", "main"]


def test_ruleset_target_exposes_history_endpoints() -> None:
    """Collision evidence is fetched from the exact target's immutable history surface."""

    target = _target()
    assert target.history_endpoint == "repos/ContextualWisdomLab/.github/rulesets/17921150/history"
    assert target.history_version_endpoint(7).endswith("/history/7")
    with pytest.raises(module.RulesetGovernanceError, match="version identity is malformed"):
        target.history_version_endpoint(0)


def test_history_transport_and_version_state_are_strict(monkeypatch) -> None:
    """History arrays and version states cross typed, exact-identity trust boundaries."""

    monkeypatch.setattr(module, "_run_gh_json", lambda *_args, **_kwargs: [{"version_id": 1}])
    assert module._gh_api_list("GET", "history") == [{"version_id": 1}]
    monkeypatch.setattr(module, "_run_gh_json", lambda *_args, **_kwargs: {})
    with pytest.raises(module.RulesetGovernanceError, match="must be an array"):
        module._gh_api_list("GET", "history")

    monkeypatch.setattr(module, "_gh_api", lambda *_args, **_kwargs: {"state": _live()})
    assert module._history_version_state(_target(), 4) == _live()
    monkeypatch.setattr(module, "_gh_api", lambda *_args, **_kwargs: {"state": []})
    with pytest.raises(module.RulesetGovernanceError, match="version state must be an object"):
        module._history_version_state(_target(), 4)


def test_latest_history_version_rejects_missing_or_malformed_history(monkeypatch) -> None:
    """Mutation never begins without one trustworthy pre-write history version."""

    monkeypatch.setattr(module, "_gh_api_list", lambda *_args, **_kwargs: [])
    with pytest.raises(module.RulesetGovernanceError, match="ruleset history is empty"):
        module._latest_history_version(_target())

    for invalid in (True, 0):
        monkeypatch.setattr(
            module,
            "_gh_api_list",
            lambda *_args, invalid=invalid, **_kwargs: [{"version_id": invalid}],
        )
        with pytest.raises(module.RulesetGovernanceError, match="version identity is malformed"):
            module._latest_history_version(_target())

    monkeypatch.setattr(module, "_gh_api_list", lambda *_args, **_kwargs: [[]])
    with pytest.raises(module.RulesetGovernanceError, match="history entry must be an object"):
        module._latest_history_version(_target())

    monkeypatch.setattr(module, "_gh_api_list", lambda *_args, **_kwargs: [{"version_id": 12}])
    assert module._latest_history_version(_target()) == 12


def test_history_transition_accepts_exactly_one_new_reviewed_version(monkeypatch) -> None:
    """One new version whose predecessor is the baseline proves no hidden pre-PUT edit."""

    monkeypatch.setattr(
        module,
        "_gh_api_list",
        lambda *_args, **_kwargs: [{"version_id": 8}, {"version_id": 7}],
    )
    monkeypatch.setattr(module, "_history_version_state", lambda _target, version: _converged())
    module._verify_ruleset_history_transition(_target(), 7, _desired())


def test_history_transition_rejects_incomplete_or_inconsistent_evidence(monkeypatch) -> None:
    """Missing predecessor, absent version advance, or mismatched latest state fail closed."""

    desired = _desired()
    monkeypatch.setattr(module, "_gh_api_list", lambda *_args, **_kwargs: [{"version_id": 8}])
    with pytest.raises(module.RulesetGovernanceError, match="did not expose a predecessor"):
        module._verify_ruleset_history_transition(_target(), 7, desired)

    monkeypatch.setattr(
        module,
        "_gh_api_list",
        lambda *_args, **_kwargs: [{"version_id": 7}, {"version_id": 6}],
    )
    with pytest.raises(module.RulesetGovernanceError, match="not visible in history"):
        module._verify_ruleset_history_transition(_target(), 7, desired)

    monkeypatch.setattr(
        module,
        "_gh_api_list",
        lambda *_args, **_kwargs: [{"version_id": 8}, {"version_id": 7}],
    )
    monkeypatch.setattr(module, "_history_version_state", lambda *_args, **_kwargs: _live())
    with pytest.raises(module.RulesetGovernanceError, match="does not match reviewed mutation"):
        module._verify_ruleset_history_transition(_target(), 7, desired)


def test_history_collision_restores_immediate_predecessor_before_failing(monkeypatch) -> None:
    """A hidden pre-PUT administrator edit is restored and history-proven before failing."""

    desired_state = _converged()
    desired = _desired()
    external = _live()
    external["conditions"] = {"ref_name": {"include": ["refs/heads/reviewed"], "exclude": []}}
    histories = iter(
        [
            [{"version_id": 10}, {"version_id": 9}, {"version_id": 7}],
            [{"version_id": 11}, {"version_id": 10}],
        ]
    )
    monkeypatch.setattr(module, "_gh_api_list", lambda *_args, **_kwargs: next(histories))
    monkeypatch.setattr(
        module,
        "_history_version_state",
        lambda _target, version: desired_state if version == 10 else external,
    )
    calls: list[tuple[str, object | None]] = []
    replies = iter([desired_state, {}, external])

    def fake_api(method, endpoint, *, body=None):
        calls.append((method, body))
        return next(replies)

    monkeypatch.setattr(module, "_gh_api", fake_api)
    with pytest.raises(module.RulesetGovernanceError, match="restored newest displaced administrator state"):
        module._verify_ruleset_history_transition(_target(), 7, desired)
    assert [method for method, _body in calls] == ["GET", "PUT", "GET"]
    assert calls[1][1] == module._editable_projection(external)


def test_history_collision_does_not_overwrite_a_newer_post_put_admin_edit(monkeypatch) -> None:
    """If live state advanced again after our PUT, collision recovery preserves that newer state."""

    desired_state = _converged()
    desired = _desired()
    external = _live()
    newer = _live()
    newer["conditions"] = {"ref_name": {"include": ["refs/heads/newer"], "exclude": []}}
    monkeypatch.setattr(
        module,
        "_gh_api_list",
        lambda *_args, **_kwargs: [{"version_id": 10}, {"version_id": 9}],
    )
    monkeypatch.setattr(
        module,
        "_history_version_state",
        lambda _target, version: desired_state if version == 10 else external,
    )
    monkeypatch.setattr(module, "_gh_api", lambda *_args, **_kwargs: newer)
    with pytest.raises(module.RulesetGovernanceError, match="advanced again"):
        module._verify_ruleset_history_transition(_target(), 7, desired)


def test_history_collision_requires_rollback_convergence(monkeypatch) -> None:
    """A failed predecessor restore is surfaced rather than treated as collision recovery."""

    desired_state = _converged()
    desired = _desired()
    external = _live()
    external["conditions"] = {"ref_name": {"include": ["refs/heads/external"], "exclude": []}}
    histories = iter(
        [
            [{"version_id": 10}, {"version_id": 9}],
            [{"version_id": 11}, {"version_id": 10}],
        ]
    )
    monkeypatch.setattr(module, "_gh_api_list", lambda *_args, **_kwargs: next(histories))
    monkeypatch.setattr(
        module,
        "_history_version_state",
        lambda _target, version: desired_state if version == 10 else external,
    )
    replies = iter([desired_state, {}, desired_state])
    monkeypatch.setattr(module, "_gh_api", lambda *_args, **_kwargs: next(replies))
    with pytest.raises(module.RulesetGovernanceError, match="rollback did not converge"):
        module._verify_ruleset_history_transition(_target(), 7, desired)


def test_history_collision_recovers_admin_write_between_recovery_get_and_put(monkeypatch) -> None:
    """A second administrator version displaced by rollback becomes the next restore target."""

    desired_state = _converged()
    desired = _desired()
    first_admin = _live()
    first_admin["conditions"] = {"ref_name": {"include": ["refs/heads/first-admin"], "exclude": []}}
    second_admin = _live()
    second_admin["conditions"] = {"ref_name": {"include": ["refs/heads/second-admin"], "exclude": []}}
    histories = iter(
        [
            [{"version_id": 10}, {"version_id": 9}, {"version_id": 7}],
            [{"version_id": 12}, {"version_id": 11}],
            [{"version_id": 13}, {"version_id": 12}],
        ]
    )
    monkeypatch.setattr(module, "_gh_api_list", lambda *_args, **_kwargs: next(histories))

    states = {
        9: first_admin,
        10: desired_state,
        11: second_admin,
        12: first_admin,
        13: second_admin,
    }
    monkeypatch.setattr(module, "_history_version_state", lambda _target, version: states[version])

    calls: list[tuple[str, object | None]] = []
    replies = iter([desired_state, {}, first_admin, first_admin, {}, second_admin])

    def fake_api(method, endpoint, *, body=None):
        calls.append((method, body))
        return next(replies)

    monkeypatch.setattr(module, "_gh_api", fake_api)
    with pytest.raises(module.RulesetGovernanceError, match="restored newest displaced administrator state"):
        module._verify_ruleset_history_transition(_target(), 7, desired)

    put_bodies = [body for method, body in calls if method == "PUT"]
    assert put_bodies == [
        module._editable_projection(first_admin),
        module._editable_projection(second_admin),
    ]


def test_reconcile_forwards_expected_main_sha_to_each_target(monkeypatch) -> None:
    """The multi-target coordinator preserves the protected-main guard on every mutation."""

    seen: list[tuple[str, bool, str | None]] = []

    def fake_target(item, *, verify_only, expected_main_sha=None):
        seen.append((item.scope, verify_only, expected_main_sha))
        return True

    monkeypatch.setattr(module, "_reconcile_target", fake_target)
    assert module.reconcile(
        (_target(),), verify_only=False, expected_main_sha="a" * 40
    ) == 1
    assert seen == [("repository", False, "a" * 40)]


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


def test_owner_plane_workflow_serializes_mutation_and_quotes_main_sha() -> None:
    """PR validation may supersede itself but owner-plane mutation is non-cancellable."""

    text = WORKFLOW.read_text(encoding="utf-8")
    assert "cancel-in-progress: ${{ github.event_name == 'pull_request' }}" in text
    assert "EXPECTED_MAIN_SHA: ${{ github.sha }}" in text
    assert '--expected-main-sha "$EXPECTED_MAIN_SHA"' in text
    assert "github.event_name != 'pull_request'" in text


def test_docs_state_github_has_no_ruleset_put_compare_and_swap() -> None:
    """Doctoring must not claim an atomic compare-and-swap GitHub does not provide."""

    text = DOCTORING.read_text(encoding="utf-8")
    assert "does not support conditional unsafe REST updates" in text
    assert "ruleset-history" in text
    assert "restores the newest displaced administrator state" in text
    assert "cannot make the final GET-to-PUT interval atomic" in text


def test_module_docstring_does_not_promise_impossible_atomicity() -> None:
    """Production documentation must describe best-effort drift checks, not CAS semantics."""

    assert "never silently overwritten" not in (module.__doc__ or "")
