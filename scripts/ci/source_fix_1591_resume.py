#!/usr/bin/env python3
"""Resume PR #1591 repair after concurrent policy work advanced the branch."""

from __future__ import annotations

from pathlib import Path

from scripts.ci import source_fix_1591_launcher_caps as fix


def repair_policy() -> None:
    """Preserve concurrent policy repair and retire only stale CLI type gates."""
    path = Path("scripts/ci/contextual_orchestrator_review_policy.py")
    text = path.read_text(encoding="utf-8")
    expected = "    limit: object = DEFAULT_CATALOG_LIMIT,\n    account_cap: object = DEFAULT_ACCOUNT_CAP,\n"
    if text.count(expected) != 2:
        raise SystemExit("concurrent policy compatibility signatures changed unexpectedly")
    if '"legacy_limit_ignored": True' not in text or '"legacy_account_cap_ignored": True' not in text:
        raise SystemExit("concurrent ignored-input report contract is missing")
    if "legacy limit must be an integer when supplied" in text:
        raise SystemExit("concurrent policy still validates ignored limit")
    if "legacy account_cap must be an integer when supplied" in text:
        raise SystemExit("concurrent policy still validates ignored account_cap")
    text = text.replace(
        '        type=int,\n        default=DEFAULT_CATALOG_LIMIT,\n',
        '        default=DEFAULT_CATALOG_LIMIT,\n',
        1,
    )
    text = text.replace(
        '        type=int,\n        default=DEFAULT_ACCOUNT_CAP,\n',
        '        default=DEFAULT_ACCOUNT_CAP,\n',
        1,
    )
    path.write_text(text, encoding="utf-8")


def repair_stale_policy_test() -> None:
    """Make the legacy-input regression match the now-non-authoritative contract."""
    path = Path("tests/test_contextual_orchestrator_review_policy.py")
    text = path.read_text(encoding="utf-8")
    old = '''@pytest.mark.parametrize(("field", "value"), [("limit", True), ("account_cap", 1.5)])
def test_build_catalog_rejects_malformed_legacy_cap_inputs(field: str, value: object) -> None:
    """Compatibility-only inputs still fail closed when their type is malformed."""
    kwargs = {field: value}
    with pytest.raises(policy.PolicyError, match="legacy"):
        policy.build_zdr_prioritized_catalog(
            policy.parse_discovery_report(_report()), **kwargs
        )
'''
    new = '''@pytest.mark.parametrize(("field", "value"), [("limit", True), ("account_cap", 1.5)])
def test_build_catalog_ignores_legacy_cap_input_types(field: str, value: object) -> None:
    """Retired compatibility inputs cannot regain admission authority through type gates."""
    result = policy.build_zdr_prioritized_catalog(
        policy.parse_discovery_report(_report()), **{field: value}
    )
    assert result["report"][f"legacy_{field}_ignored"] is True
'''
    if text.count(old) != 1:
        if "def test_build_catalog_ignores_legacy_cap_input_types" in text:
            return
        raise SystemExit("stale legacy-cap regression changed unexpectedly")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


fix.repair_policy = repair_policy
repair_stale_policy_test()
fix.main()
