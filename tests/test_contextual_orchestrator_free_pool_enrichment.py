"""Runtime report enrichment contracts for free-pool source admission."""

from scripts.ci.contextual_orchestrator_review_launcher import _with_discovery_counts


def test_discovery_enrichment_recomputes_free_pool_counts_from_full_rows() -> None:
    """Priced fallback reports retain full discovered authorized free capacity."""
    stage_report = {
        "free_pool_admitted_routes": 0,
        "free_pool_excluded_source_count": 0,
        "free_pool_account_diversity": 0,
    }
    rows = [
        {
            "provider": "openrouter",
            "credential_key": "OPENROUTER_API_KEY",
            "cost_evidence": "free",
        },
        {
            "provider": "openai",
            "credential_key": "OPENAI_API_KEY",
            "cost_evidence": "free",
        },
        {
            "provider": "openai",
            "credential_key": "OPENAI_API_KEY",
            "cost_evidence": "priced",
        },
    ]

    enriched = _with_discovery_counts(
        stage_report,
        rows,
        provider_account=lambda provider: provider,
    )

    assert enriched["total_routes"] == 3
    assert enriched["total_free_routes"] == 2
    assert enriched["free_account_diversity"] == 2
    assert enriched["free_pool_admitted_routes"] == 1
    assert enriched["free_pool_excluded_source_count"] == 1
    assert enriched["free_pool_account_diversity"] == 1
