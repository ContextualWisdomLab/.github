"""One-shot exact-text repair for PR #1644 review round two."""

from __future__ import annotations

from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    """Replace one reviewed source anchor or abort without partial mutation."""
    if text.count(old) != 1:
        raise SystemExit(f"expected exactly one {label} anchor, found {text.count(old)}")
    return text.replace(old, new, 1)


def repair_reconciler() -> None:
    """Separate immutable history provenance from editable live identity."""
    path = Path("scripts/ci/reconcile_ruleset_governance.py")
    text = path.read_text(encoding="utf-8")
    old = '''def _history_version_state(target: RulesetTarget, version_id: int) -> dict[str, Any]:
    """Return the exact ruleset state stored at one immutable history version."""

    payload = _gh_api("GET", target.history_version_endpoint(version_id))
    state = _plain_dict(payload.get("state"), field="ruleset history version state")
    _assert_identity(state, target)
    return state


def _assert_identity(live: dict[str, Any], target: RulesetTarget) -> None:
    """Require the live ruleset to be the exact reviewed object before mutation."""

    expected = {
        "id": target.ruleset_id,
        "name": target.name,
        "target": "branch",
        "source_type": target.source_type,
        "source": target.source,
        "enforcement": "active",
    }
    mismatches = [key for key, value in expected.items() if live.get(key) != value]
    if mismatches:
        raise RulesetGovernanceError(
            f"{target.scope} ruleset identity drift: {', '.join(sorted(mismatches))}"
        )
'''
    new = '''def _assert_target_provenance(live: dict[str, Any], target: RulesetTarget) -> None:
    """Require immutable ruleset provenance while allowing historical editable fields."""

    expected = {
        "id": target.ruleset_id,
        "target": "branch",
        "source_type": target.source_type,
        "source": target.source,
    }
    mismatches = [key for key, value in expected.items() if live.get(key) != value]
    if mismatches:
        raise RulesetGovernanceError(
            f"{target.scope} ruleset identity drift: {', '.join(sorted(mismatches))}"
        )


def _history_version_state(target: RulesetTarget, version_id: int) -> dict[str, Any]:
    """Return one historical state after proving it belongs to the exact target."""

    payload = _gh_api("GET", target.history_version_endpoint(version_id))
    state = _plain_dict(payload.get("state"), field="ruleset history version state")
    _assert_target_provenance(state, target)
    return state


def _assert_identity(live: dict[str, Any], target: RulesetTarget) -> None:
    """Require current live state to retain the reviewed editable identity too."""

    _assert_target_provenance(live, target)
    expected = {"name": target.name, "enforcement": "active"}
    mismatches = [key for key, value in expected.items() if live.get(key) != value]
    if mismatches:
        raise RulesetGovernanceError(
            f"{target.scope} ruleset identity drift: {', '.join(sorted(mismatches))}"
        )
'''
    text = replace_once(text, old, new, "history/live identity split")
    text = replace_once(
        text,
        '''    restored = _gh_api("GET", target.endpoint)
    _assert_identity(restored, target)
    if _editable_projection(restored) != predecessor_payload:
''',
        '''    restored = _gh_api("GET", target.endpoint)
    _assert_target_provenance(restored, target)
    if _editable_projection(restored) != predecessor_payload:
''',
        "historical rollback verification",
    )
    path.write_text(text, encoding="utf-8")


def repair_audit_fixture() -> None:
    """Keep the canonical passing repository-ruleset fixture complete."""
    path = Path("tests/test_central_required_workflow_ruleset_audit.py")
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '''                    "required_approving_review_count": 0,
                    "dismiss_stale_reviews_on_push": True,
                    "require_last_push_approval": False,
''',
        '''                    "required_approving_review_count": 0,
                    "dismiss_stale_reviews_on_push": True,
                    "require_code_owner_review": False,
                    "require_last_push_approval": False,
''',
        "repository audit fixture code-owner flag",
    )
    path.write_text(text, encoding="utf-8")


def repair_validation_scope() -> None:
    """Make the new regression part of every reviewed reconciler validation path."""
    path = Path(".github/workflows/ruleset-governance-reconcile.yml")
    text = path.read_text(encoding="utf-8")
    marker = '      - "tests/test_ruleset_governance_review_regressions.py"\n'
    if text.count(marker) != 2:
        raise SystemExit(f"unexpected workflow path marker count: {text.count(marker)}")
    text = text.replace(
        marker,
        marker + '      - "tests/test_ruleset_governance_review_round2.py"\n',
    )
    text = replace_once(
        text,
        '''            -m pytest -q tests/test_ruleset_governance_reconciliation.py tests/test_ruleset_governance_review_regressions.py
''',
        '''            -m pytest -q tests/test_ruleset_governance_reconciliation.py tests/test_ruleset_governance_review_regressions.py tests/test_ruleset_governance_review_round2.py
''',
        "focused pytest command",
    )
    path.write_text(text, encoding="utf-8")


def repair_docs() -> None:
    """Record the cancellation and historical-identity recovery boundary."""
    path = Path("docs/doctoring/ruleset-owner-plane-reconciliation.md")
    text = path.read_text(encoding="utf-8")
    heading = "## 2026-09-02 review-round-two recovery hardening"
    if heading not in text:
        text = text.rstrip() + f'''\n\n{heading}\n\nPrivileged owner-plane reconciliation is serialized without `cancel-in-progress`.\nPull-request validation may still supersede older validation runs, but a protected-main\nmutation run must finish its PUT plus immutable-history verification/recovery critical\nsection. This prevents a newer run from observing the desired payload after cancelling\na predecessor between PUT and collision verification.\n\nRuleset history is validated against immutable target provenance (`id`, branch target,\nsource type, and source). Historical `name` and `enforcement` are deliberately allowed\nto differ because they are editable administrator state that collision recovery may\nneed to restore. Current live mutation still requires the reviewed name and active\nenforcement. Rollback verifies exact predecessor editable payload convergence while\nretaining immutable target provenance, so a legitimate concurrent rename/enforcement\nchange cannot be silently overwritten.\n'''
        path.write_text(text, encoding="utf-8")


def main() -> None:
    repair_reconciler()
    repair_audit_fixture()
    repair_validation_scope()
    repair_docs()


if __name__ == "__main__":
    main()
