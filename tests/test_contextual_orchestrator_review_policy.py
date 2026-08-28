"""Tests for scripts/ci/contextual_orchestrator_review_policy.py."""

from __future__ import annotations

import json

import pytest

from scripts.ci import contextual_orchestrator_review_policy as policy
from scripts.ci import zdr_policy

ZDR_FEED = frozenset({"openrouter/deepseek/deepseek-r1:free"})


def _report() -> dict[str, object]:
    return {
        "models": [
            {
                "provider": "openrouter",
                "model": "deepseek/deepseek-r1:free",
                "agent_id": "or_ds_r1",
                "is_free": True,
            },
            {
                "provider": "nvidia_nim",
                "model": "deepseek/deepseek-r1:free",
                "agent_id": "nim_deepseek_r1",
                "is_free": True,
            },
            {
                "provider": "nvidia_nim_sub",
                "model": "meta/llama-3.3-70b-instruct",
                "agent_id": "nimsec_70b",
                "is_free": True,
            },
            {
                "provider": "openai",
                "model": "gpt-4o-mini",
                "agent_id": "openai_gpt_4o_mini",
                "is_free": True,
            },
            {
                "provider": "bytez",
                "model": "qwen2.5-coder",
                "agent_id": "bytez_qwen25_coder",
                "is_free": True,
            },
            {
                "provider": "openai",
                "model": "gpt-4.1",
                "agent_id": "openai_gpt_41",
                "is_free": False,
            },
        ]
    }


def test_provider_family_groups_nvidia_keys() -> None:
    """The primary and secondary NVIDIA keys share one outage-domain family."""
    assert policy.provider_family("nvidia_nim") == "nvidia_nim"
    assert policy.provider_family("nvidia_nim_sub") == "nvidia_nim"
    assert policy.provider_family("openai") == "openai"


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
    result = policy.build_zdr_prioritized_catalog(
        policy.parse_discovery_report(_report()),
        limit=12,
        family_cap=4,
        zdr_endpoints=ZDR_FEED,
    )
    agents = result["agents"]
    assert agents[0]["model"] == "deepseek/deepseek-r1:free"
    assert agents[0]["provider_name"] == "nvidia_nim"
    assert "zdr" in agents[0]["tags"]
    assert all(agent["provider_name"] != "openrouter" for agent in agents)
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


def test_build_catalog_applies_feed_model_evidence_to_other_provider() -> None:
    """A matching model identity can attest a discovered provider row."""
    result = policy.build_zdr_prioritized_catalog(
        policy.parse_discovery_report(
            {
                "models": [
                    {
                        "provider": "nvidia_nim",
                        "model": "deepseek/deepseek-r1:free",
                        "agent_id": "nim_deepseek_r1",
                        "is_free": True,
                    }
                ]
            }
        ),
        zdr_endpoints=ZDR_FEED,
    )
    assert result["agents"][0]["provider_name"] == "nvidia_nim"
    assert "zdr" in result["agents"][0]["tags"]
    assert result["report"]["zdr_selected_count"] == 1
    assert result["report"]["zdr_sources"] == [
        "https://openrouter.ai/api/v1/endpoints/zdr"
    ]


def test_build_catalog_assigns_unique_priorities() -> None:
    """Each selected agent gets a distinct priority so TaskOrchestrator cannot tie on id."""
    result = policy.build_zdr_prioritized_catalog(
        policy.parse_discovery_report(_report()),
        limit=12,
        family_cap=4,
        zdr_endpoints=ZDR_FEED,
    )
    priorities = [agent["priority"] for agent in result["agents"]]
    assert priorities == sorted(priorities, reverse=True)
    assert len(priorities) == len(set(priorities))
    assert result["agents"][0]["priority"] == 0
    assert result["report"]["total_free_routes"] == 4
    assert result["report"]["evidence_only_free_routes"] == 1


def test_build_catalog_applies_family_cap() -> None:
    """A family cap keeps one outage domain from absorbing the pool."""
    report = {
        "models": [
            {"provider": "nvidia_nim", "model": f"m{i}", "agent_id": f"nim_a{i}", "is_free": True}
            for i in range(6)
        ]
        + [
            {
                "provider": "nvidia_nim_sub",
                "model": f"s{i}",
                "agent_id": f"nim_b{i}",
                "is_free": True,
            }
            for i in range(6)
        ]
        + [
            {"provider": "openai", "model": f"o{i}", "agent_id": f"oa_{i}", "is_free": True}
            for i in range(3)
        ]
    }
    result = policy.build_zdr_prioritized_catalog(
        policy.parse_discovery_report(report), limit=12, family_cap=2
    )
    family_counts: dict[str, int] = {}
    for agent in result["agents"]:
        family = policy.provider_family(agent["provider_name"])
        family_counts[family] = family_counts.get(family, 0) + 1
    assert family_counts["nvidia_nim"] == 2
    assert family_counts["openai"] == 2


def test_build_catalog_respects_limit() -> None:
    """The catalog never exceeds the configured agent limit."""
    report = {
        "models": [
            {"provider": "openai", "model": f"m{i}", "agent_id": f"oa_{i}", "is_free": True}
            for i in range(20)
        ]
    }
    result = policy.build_zdr_prioritized_catalog(
        policy.parse_discovery_report(report), limit=5, family_cap=100
    )
    assert len(result["agents"]) == 5


def test_build_catalog_fails_closed_without_free_models() -> None:
    """An empty free pool cannot serve orchestrator/free and must fail loudly."""
    report = {
        "models": [
            {"provider": "openai", "model": "gpt-4.1", "agent_id": "oa_41", "is_free": False}
        ]
    }
    with pytest.raises(policy.PolicyError, match="no free"):
        policy.build_zdr_prioritized_catalog(
            policy.parse_discovery_report(report), limit=12, family_cap=4
        )


def test_build_catalog_fails_closed_when_only_openrouter_is_free() -> None:
    """OpenRouter evidence alone cannot become a routed upstream."""
    rows = policy.parse_discovery_report(
        {
            "models": [
                {
                    "provider": "openrouter",
                    "model": "deepseek/deepseek-r1:free",
                    "agent_id": "or_ds_r1",
                    "is_free": True,
                }
            ]
        }
    )
    with pytest.raises(policy.PolicyError, match="no free"):
        policy.build_zdr_prioritized_catalog(rows, zdr_endpoints=ZDR_FEED)


def test_build_catalog_uses_static_table_without_feed() -> None:
    """Without a feed, OpenRouter is not granted ZDR for every free route."""
    result = policy.build_zdr_prioritized_catalog(
        policy.parse_discovery_report(_report()), limit=12, family_cap=4
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
        family_cap=4,
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
            "--family-cap",
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
        family_cap=4,
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
            family_cap=4,
            require_zdr=True,
        )
