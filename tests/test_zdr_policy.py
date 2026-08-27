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


@pytest.mark.parametrize(
    ("provider_name", "expected_zdr"),
    [
        ("openrouter", True),
        ("nvidia_nim", False),
        ("nvidia_nim_sub", False),
        ("openai", False),
        ("bytez", False),
    ],
)
def test_is_zdr_model_static_table(provider_name: str, expected_zdr: bool) -> None:
    """Without a live endpoint feed the dated static table is authoritative."""
    assert zdr_policy.is_zdr_model(provider_name) is expected_zdr


def test_is_zdr_model_openrouter_feed_is_authoritative_when_present() -> None:
    """A non-empty ZDR endpoint feed decides membership for openrouter routes."""
    feed = frozenset({"openrouter/deepseek/deepseek-r1:free", "openrouter/nvidia/foo"})
    assert zdr_policy.is_zdr_model("openrouter", zdr_endpoints=feed) is True
    assert (
        zdr_policy.is_zdr_model(
            "openrouter", zdr_endpoints=frozenset({"openai/gpt-4o-mini"})
        )
        is False
    )


def test_is_zdr_model_feed_only_applies_to_the_openrouter_scope() -> None:
    """Static non-ZDR providers stay non-ZDR even if a route key is present."""
    feed = frozenset({"nvidia_nim/nvidia/nemotron-3-nano-30b-a3b"})
    assert zdr_policy.is_zdr_model("nvidia_nim", zdr_endpoints=feed) is False


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