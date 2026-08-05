"""Additional fail-closed JSON redaction boundary tests."""

from __future__ import annotations

import json

import pytest

from scripts.ci import redact_sensitive_log as redactor


def test_json_object_keys_are_redacted_when_the_key_contains_a_provider_token() -> None:
    """Credential-shaped JSON object keys must not survive structured redaction."""
    provider_token = "nv" + "api-" + ("K" * 24)
    raw = json.dumps({provider_token: "ordinary-value"})

    redacted = redactor.redact_text(raw)

    assert provider_token not in redacted
    assert redactor.REDACTED in redacted


def test_json_object_keys_are_redacted_when_the_key_contains_an_assignment() -> None:
    """Assignment-shaped JSON object keys must pass through the shared scanner."""
    assignment_key = "api_key=" + ("S" * 24)
    raw = json.dumps({assignment_key: "ordinary-value"})

    redacted = redactor.redact_text(raw)

    assert assignment_key not in redacted
    assert redactor.REDACTED in redacted


@pytest.mark.parametrize(
    "sensitive_key",
    [
        "clientSecret",
        "databasePassword",
        "serviceAuthorizationHeader",
        "privateKeyMaterial",
        "sessionTokenValue",
    ],
)
def test_concatenated_sensitive_json_keys_redact_their_values(
    sensitive_key: str,
) -> None:
    """CamelCase and concatenated credential keys cannot retain plain values."""
    secret_value = "plain-secret"

    redacted = redactor.redact_text(json.dumps({sensitive_key: secret_value}))

    assert secret_value not in redacted
    assert redactor.REDACTED in redacted


def test_leading_whitespace_does_not_bypass_structured_json_redaction() -> None:
    """Indented JSON diagnostics retain indentation but never a sensitive value."""
    secret_value = "plain-secret"

    redacted = redactor.redact_text(
        "   " + json.dumps({"clientSecret": secret_value}) + "\n"
    )

    assert redacted == f'   {{"clientSecret":"{redactor.REDACTED}"}}\n'
    assert secret_value not in redacted


def test_malformed_json_like_diagnostic_fails_closed() -> None:
    """A JSON-looking line that cannot be parsed is replaced as one safe record."""
    raw = '  {"clientSecret":"plain-secret"\n'

    assert redactor.redact_text(raw) == f"  {redactor.REDACTED}\n"


@pytest.mark.parametrize(
    "raw",
    [
        "tool --token plain-secret --name safe",
        'tool --password "plain secret" --name safe',
        "tool --api-key 'plain secret' --name safe",
    ],
)
def test_echoed_separate_sensitive_options_are_redacted(raw: str) -> None:
    """Child-process command echoes cannot disclose separate option values."""
    redacted = redactor.redact_text(raw)

    assert "plain-secret" not in redacted
    assert "plain secret" not in redacted
    assert redactor.REDACTED in redacted


def test_sensitive_option_without_value_does_not_consume_the_next_option() -> None:
    """A missing value leaves the following option visible for diagnosis."""
    raw = "tool --token --name safe"

    assert redactor.redact_text(raw) == raw


def test_long_ordinary_identifier_does_not_restart_assignment_scanning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One long ordinary token must cause only one assignment classification."""
    original = redactor._consume_sensitive_assignment
    starts: list[int] = []

    def instrument(text: str, start: int):
        starts.append(start)
        return original(text, start)

    monkeypatch.setattr(redactor, "_consume_sensitive_assignment", instrument)
    ordinary_identifier = "a" * 100_000

    assert redactor.redact_text(ordinary_identifier) == ordinary_identifier
    assert starts == [0]


def test_oversized_assignment_key_is_redacted_conservatively() -> None:
    """An oversized key cannot evade redaction by exceeding matcher limits."""
    oversized_key = "ordinary" * (redactor.MAX_IDENTIFIER_CHARS + 1)
    secret_value = "plain-secret"

    redacted = redactor.redact_text(f"{oversized_key}={secret_value}")

    assert secret_value not in redacted
    assert redacted.endswith(redactor.REDACTED)


def test_json_depth_limit_replaces_the_remaining_subtree() -> None:
    """Excessive valid JSON nesting is redacted before recursive publication."""
    nested: object = "plain-secret"
    for _ in range(redactor.MAX_JSON_DEPTH + 1):
        nested = {"safe": nested}

    encoded = json.dumps(redactor._redact_json(nested))

    assert "plain-secret" not in encoded
    assert redactor.REDACTED in encoded


def test_json_parser_recursion_failure_redacts_the_entire_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A parser recursion failure must not fall back to weaker key handling."""

    def raise_recursion(_value: str) -> object:
        raise RecursionError("synthetic deeply nested diagnostic")

    monkeypatch.setattr(redactor.json, "loads", raise_recursion)

    assert (
        redactor.redact_text('{"api_key":"plain-secret"}\n')
        == f"{redactor.REDACTED}\n"
    )


def test_json_encoder_recursion_failure_redacts_the_entire_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An encoder recursion failure follows the same fail-closed line boundary."""

    def raise_recursion(*_args, **_kwargs) -> str:
        raise RecursionError("synthetic encoder recursion")

    monkeypatch.setattr(redactor.json, "dumps", raise_recursion)

    assert (
        redactor.redact_text('{"message":"ordinary"}\n')
        == f"{redactor.REDACTED}\n"
    )
