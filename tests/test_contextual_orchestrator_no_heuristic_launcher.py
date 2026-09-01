"""Regression contracts removing heuristic decisions from the review launcher."""

from __future__ import annotations

from pathlib import Path


LAUNCHER = Path("scripts/ci/contextual_orchestrator_review_launcher.py")


def test_launcher_has_no_synthetic_token_budget_or_route_cap_constants() -> None:
    """CI review startup cannot make serving admission depend on magic budgets."""
    source = LAUNCHER.read_text(encoding="utf-8")
    forbidden = (
        "REVIEW_PREFLIGHT_BASE_TOKENS",
        "REVIEW_PREFLIGHT_ESCALATED_TOKENS",
        "REVIEW_PREFLIGHT_MAX_ESCALATIONS",
        "REVIEW_PREFLIGHT_MAX_TOTAL_ROUTES",
        "REVIEW_PREFLIGHT_PRIMARY_ROUTE_LIMIT",
        "ORCHESTRATOR_CATALOG_LIMIT",
        "ORCHESTRATOR_CATALOG_ACCOUNT_CAP",
        "_bounded_primary_catalog_limit",
        "_bounded_fallback_catalog_limit",
        "_catalog_account_cap",
    )
    for marker in forbidden:
        assert marker not in source


def test_launcher_uses_structured_discovery_capability_contracts() -> None:
    """Model-name inference cannot substitute for provider-declared capabilities."""
    source = LAUNCHER.read_text(encoding="utf-8")
    assert "general_free_serving_candidates" in source
    assert "is_discovered_chat_candidate" in source
    assert "is_general_chat_agent_model_id" not in source


def test_launcher_does_not_filter_routes_with_a_synthetic_generation_probe() -> None:
    """Startup may record discovery evidence but cannot probe-and-rank candidates."""
    source = LAUNCHER.read_text(encoding="utf-8")
    assert "_preflight_review_agents" not in source
    assert "_preflight_with_fallback" not in source
    assert "proxy_send_once" not in source
    assert '"selection_contract": "evidence-admission-only-v1"' in source
