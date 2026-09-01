"""Regression contracts for evidence-only contextual-orchestrator admission."""

from __future__ import annotations

import pytest

from scripts.ci import contextual_orchestrator_review_policy as policy


def _free_row(index: int, *, provider: str = "openrouter") -> dict[str, object]:
    """Return one normalized evidence-eligible free review route."""
    credential = {
        "bytez": "BYTEZ_API_KEY",
        "nvidia_nim": "NVIDIA_NIM_API_KEY",
        "nvidia_nim_sub": "NVIDIA_NIM_API_KEY_SUB",
        "openrouter": "OPENROUTER_API_KEY",
    }[provider]
    return {
        "provider": provider,
        "model": f"review-model-{index:02d}",
        "agent_id": f"{provider}_review_model_{index:02d}",
        "is_free": True,
        "cost_evidence": policy.COST_FREE,
        "prompt_price_per_1k": 0.0,
        "completion_price_per_1k": 0.0,
        "currency_code": "USD",
        "base_url": f"https://{provider}.example/v1",
        "credential_key": credential,
        "auth_scheme": "Bearer",
    }


def test_free_pool_admits_every_evidence_eligible_route_despite_legacy_caps() -> None:
    """Legacy cap arguments may not evict evidence-eligible free candidates."""
    rows = [_free_row(index) for index in range(13)]

    result = policy.build_zdr_prioritized_catalog(
        rows,
        pool="free",
        limit=1,
        account_cap=1,
    )

    assert {entry["model"] for entry in result["agents"]} == {
        row["model"] for row in rows
    }
    assert result["report"]["selected_count"] == len(rows)


def test_free_pool_admission_assigns_no_hand_authored_priority() -> None:
    """Admission leaves every eligible model neutral for evidence-based routing."""
    rows = [
        _free_row(0, provider="bytez"),
        _free_row(1, provider="nvidia_nim"),
        _free_row(2, provider="nvidia_nim_sub"),
        _free_row(3, provider="openrouter"),
    ]

    result = policy.build_zdr_prioritized_catalog(rows, pool="free")

    assert {entry["priority"] for entry in result["agents"]} == {0}


def test_normalized_agent_identity_collision_fails_closed() -> None:
    """Two distinct routes may not share the runtime identity used for failover."""
    first = _free_row(0)
    second = _free_row(1)
    first["agent_id"] = "openrouter/model-a"
    second["agent_id"] = "openrouter-model-a"
    assert first["model"] != second["model"]

    with pytest.raises(policy.PolicyError, match="agent id collision"):
        policy.build_zdr_prioritized_catalog([first, second], pool="free")


def test_legacy_ignored_inputs_accept_arbitrary_values() -> None:
    """Ignored compatibility inputs cannot become an accidental admission contract."""
    rows = [_free_row(index) for index in range(3)]
    sentinel = object()

    result = policy.build_zdr_prioritized_catalog(
        rows,
        pool="free",
        limit="retired-limit",
        account_cap=sentinel,
    )

    assert [entry["model"] for entry in result["agents"]] == [
        row["model"] for row in rows
    ]
    assert result["report"]["legacy_limit_ignored"] is True
    assert result["report"]["legacy_account_cap_ignored"] is True
