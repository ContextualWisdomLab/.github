"""Regression contracts forbidding heuristic CI review-catalog selection."""

from __future__ import annotations

import pytest

from scripts.ci import contextual_orchestrator_review_policy as policy

FREE_PRICE = {
    "prompt_price_per_1k": 0.0,
    "completion_price_per_1k": 0.0,
    "currency_code": "USD",
}


def _free_report(count: int = 13) -> dict[str, object]:
    """Build more routes than the legacy route/account caps admitted."""
    return {
        "models": [
            {
                "provider": "openrouter",
                "model": f"model-{index}",
                "agent_id": f"openrouter_model_{index}",
                "credential_key": "OPENROUTER_API_KEY",
                "is_free": True,
                **FREE_PRICE,
            }
            for index in range(count)
        ]
    }


def test_free_catalog_admits_every_evidence_eligible_route_without_caps() -> None:
    """Route-count and per-account caps cannot delete eligible free candidates."""
    rows = policy.parse_discovery_report(_free_report())

    result = policy.build_zdr_prioritized_catalog(rows, pool="free")

    assert len(result["agents"]) == len(rows) == 13
    assert {agent["model"] for agent in result["agents"]} == {
        row["model"] for row in rows
    }


def test_catalog_does_not_encode_an_arbitrary_routing_priority() -> None:
    """Catalog construction is admission only; it must not manufacture a rank."""
    result = policy.build_zdr_prioritized_catalog(
        policy.parse_discovery_report(_free_report(3)), pool="free"
    )

    assert {agent["priority"] for agent in result["agents"]} == {0}


def test_catalog_rejects_legacy_decision_caps_instead_of_silently_using_them() -> None:
    """Callers cannot re-enable the removed heuristic caps through old parameters."""
    rows = policy.parse_discovery_report(_free_report(3))

    with pytest.raises(policy.PolicyError, match="heuristic catalog caps"):
        policy.build_zdr_prioritized_catalog(rows, limit=2)
    with pytest.raises(policy.PolicyError, match="heuristic catalog caps"):
        policy.build_zdr_prioritized_catalog(rows, account_cap=1)


def test_zdr_evidence_filters_only_when_zdr_is_required() -> None:
    """ZDR metadata is an eligibility requirement, not an implicit preference rank."""
    report = {
        "models": [
            {
                "provider": "openrouter",
                "model": "not-attested",
                "agent_id": "openrouter_not_attested",
                "credential_key": "OPENROUTER_API_KEY",
                "is_free": True,
                **FREE_PRICE,
            },
            {
                "provider": "openrouter",
                "model": "attested",
                "agent_id": "openrouter_attested",
                "credential_key": "OPENROUTER_API_KEY",
                "is_free": True,
                **FREE_PRICE,
            },
        ]
    }
    rows = policy.parse_discovery_report(report)
    zdr = frozenset({"openrouter/attested"})

    ordinary = policy.build_zdr_prioritized_catalog(
        rows, pool="free", zdr_endpoints=zdr, require_zdr=False
    )
    private = policy.build_zdr_prioritized_catalog(
        rows, pool="free", zdr_endpoints=zdr, require_zdr=True
    )

    assert {agent["model"] for agent in ordinary["agents"]} == {
        "not-attested",
        "attested",
    }
    assert [agent["model"] for agent in private["agents"]] == ["attested"]
