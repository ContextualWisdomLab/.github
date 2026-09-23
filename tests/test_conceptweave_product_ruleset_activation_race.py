from __future__ import annotations

from datetime import datetime, timezone

import pytest

from scripts.ci import reconcile_conceptweave_product_ruleset as p
from scripts.ci.reconcile_ruleset_governance import RulesetGovernanceError


def _manifest(ruleset_id: int) -> dict[str, object]:
    return {
        "schema_version": 1,
        "target_repository": p.TARGET_FULL_NAME,
        "target_branch": p.TARGET_BRANCH,
        "ruleset_name": p.RULESET_NAME,
        "ruleset_id": ruleset_id,
        "required_check": p.PRODUCT_CHECK,
        "forbidden_check": p.METADATA_ONLY_CHECK,
    }


def _live(ruleset_id: int) -> dict[str, object]:
    return {
        "id": ruleset_id,
        "source_type": "Organization",
        "source": p.ORGANIZATION,
        **p._desired(enforcement="evaluate"),
    }


def test_activation_aborts_when_conceptweave_main_advances_after_canary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Do not activate from evaluate evidence whose protected target base went stale."""

    ruleset_id = 30
    base_sha = "a" * 40
    head_sha = "b" * 40
    target_checks = 0
    put_called = False
    current = _live(ruleset_id)

    monkeypatch.setattr(p, "_assert_current_main", lambda _sha: None)
    monkeypatch.setattr(p, "_named_ruleset", lambda: {"id": ruleset_id})
    monkeypatch.setattr(p, "_live", lambda _target: current)
    monkeypatch.setattr(
        p,
        "_latest_base_retarget",
        lambda _pr: datetime(2026, 9, 23, 0, 0, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(
        p,
        "_canary_evidence",
        lambda **_kwargs: (base_sha, head_sha),
    )
    monkeypatch.setattr(p, "_assert_evaluate_rule_suite", lambda **_kwargs: None)
    monkeypatch.setattr(p, "_latest_history_version", lambda _target: 4)

    def assert_target_main(_sha: str) -> None:
        nonlocal target_checks
        target_checks += 1
        if target_checks == 2:
            raise RulesetGovernanceError("ConceptWeave protected main advanced")

    monkeypatch.setattr(p, "_assert_target_main", assert_target_main)

    def api(method: str, _endpoint: str, **_kwargs: object) -> dict[str, object]:
        nonlocal put_called
        if method == "PUT":
            put_called = True
        return {}

    monkeypatch.setattr(p, "_gh_api", api)

    with pytest.raises(RulesetGovernanceError, match="protected main advanced"):
        p.activate_product_ruleset(
            _manifest(ruleset_id),
            expected_main_sha="d" * 40,
            canary_pr=5,
            canary_run_id=77,
        )

    assert target_checks == 2
    assert put_called is False
