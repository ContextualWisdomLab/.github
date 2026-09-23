from __future__ import annotations

import pytest

from scripts.ci import reconcile_conceptweave_product_ruleset as p
from scripts.ci.reconcile_ruleset_governance import RulesetGovernanceError


def _manifest() -> dict[str, object]:
    return {
        "schema_version": 1,
        "target_repository": p.TARGET_FULL_NAME,
        "target_branch": p.TARGET_BRANCH,
        "ruleset_name": p.RULESET_NAME,
        "ruleset_id": None,
        "required_check": p.PRODUCT_CHECK,
        "forbidden_check": p.METADATA_ONLY_CHECK,
    }


def test_bootstrap_rechecks_protected_main_immediately_before_create(monkeypatch):
    expected = "a" * 40
    current_main_checks: list[str] = []
    created = False

    def assert_current_main(sha: str) -> None:
        current_main_checks.append(sha)
        if len(current_main_checks) == 2:
            raise RulesetGovernanceError("protected main advanced")

    def create_evaluate_ruleset():
        nonlocal created
        created = True
        return {"id": 91}

    monkeypatch.setattr(p, "_assert_current_main", assert_current_main)
    monkeypatch.setattr(p, "_named_ruleset", lambda: None)
    monkeypatch.setattr(p, "_create_evaluate_ruleset", create_evaluate_ruleset)

    with pytest.raises(RulesetGovernanceError, match="advanced"):
        p.bootstrap_product_ruleset(_manifest(), expected_main_sha=expected)

    assert current_main_checks == [expected, expected]
    assert created is False
