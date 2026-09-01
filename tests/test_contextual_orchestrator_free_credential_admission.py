"""Free-pool credential-source admission contracts for the review catalog."""

from __future__ import annotations

import pytest

from scripts.ci.contextual_orchestrator_review_policy import (
    PolicyError,
    build_zdr_prioritized_catalog,
    parse_discovery_report,
)
from scripts.ci.zdr_policy import PROVIDER_CREDENTIAL_NAMES


def _zero_cost_row(provider: str) -> dict[str, object]:
    """Return one complete zero-cost discovery row with authentic source identity."""
    return {
        "provider": provider,
        "model": f"{provider}-review-model",
        "agent_id": f"{provider}_review_model",
        "is_free": True,
        "prompt_price_per_1k": 0.0,
        "completion_price_per_1k": 0.0,
        "currency_code": "USD",
        "credential_key": PROVIDER_CREDENTIAL_NAMES[provider],
    }


def test_free_pool_excludes_openai_while_global_discovery_keeps_all_five() -> None:
    """All providers stay discoverable, but OpenAI contributes no free candidate."""
    providers = (
        "bytez",
        "nvidia_nim",
        "nvidia_nim_sub",
        "openrouter",
        "openai",
    )
    rows = parse_discovery_report({"models": [_zero_cost_row(provider) for provider in providers]})

    result = build_zdr_prioritized_catalog(rows, pool="free", limit=12, account_cap=12)

    selected = result["report"]["selected"]
    assert {entry["provider"] for entry in selected} == {
        "bytez",
        "nvidia_nim",
        "nvidia_nim_sub",
        "openrouter",
    }
    assert all(agent["credential_key"] != "OPENAI_API_KEY" for agent in result["agents"])
    # Discovery-wide counters keep their established meaning; narrower pool
    # admission gets separate fields so runtime enrichment cannot relabel them.
    assert result["report"]["total_free_routes"] == 5
    assert result["report"]["free_account_diversity"] == 5
    assert result["report"]["free_pool_admitted_routes"] == 4
    assert result["report"]["free_pool_excluded_source_count"] == 1
    assert result["report"]["free_pool_account_diversity"] == 4


def test_auto_pool_may_retain_globally_discovered_openai() -> None:
    """The free-source rule does not delete OpenAI from non-free/global routing."""
    rows = parse_discovery_report(
        {"models": [_zero_cost_row("openrouter"), _zero_cost_row("openai")]}
    )

    result = build_zdr_prioritized_catalog(rows, pool="auto", limit=12, account_cap=12)

    assert {entry["provider"] for entry in result["report"]["selected"]} == {
        "openrouter",
        "openai",
    }
    assert result["report"]["free_pool_admitted_routes"] == 1
    assert result["report"]["free_pool_excluded_source_count"] == 1


def test_openai_only_zero_cost_discovery_fails_closed_for_free_pool() -> None:
    """A globally discovered OpenAI route cannot become the sole free fallback."""
    rows = parse_discovery_report({"models": [_zero_cost_row("openai")]})

    with pytest.raises(PolicyError, match="orchestrator/free would fail closed"):
        build_zdr_prioritized_catalog(rows, pool="free", limit=12, account_cap=12)


def test_provider_credential_source_mismatch_is_rejected() -> None:
    """A row cannot spoof an eligible provider while using the OpenAI credential."""
    row = _zero_cost_row("openrouter")
    row["credential_key"] = "OPENAI_API_KEY"

    with pytest.raises(PolicyError, match="credential source does not match provider evidence"):
        parse_discovery_report({"models": [row]})
