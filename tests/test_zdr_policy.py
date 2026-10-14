"""Tests for scripts/ci/zdr_policy.py — the org zero-data-retention policy."""

from __future__ import annotations

import datetime

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


def test_route_key_strips_a_leading_slash() -> None:
    """Feed membership keys never keep a leading slash on the model slug."""
    assert zdr_policy.route_key("openrouter", "/deepseek/deepseek-r1:free") == (
        "openrouter/deepseek/deepseek-r1:free"
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

def test_every_attestation_carries_a_valid_until_after_its_as_of() -> None:
    """No citation may age silently: expiry is required and must follow as_of."""
    for name in zdr_policy.known_provider_names():
        scope = zdr_policy.provider_zdr_scope(name)
        as_of = datetime.date.fromisoformat(scope.as_of)
        valid_until = datetime.date.fromisoformat(scope.valid_until)
        assert valid_until > as_of, name
        assert valid_until == as_of + datetime.timedelta(
            days=zdr_policy.ATTESTATION_REVIEW_WINDOW_DAYS
        ), name


def test_attestation_is_current_on_and_after_the_expiry_boundary() -> None:
    """The window is inclusive of valid_until and closed the day after."""
    scope = zdr_policy.provider_zdr_scope("openrouter")
    valid_until = datetime.date.fromisoformat(scope.valid_until)
    assert zdr_policy.attestation_is_current("openrouter", valid_until) is True
    assert (
        zdr_policy.attestation_is_current(
            "openrouter", valid_until - datetime.timedelta(days=1)
        )
        is True
    )
    assert (
        zdr_policy.attestation_is_current(
            "openrouter", valid_until + datetime.timedelta(days=1)
        )
        is False
    )


def test_attestation_is_current_rejects_unknown_provider() -> None:
    """Staleness cannot be asked about a provider outside the policy table."""
    with pytest.raises(KeyError):
        zdr_policy.attestation_is_current("made_up_provider", datetime.date(2026, 9, 5))


def test_expired_provider_names_is_empty_while_every_citation_is_current() -> None:
    """A date inside every window reports nothing to re-read."""
    assert zdr_policy.expired_provider_names(datetime.date(2026, 9, 5)) == ()


def test_expired_provider_names_reports_only_the_lapsed_entries() -> None:
    """Entries expire independently and are reported sorted."""
    assert zdr_policy.expired_provider_names(datetime.date(2026, 11, 26)) == (
        "bytez",
        "openai",
        "openrouter",
    )
    assert zdr_policy.expired_provider_names(datetime.date(2999, 12, 31)) == (
        zdr_policy.known_provider_names()
    )


def test_is_zdr_model_ignores_expiry_when_no_date_is_supplied() -> None:
    """Omitting today leaves the existing table-only decision untouched."""
    feed = frozenset({"openrouter/deepseek/deepseek-r1:free"})
    assert (
        zdr_policy.is_zdr_model(
            "openrouter", model="deepseek/deepseek-r1:free", zdr_endpoints=feed
        )
        is True
    )


def test_is_zdr_model_fails_closed_on_an_expired_attestation() -> None:
    """An unre-read citation grants nothing, feed membership notwithstanding."""
    feed = frozenset({"openrouter/deepseek/deepseek-r1:free"})
    assert (
        zdr_policy.is_zdr_model(
            "openrouter",
            model="deepseek/deepseek-r1:free",
            zdr_endpoints=feed,
            today=datetime.date(2026, 9, 5),
        )
        is True
    )
    assert (
        zdr_policy.is_zdr_model(
            "openrouter",
            model="deepseek/deepseek-r1:free",
            zdr_endpoints=feed,
            today=datetime.date(2026, 11, 26),
        )
        is False
    )


def test_is_zdr_model_expiry_cannot_promote_a_non_zdr_provider() -> None:
    """Expiry only ever removes a grant; a not-ZDR entry stays not-ZDR."""
    for today in (datetime.date(2026, 9, 5), datetime.date(2999, 12, 31)):
        assert zdr_policy.is_zdr_model("nvidia_nim", model="any/model", today=today) is False
