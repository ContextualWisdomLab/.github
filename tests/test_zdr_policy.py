"""Tests for scripts/ci/zdr_policy.py — the org zero-data-retention policy."""

from __future__ import annotations

import pytest

from scripts.ci import zdr_policy


def test_known_provider_names_covers_the_five_orchestrator_providers() -> None:
    """The policy table admits exactly the five CI review providers."""
    assert zdr_policy.known_provider_names() == (
        "bytez",
        "nvidia_nim",
        "nvidia_nim_sub",
        "openai",
        "openrouter",
    )


def test_provider_zdr_scope_returns_frozen_attestation() -> None:
    """Each provider resolves to a fully populated, frozen scope."""
    scope = zdr_policy.provider_zdr_scope("openrouter")
    assert scope.provider_name == "openrouter"
    assert scope.zero_data_retention is True
    assert "openrouter.ai" in scope.source
    assert scope.as_of
    assert scope.note
    with pytest.raises(AttributeError):
        scope.zero_data_retention = False


def test_provider_zdr_scope_rejects_unknown_provider() -> None:
    """An unattested provider cannot be routed around the policy table."""
    with pytest.raises(KeyError):
        zdr_policy.provider_zdr_scope("made_up_provider")


def test_is_zdr_model_rejects_non_string_model() -> None:
    """Defensive route evaluation must fail closed for malformed model values."""
    assert (
        zdr_policy.is_zdr_model(
            "openrouter",
            model=object(),  # type: ignore[arg-type]
            zdr_endpoints=frozenset({"openrouter/provider/model"}),
        )
        is False
    )


@pytest.mark.parametrize(
    ("provider_name", "expected_zdr"),
    [
        ("openrouter", False),
        ("nvidia_nim", False),
        ("nvidia_nim_sub", False),
        ("openai", False),
        ("bytez", False),
    ],
)
def test_is_zdr_model_static_table(provider_name: str, expected_zdr: bool) -> None:
    """An empty OpenRouter feed is not a grant; static non-ZDR stays non-ZDR."""
    assert zdr_policy.is_zdr_model(provider_name) is expected_zdr
    assert zdr_policy.is_zdr_model(provider_name, model="any/model") is expected_zdr


def test_is_zdr_model_openrouter_feed_is_authoritative_when_present() -> None:
    """A non-empty feed decides OpenRouter membership by exact route only."""
    feed = frozenset({"openrouter/deepseek/deepseek-r1:free", "openrouter/nvidia/foo"})
    assert (
        zdr_policy.is_zdr_model(
            "openrouter",
            model="deepseek/deepseek-r1:free",
            zdr_endpoints=feed,
        )
        is True
    )
    assert zdr_policy.is_zdr_model("openrouter", zdr_endpoints=feed) is False
    assert (
        zdr_policy.is_zdr_model(
            "openrouter",
            model="openai/gpt-4o-mini",
            zdr_endpoints=feed,
        )
        is False
    )
    assert (
        zdr_policy.is_zdr_model(
            "openrouter",
            model="deepseek/deepseek-r1:free",
            zdr_endpoints=frozenset({"openai/gpt-4o-mini"}),
        )
        is False
    )
    assert (
        zdr_policy.is_zdr_model(
            "openrouter",
            model="other/deepseek-r1:free",
            zdr_endpoints=frozenset({"openrouter/deepseek/deepseek-r1:free"}),
        )
        is False
    )


def test_route_key_strips_a_leading_slash() -> None:
    """Feed membership keys never keep a leading slash on the model slug."""
    assert zdr_policy.route_key("openrouter", "/deepseek/deepseek-r1:free") == (
        "openrouter/deepseek/deepseek-r1:free"
    )


def test_is_zdr_model_feed_evidence_matches_other_provider_model_ids() -> None:
    """OpenRouter model evidence selects matching candidates from other providers."""
    feed = frozenset({"openrouter/deepseek/deepseek-r1:free"})
    assert (
        zdr_policy.is_zdr_model(
            "nvidia_nim",
            model="deepseek/deepseek-r1:free",
            zdr_endpoints=feed,
        )
        is True
    )
    assert (
        zdr_policy.is_zdr_model(
            "nvidia_nim",
            model="nvidia/nemotron-3-nano-30b-a3b",
            zdr_endpoints=feed,
        )
        is False
    )
    assert (
        zdr_policy.is_zdr_model(
            "nvidia_nim",
            model="deepseek-r1:free",
            zdr_endpoints=feed,
        )
        is True
    )
    assert (
        zdr_policy.is_zdr_model(
            "nvidia_nim",
            model="nvidia/deepseek-r1:free",
            zdr_endpoints=frozenset(
                {
                    "openrouter/deepseek/deepseek-r1:free",
                    "openrouter/other/deepseek-r1:free",
                }
            ),
        )
        is False
    )


def test_is_zdr_model_rejects_noncanonical_feed_provider_keys() -> None:
    """Only canonical OpenRouter feed routes may provide cross-provider evidence."""
    assert (
        zdr_policy.is_zdr_model(
            "nvidia_nim",
            model="deepseek/deepseek-r1:free",
            zdr_endpoints=frozenset({"nvidia_nim/deepseek/deepseek-r1:free"}),
        )
        is False
    )


@pytest.mark.parametrize(
    "feed_key",
    [
        "openrouter//deepseek/deepseek-r1:free",
        "openrouter/deepseek/deepseek-r1:free/",
        "openrouter/",
    ],
)
def test_is_zdr_model_rejects_feed_keys_with_empty_segments(feed_key: str) -> None:
    """Malformed feed paths cannot grant suffix-based ZDR evidence."""
    assert (
        zdr_policy.is_zdr_model(
            "nvidia_nim",
            model="deepseek/deepseek-r1:free",
            zdr_endpoints=frozenset({feed_key}),
        )
        is False
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (True, True),
        (1, True),
        (1.0, True),
        ("true", True),
        ("TRUE", True),
        ("yes", True),
        ("1", True),
        (False, False),
        (0, False),
        (0.0, False),
        ("false", False),
        ("False", False),
        ("", False),
        (None, False),
    ],
)
def test_is_free_route(value: object, expected: bool) -> None:
    """Only explicitly truthy free markers count; strings are case-folded."""
    assert zdr_policy.is_free_route(value) is expected
