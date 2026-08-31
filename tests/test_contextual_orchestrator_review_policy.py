"""Tests for scripts/ci/contextual_orchestrator_review_policy.py."""

from __future__ import annotations

import json

import pytest

from scripts.ci import contextual_orchestrator_review_policy as policy
from scripts.ci import zdr_policy

ZDR_FEED = frozenset({"openrouter/deepseek/deepseek-r1:free"})
FREE_PRICE = {
    "prompt_price_per_1k": 0.0,
    "completion_price_per_1k": 0.0,
    "currency_code": "USD",
}


def _report() -> dict[str, object]:
    return {
        "models": [
            {
                "provider": "openrouter",
                "model": "deepseek/deepseek-r1:free",
                "agent_id": "or_ds_r1",
                "is_free": True,
                **FREE_PRICE,
            },
            {
                "provider": "nvidia_nim",
                "model": "nvidia/nemotron-3-nano-30b-a3b",
                "agent_id": "nim_nano_free",
                "is_free": True,
                **FREE_PRICE,
            },
            {
                "provider": "nvidia_nim_sub",
                "model": "meta/llama-3.3-70b-instruct",
                "agent_id": "nimsec_70b",
                "is_free": True,
                **FREE_PRICE,
            },
            {
                "provider": "openai",
                "model": "gpt-4o-mini",
                "agent_id": "openai_gpt_4o_mini",
                "is_free": True,
                **FREE_PRICE,
            },
            {
                "provider": "bytez",
                "model": "qwen2.5-coder",
                "agent_id": "bytez_qwen25_coder",
                "is_free": True,
                **FREE_PRICE,
            },
            {
                "provider": "openai",
                "model": "gpt-4.1",
                "agent_id": "openai_gpt_41",
                "is_free": False,
                "prompt_price_per_1k": 0.002,
                "completion_price_per_1k": 0.008,
                "currency_code": "USD",
            },
        ]
    }


def test_provider_account_keeps_nvidia_keys_independent() -> None:
    """The primary and secondary NVIDIA credentials are separate accounts."""
    assert policy.provider_account("nvidia_nim") == "nvidia_nim"
    assert policy.provider_account("nvidia_nim_sub") == "nvidia_nim_sub"
    assert policy.provider_account("openai") == "openai"


def test_outage_domain_groups_by_shared_base_url() -> None:
    """Outage domain is keyed on a row's own base_url, not its provider name."""
    assert policy._outage_domain(
        {"base_url": "https://integrate.api.nvidia.com/v1"}
    ) == policy._outage_domain({"base_url": "https://integrate.api.nvidia.com/v1"})
    assert policy._outage_domain(
        {"base_url": "https://api.openai.com/v1"}
    ) != policy._outage_domain({"base_url": "https://integrate.api.nvidia.com/v1"})


@pytest.mark.parametrize(
    ("base_url", "equivalent_to"),
    [
        ("HTTPS://Integrate.API.Nvidia.COM/v1", "https://integrate.api.nvidia.com/v1"),
        ("https://integrate.api.nvidia.com:443/v1", "https://integrate.api.nvidia.com/v1"),
        ("https://integrate.api.nvidia.com/v1/", "https://integrate.api.nvidia.com/v1"),
        ("https://integrate.api.nvidia.com/v1//", "https://integrate.api.nvidia.com/v1"),
    ],
)
def test_normalize_base_url_treats_equivalent_spellings_as_one_domain(
    base_url: str, equivalent_to: str
) -> None:
    """Case, an explicit default port, and a trailing slash do not split a domain.

    Regression for a Devin Review finding on this fix: comparing raw
    ``base_url`` strings would let a hostname-case difference, an explicit
    ``:443``, or a trailing slash split one physical endpoint into two
    outage domains by formatting accident alone -- silently reintroducing
    the diversity-overstating, cap-bypassing bug this module exists to fix,
    for exactly the ``nvidia_nim``/``nvidia_nim_sub`` pair it was written to
    protect.
    """
    assert policy._normalize_base_url(base_url) == policy._normalize_base_url(equivalent_to)


@pytest.mark.parametrize(
    ("base_url", "distinct_from"),
    [
        ("https://integrate.api.nvidia.com/v1", "https://api.openai.com/v1"),
        ("https://integrate.api.nvidia.com:8443/v1", "https://integrate.api.nvidia.com/v1"),
        ("https://integrate.api.nvidia.com/v2", "https://integrate.api.nvidia.com/v1"),
        ("http://integrate.api.nvidia.com/v1", "https://integrate.api.nvidia.com/v1"),
    ],
)
def test_normalize_base_url_preserves_genuine_distinctions(
    base_url: str, distinct_from: str
) -> None:
    """A different host, non-default port, path, or scheme stays a different domain."""
    assert policy._normalize_base_url(base_url) != policy._normalize_base_url(distinct_from)


def test_normalize_base_url_falls_back_on_unparseable_input() -> None:
    """A hostless or malformed-port URL groups by a stripped, lowercased copy.

    Never raises: this function only needs equal inputs to compare equal,
    not a validated URL, since it groups audit evidence, not user input that
    must be rejected.
    """
    assert policy._normalize_base_url("") == policy._normalize_base_url("")
    assert policy._normalize_base_url(" NOT-A-URL ") == policy._normalize_base_url("not-a-url")
    assert policy._normalize_base_url(
        "https://host:notaport/v1"
    ) == policy._normalize_base_url("HTTPS://HOST:NOTAPORT/v1")


def test_normalize_base_url_falls_back_on_malformed_ipv6_bracket() -> None:
    """An unmatched IPv6 bracket cannot raise past this function.

    Regression for a Devin Review finding: ``urlsplit()`` itself raises
    ``ValueError`` for an unmatched ``[``/``]`` (e.g. ``https://[::1/v1``,
    a missing closing bracket) -- before any scheme/host/port is even
    available to inspect, so the earlier fallback (which only wrapped the
    ``.port`` property access) did not cover it.
    """
    # Would raise ValueError: Invalid IPv6 URL if urlsplit() itself were not
    # also wrapped.
    assert policy._normalize_base_url("https://[::1/v1") == "https://[::1/v1"
    assert policy._normalize_base_url("HTTPS://[::1/V1") == policy._normalize_base_url(
        "https://[::1/v1"
    )


def test_normalize_base_url_distinguishes_ipv6_port_from_literal_colon_digits() -> None:
    """An IPv6 host:port pair and a differently-shaped literal stay distinct.

    Regression for a Devin Review finding: ``urlsplit().hostname`` strips
    IPv6 literal brackets (``[::1]`` -> ``::1``), so appending a port
    without re-adding them collapsed ``https://[::1]:8443/v1`` (host
    ``::1``, port ``8443``) and ``https://[::1:8443]/v1`` (one IPv6
    literal, ``::1:8443``, with no separate port at all) to the identical
    ``::1:8443`` string -- two different addresses undercounted as one
    outage domain.
    """
    explicit_port = policy._normalize_base_url("https://[::1]:8443/v1")
    literal_colon_digits = policy._normalize_base_url("https://[::1:8443]/v1")
    assert explicit_port != literal_colon_digits
    # Both stay valid, bracketed netloc syntax, not the pre-fix bare form.
    assert explicit_port == "https://[::1]:8443/v1"
    assert literal_colon_digits == "https://[::1:8443]/v1"


def test_normalize_base_url_drops_default_port_for_ipv6_host() -> None:
    """An explicit default port on an IPv6 host is still dropped, brackets intact."""
    assert policy._normalize_base_url(
        "https://[::1]:443/v1"
    ) == policy._normalize_base_url("https://[::1]/v1")


def test_outage_domain_uses_normalized_base_url() -> None:
    """Two rows spelling one endpoint differently share one outage domain."""
    assert policy._outage_domain(
        {"base_url": "https://integrate.api.nvidia.com/v1"}
    ) == policy._outage_domain({"base_url": "https://Integrate.API.Nvidia.com:443/v1/"})


def _row(
    provider: str, model: str, *, cost_evidence: str = policy.COST_UNKNOWN
) -> dict[str, object]:
    """Return a minimal normalized-shaped row for ``_fair_admission_order`` tests."""
    return {
        "provider": provider,
        "model": model,
        "base_url": policy.PROVIDER_BASE_URLS[provider],
        "cost_evidence": cost_evidence,
    }


def test_fair_admission_order_untouched_for_single_account_domains() -> None:
    """A domain with only one contributing account keeps its original order."""
    rows = [_row("openrouter", "a"), _row("openai", "b"), _row("bytez", "c")]
    assert policy._fair_admission_order(rows, zdr_endpoints=frozenset()) == rows


def test_fair_admission_order_round_robins_a_shared_domain() -> None:
    """Two accounts sharing a domain alternate instead of one exhausting first.

    Regression for the same Devin Review finding as
    ``test_build_catalog_shared_domain_cap_does_not_starve_second_account``,
    exercised directly against the reordering helper: unit-level coverage of
    exactly which row is emitted in which position, not just the resulting
    admission counts.
    """
    rows = [
        _row("nvidia_nim", "m0"),
        _row("nvidia_nim", "m1"),
        _row("nvidia_nim", "m2"),
        _row("nvidia_nim_sub", "s0"),
        _row("nvidia_nim_sub", "s1"),
    ]
    ordered = policy._fair_admission_order(rows, zdr_endpoints=frozenset())
    assert [(row["provider"], row["model"]) for row in ordered] == [
        ("nvidia_nim", "m0"),
        ("nvidia_nim_sub", "s0"),
        ("nvidia_nim", "m1"),
        ("nvidia_nim_sub", "s1"),
        ("nvidia_nim", "m2"),
    ]


def test_fair_admission_order_never_moves_a_row_across_priority_tiers() -> None:
    """Fairness reordering never lets a worse-tier row outrank a better-tier one.

    Regression for a real correctness bug a Devin Review finding caught: an
    earlier revision of ``_fair_admission_order`` grouped every row for one
    outage domain into a single block at that domain's first appearance,
    *regardless of tier* -- so a lower-priority row (here, priced OpenAI)
    sharing a domain with a higher-priority row (free OpenAI) could get
    dragged ahead of a higher-priority row from a *different* domain (free
    OpenRouter) that happened to sort later only because of the
    ``(provider, model)`` tie-break. Concretely: sorted input
    ``[free OpenAI, free OpenRouter, priced OpenAI]`` must stay in that
    exact order -- the free OpenRouter row must never be pushed behind the
    priced OpenAI row merely because OpenAI's two rows share a domain.
    """
    rows = [
        _row("openai", "free-model", cost_evidence=policy.COST_FREE),
        _row("openrouter", "free-model", cost_evidence=policy.COST_FREE),
        _row("openai", "priced-model", cost_evidence=policy.COST_PRICED),
    ]
    ordered = policy._fair_admission_order(rows, zdr_endpoints=frozenset())
    assert [(row["provider"], row["model"]) for row in ordered] == [
        ("openai", "free-model"),
        ("openrouter", "free-model"),
        ("openai", "priced-model"),
    ]


def test_build_catalog_never_admits_a_priced_route_over_a_free_one_from_another_domain() -> None:
    """End-to-end: a tight limit must never drop a free route for a paid one.

    Same Devin Review finding as ``test_fair_admission_order_never_moves_a_
    row_across_priority_tiers``, exercised through the full public API
    rather than the internal reordering helper directly.
    """
    report = {
        "models": [
            {
                "provider": "openai",
                "model": "free-model",
                "agent_id": "oa_free",
                "is_free": True,
                **FREE_PRICE,
            },
            {
                "provider": "openai",
                "model": "priced-model",
                "agent_id": "oa_priced",
                "is_free": False,
                "prompt_price_per_1k": 0.002,
                "completion_price_per_1k": 0.008,
                "currency_code": "USD",
            },
            {
                "provider": "openrouter",
                "model": "free-model",
                "agent_id": "or_free",
                "is_free": True,
                **FREE_PRICE,
            },
        ]
    }
    result = policy.build_zdr_prioritized_catalog(
        policy.parse_discovery_report(report), limit=2, account_cap=4, pool="auto"
    )
    assert [agent["model"] for agent in result["agents"]] == ["free-model", "free-model"]
    assert [agent["provider_name"] for agent in result["agents"]] == ["openai", "openrouter"]


def test_fair_admission_order_preserves_domain_position_and_multiple_domains() -> None:
    """Reordering stays local to each multi-account domain, in its original slot.

    A single-account domain on either side of a multi-account domain stays
    exactly where it was, untouched; the multi-account domain's block still
    starts where its first row originally appeared, with only its internal
    order changed (``nvidia_nim``'s two consecutive rows are pulled apart to
    give ``nvidia_nim_sub`` a turn between them, rather than staying
    adjacent).
    """
    rows = [
        _row("bytez", "b0"),
        _row("nvidia_nim", "m0"),
        _row("nvidia_nim", "m1"),
        _row("nvidia_nim_sub", "s0"),
        _row("openrouter", "r0"),
    ]
    ordered = policy._fair_admission_order(rows, zdr_endpoints=frozenset())
    assert [(row["provider"], row["model"]) for row in ordered] == [
        ("bytez", "b0"),
        ("nvidia_nim", "m0"),
        ("nvidia_nim_sub", "s0"),
        ("nvidia_nim", "m1"),
        ("openrouter", "r0"),
    ]


@pytest.mark.parametrize(
    ("candidate", "provider", "expected"),
    [
        ("or_ds_r1", "openrouter", "or_ds_r1"),
        ("singleword", "openrouter", "openrouter_singleword"),
        ("Bytez::Qwen25-Coder!", "bytez", "bytez_qwen25_coder"),
        ("or::path", "openrouter", "or_path"),
    ],
)
def test_normalize_agent_id(candidate: str, provider: str, expected: str) -> None:
    """Agent ids are normalized to two-or-more-word snake_case."""
    assert policy._normalize_agent_id(candidate, provider) == expected


def test_is_valid_is_free_rejects_non_scalar_markers() -> None:
    """Non-scalar or missing free markers are not valid discovery evidence."""
    assert policy._is_valid_is_free([]) is False
    assert policy._is_valid_is_free({}) is False
    assert policy._is_valid_is_free(None) is False
    assert policy._is_valid_is_free("") is False
    assert policy._is_valid_is_free(0) is True


def test_free_marker_without_a_price_vector_remains_unknown() -> None:
    """A provider label cannot replace missing prompt/completion price evidence."""
    assert policy._normalize_cost_evidence(
        route="openrouter/example",
        is_free=True,
        prompt_price=None,
        completion_price=None,
        currency_code=None,
    ) == (policy.COST_UNKNOWN, None, None, None)


def test_load_zdr_endpoints_skips_rows_without_provider_or_model(tmp_path) -> None:
    """Feed rows missing a provider or model cannot pollute the route keys."""
    feed = tmp_path / "zdr.json"
    feed.write_text(
        json.dumps(
            {
                "data": [
                    {"model_name": "deepseek/deepseek-r1:free", "provider_name": "DeepSeek"},
                    {"model_name": "no-provider"},
                    {"provider_name": "NoModel"},
                ]
            }
        ),
        encoding="utf-8",
    )
    keys = policy._load_zdr_endpoints(str(feed))
    assert keys == frozenset(
        {
            "DeepSeek/deepseek/deepseek-r1:free",
            "openrouter/deepseek/deepseek-r1:free",
        }
    )


def test_load_zdr_endpoints_respects_none_feed_path(tmp_path) -> None:
    """Explicit and empty feed shapes both collapse to an empty route set."""
    empty_feed = tmp_path / "empty.json"
    empty_feed.write_text(json.dumps({"data": []}), encoding="utf-8")
    assert policy._load_zdr_endpoints(str(empty_feed)) == frozenset()


def test_route_key_prefixes_provider() -> None:
    """ZDR feed keys are matched with the provider prefix."""
    assert policy._route_key("openrouter", "deepseek/deepseek-r1:free") == (
        "openrouter/deepseek/deepseek-r1:free"
    )
    assert policy._route_key("nvidia_nim", "/leda/nemotron") == "nvidia_nim/leda/nemotron"


def test_parse_discovery_report_normalizes_rows() -> None:
    """Base URL, credential, and auth scheme fall back to the policy table."""
    rows = policy.parse_discovery_report(_report())
    assert len(rows) == 6
    bytez_row = next(row for row in rows if row["provider"] == "bytez")
    assert bytez_row["base_url"] == zdr_policy.PROVIDER_BASE_URLS["bytez"]
    assert bytez_row["credential_key"] == "BYTEZ_API_KEY"
    assert bytez_row["auth_scheme"] == "Key"
    openai_gpt41 = next(
        row for row in rows if row["provider"] == "openai" and row["model"] == "gpt-4.1"
    )
    assert openai_gpt41["is_free"] is False


@pytest.mark.parametrize(
    "report",
    [
        {},
        {"models": "not-a-list"},
        {"models": [{"model": "x", "is_free": True}]},
        {"models": [{"provider": "openai", "is_free": True}]},
        {"models": [{"provider": "not_a_provider", "model": "x", "is_free": True}]},
        {"models": [{"provider": "openai", "model": "gpt-4o-mini"}]},
        {"models": [42]},
        {"models": [{"provider": "openai", "model": "m", "is_free": None}]},
    ],
)
def test_parse_discovery_report_rejects_invalid_rows(report: dict[str, object]) -> None:
    """Malformed or unattested rows fail closed with a named PolicyError."""
    with pytest.raises(policy.PolicyError):
        policy.parse_discovery_report(report)


def test_build_catalog_is_zdr_first_and_free_only() -> None:
    """ZDR-compliant routes outrank non-ZDR free routes; priced routes stay out."""
    parsed = policy.parse_discovery_report(_report())
    result = policy.build_zdr_prioritized_catalog(
        parsed,
        limit=12,
        account_cap=4,
        zdr_endpoints=ZDR_FEED,
    )
    agents = result["agents"]
    assert agents[0]["model"] == "deepseek/deepseek-r1:free"
    assert "zdr" in agents[0]["tags"]
    models = [agent["model"] for agent in agents]
    assert "gpt-4.1" not in models
    assert result["report"]["pool"] == "orchestrator/free"
    assert result["report"]["zdr_selected_count"] == 1
    assert result["report"]["zdr_endpoints_feed_used"] is True
    assert result["report"]["selected_count"] == len(agents)
    for agent in agents:
        assert agent["disabled"] is False
        assert "cost:free" in agent["tags"]
        assert agent["credential_key"]


def test_build_auto_catalog_admits_price_evidenced_routes() -> None:
    """The Strix auto pool can use priced routes without weakening the free pool."""
    parsed = policy.parse_discovery_report(_report())
    result = policy.build_zdr_prioritized_catalog(
        parsed,
        limit=12,
        account_cap=4,
        zdr_endpoints=ZDR_FEED,
        pool="auto",
    )

    agents = result["agents"]
    priced = next(agent for agent in agents if agent["model"] == "gpt-4.1")
    assert "cost:priced" in priced["tags"]
    priced_evidence = next(row for row in parsed if row["model"] == "gpt-4.1")
    assert priced_evidence["prompt_price_per_1k"] == 0.002
    assert priced_evidence["completion_price_per_1k"] == 0.008
    assert priced_evidence["currency_code"] == "USD"
    assert result["report"]["pool"] == "orchestrator/auto"
    assert result["report"]["total_routes"] == 6
    assert result["report"]["free_selected_count"] == 5
    assert result["report"]["priced_selected_count"] == 1


def test_build_auto_catalog_order_is_independent_of_discovery_order() -> None:
    """Equivalent route tiers have deterministic provider/model priority."""
    parsed = policy.parse_discovery_report(_report())
    forward = policy.build_zdr_prioritized_catalog(parsed, pool="auto")
    reversed_result = policy.build_zdr_prioritized_catalog(reversed(parsed), pool="auto")
    assert forward["report"]["selected"] == reversed_result["report"]["selected"]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("prompt_price_per_1k", None, "lacks numeric prompt_price_per_1k"),
        ("completion_price_per_1k", -1, "invalid completion_price_per_1k"),
        ("prompt_price_per_1k", float("inf"), "invalid prompt_price_per_1k"),
        ("currency_code", "", "lacks currency_code"),
    ],
)
def test_priced_routes_require_complete_published_price_evidence(
    field: str, value: object, message: str
) -> None:
    """Auto routing rejects routes whose published cost evidence is incomplete."""
    report = _report()
    priced = report["models"][-1]
    priced[field] = value
    with pytest.raises(policy.PolicyError, match=message):
        policy.parse_discovery_report(report)


def test_build_auto_catalog_keeps_private_targets_zdr_only() -> None:
    """Private Strix auto routing still excludes every unattested route."""
    result = policy.build_zdr_prioritized_catalog(
        policy.parse_discovery_report(_report()),
        limit=12,
        account_cap=4,
        zdr_endpoints=ZDR_FEED,
        require_zdr=True,
        pool="auto",
    )

    assert [agent["model"] for agent in result["agents"]] == [
        "deepseek/deepseek-r1:free"
    ]
    assert result["report"]["priced_selected_count"] == 0


def test_build_catalog_reports_free_account_diversity() -> None:
    """Diversity counts independently credentialed accounts with free routes.

    ``free_outage_domain_diversity`` is one lower than ``free_account_
    diversity`` here: ``nvidia_nim`` and ``nvidia_nim_sub`` are two
    independent accounts (see ``test_build_catalog_counts_same_vendor_
    credentials_independently``) but share one physical upstream endpoint,
    so they collapse to a single outage domain while the other three
    providers (openrouter, openai, bytez) each keep their own.
    """
    result = policy.build_zdr_prioritized_catalog(
        policy.parse_discovery_report(_report()),
        limit=12,
        account_cap=4,
        zdr_endpoints=ZDR_FEED,
    )
    assert result["report"]["free_account_diversity"] == 5
    assert result["report"]["free_outage_domain_diversity"] == 4


def test_build_catalog_counts_same_vendor_credentials_independently() -> None:
    """Same-vendor credentials remain distinct discovery accounts.

    But they are *not* automatically distinct outage domains:
    ``free_outage_domain_diversity`` reports 1 here, not 2, because both
    rows' ``base_url`` (via ``PROVIDER_BASE_URLS``) resolve to the identical
    ``https://integrate.api.nvidia.com/v1`` upstream. Regression for a real,
    separate bug found by review during this session: #941/#945/#1468
    correctly stopped assuming these two credentials share a *model
    catalog*, but a caller deciding whether a single physical outage could
    empty the free catalog (e.g. open PR #1437's Strix ``orchestrator/free``
    eligibility gate) needs the outage-domain count, not the account count
    -- conflating the two would let this exact pair report a falsely safe
    diversity of 2 for that specific decision.
    """
    single_family_report = {
        "models": [
            {
                "provider": "nvidia_nim",
                "model": "nvidia/nemotron-3-nano-30b-a3b",
                "agent_id": "nim_nano_free",
                "is_free": True,
                **FREE_PRICE,
            },
            {
                "provider": "nvidia_nim_sub",
                "model": "meta/llama-3.3-70b-instruct",
                "agent_id": "nimsec_70b",
                "is_free": True,
                **FREE_PRICE,
            },
        ]
    }
    result = policy.build_zdr_prioritized_catalog(
        policy.parse_discovery_report(single_family_report),
        limit=12,
        account_cap=4,
    )
    assert result["report"]["free_account_diversity"] == 2
    assert result["report"]["free_outage_domain_diversity"] == 1


def test_build_catalog_collapses_differently_spelled_equivalent_endpoints() -> None:
    """A hostname-case/port/slash spelling difference cannot split one domain.

    End-to-end regression for the same Devin Review finding as
    ``test_normalize_base_url_treats_equivalent_spellings_as_one_domain``,
    exercised through ``parse_discovery_report``'s ``base_url`` override
    (the field a discovery report -- including this script's own
    ``--discovery-report`` CLI input, not only the sidecar's exact
    generation path -- may supply explicitly) rather than the unit-level
    helper directly.
    """
    differently_spelled_report = {
        "models": [
            {
                "provider": "nvidia_nim",
                "model": "nvidia/nemotron-3-nano-30b-a3b",
                "agent_id": "nim_nano_free",
                "is_free": True,
                "base_url": "https://integrate.api.nvidia.com/v1",
                **FREE_PRICE,
            },
            {
                "provider": "nvidia_nim_sub",
                "model": "meta/llama-3.3-70b-instruct",
                "agent_id": "nimsec_70b",
                "is_free": True,
                "base_url": "HTTPS://Integrate.API.Nvidia.com:443/v1/",
                **FREE_PRICE,
            },
        ]
    }
    result = policy.build_zdr_prioritized_catalog(
        policy.parse_discovery_report(differently_spelled_report),
        limit=12,
        account_cap=1,
    )
    assert result["report"]["free_outage_domain_diversity"] == 1
    # The shared domain's cap of 1 admits only the first-sorted row, not one
    # from each differently-spelled row.
    assert len(result["agents"]) == 1


def test_build_catalog_rejects_unknown_pool() -> None:
    """An unrecognized virtual pool cannot silently widen model admission."""
    with pytest.raises(policy.PolicyError, match="unsupported review pool"):
        policy.build_zdr_prioritized_catalog(
            policy.parse_discovery_report(_report()), pool="direct"
        )


def test_build_catalog_assigns_unique_priorities() -> None:
    """Each selected agent gets a distinct priority so TaskOrchestrator cannot tie on id."""
    result = policy.build_zdr_prioritized_catalog(
        policy.parse_discovery_report(_report()),
        limit=12,
        account_cap=4,
        zdr_endpoints=ZDR_FEED,
    )
    priorities = [agent["priority"] for agent in result["agents"]]
    assert priorities == sorted(priorities, reverse=True)
    assert len(priorities) == len(set(priorities))
    assert result["agents"][0]["priority"] == 0
    assert result["report"]["total_free_routes"] == 5


def test_build_catalog_applies_account_cap() -> None:
    """The admission cap is enforced per outage domain, split fairly within it.

    ``nvidia_nim`` and ``nvidia_nim_sub`` share one outage domain (both
    ``https://integrate.api.nvidia.com/v1``), so they share one ``2``-slot
    cap budget here rather than each getting their own -- with ``account_cap``
    still named for the credential-account concept it started as, but its
    grouping fixed to outage domains (see ``test_build_catalog_prevents_
    shared_endpoint_from_crowding_out_independent_providers`` for the
    concrete crowding-out scenario this exists to prevent). The shared
    budget is split round-robin across the domain's accounts (see
    ``test_build_catalog_shared_domain_cap_does_not_starve_second_account``),
    not consumed entirely by whichever one sorts first: one slot each for
    ``nvidia_nim``/``nvidia_nim_sub`` here, not two for one and zero for the
    other.
    """
    report = {
        "models": [
                {"provider": "nvidia_nim", "model": f"m{i}", "agent_id": f"nim_a{i}", "is_free": True, **FREE_PRICE}
            for i in range(6)
        ]
        + [
            {
                "provider": "nvidia_nim_sub",
                "model": f"s{i}",
                    "agent_id": f"nim_b{i}",
                    "is_free": True,
                    **FREE_PRICE,
            }
            for i in range(6)
        ]
        + [
                {"provider": "openai", "model": f"o{i}", "agent_id": f"oa_{i}", "is_free": True, **FREE_PRICE}
            for i in range(3)
        ]
    }
    result = policy.build_zdr_prioritized_catalog(
        policy.parse_discovery_report(report), limit=12, account_cap=2
    )
    account_counts: dict[str, int] = {}
    for agent in result["agents"]:
        account = policy.provider_account(agent["provider_name"])
        account_counts[account] = account_counts.get(account, 0) + 1
    assert account_counts == {"nvidia_nim": 1, "nvidia_nim_sub": 1, "openai": 2}
    assert len(result["agents"]) == 4


def test_build_catalog_prevents_shared_endpoint_from_crowding_out_independent_providers() -> None:
    """A shared-endpoint credential pair cannot out-compete independent providers.

    Regression for a real, still-open gap this session's own review found in
    the already-merged #1468 fix: #1468 correctly stopped treating
    ``nvidia_nim``/``nvidia_nim_sub`` as one *model-catalog* family, but in
    doing so also let the admission cap treat them as two fully independent
    *accounts* -- meaning the two credentials could jointly consume up to
    ``2 * account_cap`` catalog slots, all from one physical endpoint,
    crowding out a genuinely independent provider (``openrouter`` here) even
    though it has its own free routes available. With the cap correctly
    grouped by outage domain instead, the two NVIDIA credentials share one
    domain's cap budget and cannot jointly exceed it.
    """
    report = {
        "models": [
            {"provider": "bytez", "model": f"b{i}", "agent_id": f"bytez_{i}", "is_free": True, **FREE_PRICE}
            for i in range(2)
        ]
        + [
            {"provider": "nvidia_nim", "model": f"n{i}", "agent_id": f"nim_{i}", "is_free": True, **FREE_PRICE}
            for i in range(10)
        ]
        + [
            {"provider": "nvidia_nim_sub", "model": f"n{i}", "agent_id": f"nimsub_{i}", "is_free": True, **FREE_PRICE}
            for i in range(10)
        ]
        + [
            {"provider": "openrouter", "model": f"r{i}", "agent_id": f"or_{i}", "is_free": True, **FREE_PRICE}
            for i in range(2)
        ]
    }
    result = policy.build_zdr_prioritized_catalog(
        policy.parse_discovery_report(report), limit=20, account_cap=4
    )
    counts: dict[str, int] = {}
    for agent in result["agents"]:
        counts[agent["provider_name"]] = counts.get(agent["provider_name"], 0) + 1
    # NVIDIA's shared domain admits at most 4 total, split fairly (2 from
    # each credential, not 4 from whichever sorts first and 0 from the
    # other) -- leaving bytez and openrouter, each an independent domain,
    # fully admitted.
    assert counts == {"bytez": 2, "nvidia_nim": 2, "nvidia_nim_sub": 2, "openrouter": 2}
    assert result["report"]["free_account_diversity"] == 4
    assert result["report"]["free_outage_domain_diversity"] == 3


def test_build_catalog_shared_domain_cap_does_not_starve_second_account() -> None:
    """A shared domain's cap admits from every contending account, not just one.

    Regression for a Devin Review finding on this fix: the admission loop
    walks rows in strict sorted (cost-tier, ZDR, provider, model) order, so
    grouping the cap by outage domain alone was not enough -- whichever
    account's rows happened to sort first (``nvidia_nim`` before
    ``nvidia_nim_sub`` in every fixture here) could exhaust the *entire*
    shared cap before the domain's other account was considered at all, a
    narrower but just-as-real version of the crowding-out bug this file
    already fixes across domains. With both credentials offering far more
    rows than the shared cap, both must still contribute.
    """
    report = {
        "models": [
            {"provider": "nvidia_nim", "model": f"n{i}", "agent_id": f"nim_{i}", "is_free": True, **FREE_PRICE}
            for i in range(8)
        ]
        + [
            {"provider": "nvidia_nim_sub", "model": f"n{i}", "agent_id": f"nimsub_{i}", "is_free": True, **FREE_PRICE}
            for i in range(8)
        ]
    }
    result = policy.build_zdr_prioritized_catalog(
        policy.parse_discovery_report(report), limit=20, account_cap=4
    )
    counts: dict[str, int] = {}
    for agent in result["agents"]:
        counts[agent["provider_name"]] = counts.get(agent["provider_name"], 0) + 1
    assert counts == {"nvidia_nim": 2, "nvidia_nim_sub": 2}
    assert sum(counts.values()) == 4


def test_build_catalog_respects_limit() -> None:
    """The catalog never exceeds the configured agent limit."""
    report = {
        "models": [
                {"provider": "openai", "model": f"m{i}", "agent_id": f"oa_{i}", "is_free": True, **FREE_PRICE}
            for i in range(20)
        ]
    }
    result = policy.build_zdr_prioritized_catalog(
        policy.parse_discovery_report(report), limit=5, account_cap=100
    )
    assert len(result["agents"]) == 5


def test_build_catalog_fails_closed_without_free_models() -> None:
    """An empty free pool cannot serve orchestrator/free and must fail loudly."""
    report = {
        "models": [
            {
                "provider": "openai",
                "model": "gpt-4.1",
                "agent_id": "oa_41",
                "is_free": False,
                "prompt_price_per_1k": 0.002,
                "completion_price_per_1k": 0.008,
                "currency_code": "USD",
            }
        ]
    }
    with pytest.raises(policy.PolicyError, match="no free"):
        policy.build_zdr_prioritized_catalog(
            policy.parse_discovery_report(report), limit=12, account_cap=4
        )


def test_build_catalog_uses_static_table_without_feed() -> None:
    """Without a feed, OpenRouter is not granted ZDR for every free route."""
    result = policy.build_zdr_prioritized_catalog(
        policy.parse_discovery_report(_report()), limit=12, account_cap=4
    )
    assert result["report"]["zdr_endpoints_feed_used"] is False
    assert result["report"]["zdr_selected_count"] == 0
    assert "zdr" not in result["agents"][0]["tags"]
    assert "non-zdr" in result["agents"][0]["tags"]


def test_load_zdr_endpoints_none_yields_empty() -> None:
    """No feed path yields an empty route set (static table fallback)."""
    assert policy._load_zdr_endpoints(None) == frozenset()


def test_load_zdr_endpoints_parses_feed(tmp_path) -> None:
    """The documented OpenRouter feed shape parses into provider/model keys."""
    feed = tmp_path / "zdr.json"
    feed.write_text(
        json.dumps(
            {
                "data": [
                    {
                        "name": "deepseek/deepseek-r1:free",
                        "model_name": "deepseek/deepseek-r1:free",
                        "provider_name": "DeepSeek",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    assert policy._load_zdr_endpoints(str(feed)) == frozenset(
        {
            "DeepSeek/deepseek/deepseek-r1:free",
            "openrouter/deepseek/deepseek-r1:free",
        }
    )


def test_build_catalog_from_paths_writes_both_files(tmp_path) -> None:
    """Discovery + feed paths produce the catalog and audit report on disk."""
    discovery = tmp_path / "discovery.json"
    discovery.write_text(json.dumps(_report()), encoding="utf-8")
    feed = tmp_path / "zdr.json"
    feed.write_text(
        json.dumps(
            {"data": [{"model_name": "deepseek/deepseek-r1:free", "provider_name": "DeepSeek"}]}
        ),
        encoding="utf-8",
    )
    catalog = tmp_path / "agents.json"
    report = tmp_path / "report.json"

    result = policy.build_catalog_from_paths(
        str(discovery),
        out_path=str(catalog),
        report_path=str(report),
        limit=12,
        account_cap=4,
        zdr_endpoints_path=str(feed),
    )
    assert catalog.exists()
    assert report.exists()
    assert {"agents": result["agents"]} == json.loads(catalog.read_text(encoding="utf-8"))
    assert result["report"] == json.loads(report.read_text(encoding="utf-8"))


def test_main_success_writes_catalog(tmp_path) -> None:
    """CLI success returns 0 and materializes the catalog."""
    discovery = tmp_path / "discovery.json"
    discovery.write_text(json.dumps(_report()), encoding="utf-8")
    catalog = tmp_path / "agents.json"
    report = tmp_path / "report.json"
    exit_code = policy.main(
        [
            "--discovery-report",
            str(discovery),
            "--out",
            str(catalog),
            "--report",
            str(report),
            "--limit",
            "12",
            "--account-cap",
            "4",
        ]
    )
    assert exit_code == 0
    assert catalog.read_text(encoding="utf-8")


def test_main_policy_error_returns_one(tmp_path) -> None:
    """An unusable discovery report exits nonzero (fail closed)."""
    discovery = tmp_path / "discovery.json"
    discovery.write_text(json.dumps({"models": []}), encoding="utf-8")
    exit_code = policy.main(
        [
            "--discovery-report",
            str(discovery),
            "--out",
            str(tmp_path / "agents.json"),
            "--report",
            str(tmp_path / "report.json"),
        ]
    )
    assert exit_code == 1


def test_main_malformed_json_returns_one(tmp_path) -> None:
    """Unreadable or malformed JSON exits nonzero at the CLI boundary."""
    discovery = tmp_path / "discovery.json"
    discovery.write_text("{not json", encoding="utf-8")
    exit_code = policy.main(
        [
            "--discovery-report",
            str(discovery),
            "--out",
            str(tmp_path / "agents.json"),
            "--report",
            str(tmp_path / "report.json"),
        ]
    )
    assert exit_code == 1


def test_main_requires_discovery_report_arg() -> None:
    """The CLI enforces its required arguments."""
    with pytest.raises(SystemExit):
        policy.main(["--out", "x.json", "--report", "y.json"])

def test_private_catalog_admits_only_attested_zdr_routes() -> None:
    """Private-target evidence never falls through to a non-ZDR free route."""
    result = policy.build_zdr_prioritized_catalog(
        policy.parse_discovery_report(_report()),
        limit=12,
        account_cap=4,
        zdr_endpoints=ZDR_FEED,
        require_zdr=True,
    )

    assert result["agents"]
    assert all("zdr" in agent["tags"] for agent in result["agents"])
    assert all("non-zdr" not in agent["tags"] for agent in result["agents"])
    assert result["report"]["zdr_required"] is True
    assert result["report"]["selected_count"] == 1


def test_private_catalog_fails_closed_without_attested_zdr_route() -> None:
    """A private target cannot use availability as permission for non-ZDR routing."""
    with pytest.raises(policy.PolicyError, match="ZDR"):
        policy.build_zdr_prioritized_catalog(
            policy.parse_discovery_report(_report()),
            limit=12,
            account_cap=4,
            require_zdr=True,
        )
