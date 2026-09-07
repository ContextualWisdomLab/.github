"""End-to-end contract for Bytez free-price discovery and catalog admission."""

from __future__ import annotations

from pathlib import Path
import runpy
from types import SimpleNamespace

import pytest

from scripts.ci import contextual_orchestrator_review_policy as policy

_REPO_ROOT = Path(__file__).resolve().parents[1]
_LAUNCHER = _REPO_ROOT / "scripts/ci/contextual_orchestrator_review_launcher.py"
_BYTEZ_MODEL = "0-hero/Matter-0.1-Slim-7B-C"


def _report_bytez(*, free: bool) -> list[dict[str, object]]:
    """Pass one pinned-runtime-shaped Bytez row through the real launcher adapter."""
    report_rows = runpy.run_path(str(_LAUNCHER))["_report_rows"]
    discovered = SimpleNamespace(
        provider_name="bytez",
        model_id=_BYTEZ_MODEL,
        agent_id="bytez_matter_01_slim_7b_c",
        chat_base_url="https://api.bytez.com/models/v2/openai/v1",
        credential_name="BYTEZ_API_KEY",
        auth_scheme="raw-token",
        output_modalities=("text",),
        prompt_price_per_1k=None,
        completion_price_per_1k=None,
        currency_code="USD",
    )
    free_routes = frozenset({("bytez", _BYTEZ_MODEL)}) if free else frozenset()
    return report_rows([discovered], free_routes)


def test_zero_meter_price_survives_launcher_policy_and_catalog() -> None:
    """Exact-zero Bytez meter pricing must enter free without fake token prices."""
    report_rows = _report_bytez(free=True)
    assert report_rows[0]["is_free"] is True
    assert report_rows[0]["prompt_price_per_1k"] is None
    assert report_rows[0]["completion_price_per_1k"] is None

    parsed = policy.parse_discovery_report({"models": report_rows})
    assert parsed[0]["cost_evidence"] == policy.COST_FREE
    assert parsed[0]["non_token_price_evidence"] == {
        "source": "bytez.meterPrice",
        "price": 0.0,
        "unit": "provider_meter_unit",
    }
    assert parsed[0]["prompt_price_per_1k"] is None
    assert parsed[0]["completion_price_per_1k"] is None

    result = policy.build_zdr_prioritized_catalog(parsed, pool="free")
    assert [agent["model"] for agent in result["agents"]] == [_BYTEZ_MODEL]
    assert result["agents"][0]["credential_key"] == "BYTEZ_API_KEY"
    assert "cost:free" in result["agents"][0]["tags"]
    assert result["report"]["selected"][0]["non_token_price_evidence"] == (
        parsed[0]["non_token_price_evidence"]
    )


def test_unattested_bytez_meter_price_remains_unknown() -> None:
    """No free identity from the pinned parser means no Bytez free admission."""
    parsed = policy.parse_discovery_report({"models": _report_bytez(free=False)})
    assert parsed[0]["cost_evidence"] == policy.COST_UNKNOWN
    assert parsed[0]["non_token_price_evidence"] is None

    with pytest.raises(policy.PolicyError, match="would fail closed"):
        policy.build_zdr_prioritized_catalog(parsed, pool="free")
