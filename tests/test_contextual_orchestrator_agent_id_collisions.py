"""Durable regressions for normalized review-agent identity collisions."""

from __future__ import annotations

import json

import pytest

from scripts.ci import contextual_orchestrator_review_policy as policy


FREE_PRICE = {
    "prompt_price_per_1k": 0.0,
    "completion_price_per_1k": 0.0,
    "currency_code": "USD",
}


def _colliding_report() -> dict[str, object]:
    """Return distinct routes whose explicit ids normalize to one runtime id."""
    return {
        "models": [
            {
                "provider": "openrouter",
                "model": "vendor/model-a:free",
                "agent_id": "or::same",
                "is_free": True,
                **FREE_PRICE,
            },
            {
                "provider": "openrouter",
                "model": "vendor/model-b:free",
                "agent_id": "or--same",
                "is_free": True,
                **FREE_PRICE,
            },
        ]
    }


def test_catalog_fails_closed_on_normalized_agent_id_collision() -> None:
    """Distinct admitted routes may never alias to the same runtime agent id."""
    rows = policy.parse_discovery_report(_colliding_report())

    with pytest.raises(policy.PolicyError, match="agent id collision after normalization: 'or_same'"):
        policy.build_zdr_prioritized_catalog(rows)


def test_collision_never_writes_partial_catalog_or_report(tmp_path) -> None:
    """Collision validation completes before either public artifact is written."""
    discovery = tmp_path / "discovery.json"
    catalog = tmp_path / "agents.json"
    report = tmp_path / "report.json"
    discovery.write_text(json.dumps(_colliding_report()), encoding="utf-8")

    with pytest.raises(policy.PolicyError, match="agent id collision after normalization"):
        policy.build_catalog_from_paths(
            str(discovery),
            out_path=str(catalog),
            report_path=str(report),
        )

    assert not catalog.exists()
    assert not report.exists()
