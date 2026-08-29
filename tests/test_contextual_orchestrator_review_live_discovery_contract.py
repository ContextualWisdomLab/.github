"""Regression tests for live provider catalogs with unavailable price metadata."""

from __future__ import annotations

import pytest

from scripts.ci import contextual_orchestrator_review_policy as policy


FREE_MODEL = "qwen/qwen3-coder:free"
PRICED_MODEL = "anthropic/claude-sonnet-4.6"
PRICED_ZDR_FEED = frozenset({f"openrouter/{PRICED_MODEL}"})


def _live_discovery_report() -> dict[str, object]:
    """Mirror the price shapes returned by the current provider list APIs."""
    return {
        "models": [
            {
                "provider": "openrouter",
                "model": FREE_MODEL,
                "agent_id": "openrouter_qwen3_coder_free",
                "is_free": True,
                "prompt_price_per_1k": 0.0,
                "completion_price_per_1k": 0.0,
                "currency_code": "USD",
            },
            {
                "provider": "openrouter",
                "model": PRICED_MODEL,
                "agent_id": "openrouter_claude_sonnet_46",
                "is_free": False,
                "prompt_price_per_1k": 0.003,
                "completion_price_per_1k": 0.015,
                "currency_code": "USD",
            },
            {
                "provider": "openai",
                "model": "gpt-5.6",
                "agent_id": "openai_gpt_56",
                "is_free": False,
                "prompt_price_per_1k": None,
                "completion_price_per_1k": None,
                "currency_code": "USD",
            },
            {
                "provider": "nvidia_nim",
                "model": "meta/llama-3.3-70b-instruct",
                "agent_id": "nvidia_nim_llama_33_70b",
                "is_free": False,
                "prompt_price_per_1k": None,
                "completion_price_per_1k": None,
                "currency_code": "USD",
            },
            {
                "provider": "nvidia_nim_sub",
                "model": "nvidia/llama-3.1-nemotron-ultra-253b-v1",
                "agent_id": "nvidia_nim_sub_nemotron_ultra",
                "is_free": False,
                "prompt_price_per_1k": None,
                "completion_price_per_1k": None,
                "currency_code": "USD",
            },
            {
                "provider": "bytez",
                "model": "Qwen/Qwen3-Coder-480B-A35B-Instruct",
                "agent_id": "bytez_qwen3_coder_480b",
                "is_free": False,
                "prompt_price_per_1k": None,
                "completion_price_per_1k": None,
                "currency_code": "USD",
            },
        ]
    }


def test_live_catalog_keeps_complete_unknown_prices_as_unknown() -> None:
    """Unavailable price vectors are fallback evidence, not a catalog-wide error."""
    rows = policy.parse_discovery_report(_live_discovery_report())
    evidence = {row["model"]: row["cost_evidence"] for row in rows}

    assert evidence[FREE_MODEL] == "free"
    assert evidence[PRICED_MODEL] == "priced"
    assert evidence["gpt-5.6"] == "unknown"
    assert evidence["meta/llama-3.3-70b-instruct"] == "unknown"
    assert evidence["Qwen/Qwen3-Coder-480B-A35B-Instruct"] == "unknown"


def test_auto_pool_is_free_first_then_price_honest_and_provider_diverse() -> None:
    """A ZDR-priced route cannot outrank free inference; unknown cost stays last."""
    result = policy.build_zdr_prioritized_catalog(
        policy.parse_discovery_report(_live_discovery_report()),
        limit=6,
        family_cap=2,
        zdr_endpoints=PRICED_ZDR_FEED,
        pool="auto",
    )

    agents = result["agents"]
    assert agents[0]["model"] == FREE_MODEL
    assert "cost:free" in agents[0]["tags"]
    assert "cost:priced" in next(
        agent for agent in agents if agent["model"] == PRICED_MODEL
    )["tags"]

    unknown_agents = [agent for agent in agents if "cost:unknown" in agent["tags"]]
    assert {agent["provider_name"] for agent in unknown_agents} == {
        "bytez",
        "nvidia_nim",
        "nvidia_nim_sub",
        "openai",
    }
    assert result["report"]["total_unknown_routes"] == 4
    assert result["report"]["unknown_selected_count"] == 4


def test_free_pool_never_admits_priced_or_unknown_routes() -> None:
    """The existing orchestrator/free contract remains strictly zero-priced."""
    result = policy.build_zdr_prioritized_catalog(
        policy.parse_discovery_report(_live_discovery_report()),
        pool="free",
    )

    assert [agent["model"] for agent in result["agents"]] == [FREE_MODEL]
    assert result["report"]["unknown_selected_count"] == 0
    assert result["report"]["priced_selected_count"] == 0


def test_partial_price_vectors_still_fail_closed() -> None:
    """One missing price component is malformed evidence, not an unknown vector."""
    report = _live_discovery_report()
    openai = next(row for row in report["models"] if row["provider"] == "openai")
    openai["completion_price_per_1k"] = 0.01

    with pytest.raises(policy.PolicyError, match="lacks numeric prompt_price_per_1k"):
        policy.parse_discovery_report(report)


def test_legacy_normalized_rows_have_conservative_cost_fallbacks() -> None:
    """Old normalized callers remain free-only or unknown, never inferred priced."""
    assert policy._cost_evidence({"is_free": True}) == "free"
    assert policy._cost_evidence({"is_free": False}) == "unknown"
