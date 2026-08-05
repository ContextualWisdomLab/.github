"""Complete behavioral contracts for the central log-redaction primitive."""

from __future__ import annotations

import io
import sys

from scripts.ci import redact_sensitive_log as redactor


def _synthetic_provider_token() -> str:
    """Construct a provider-shaped value without storing a scanner literal."""

    return "gh" + "p_" + ("B" * 36)


def test_json_sensitive_keys_and_scalar_values_preserve_safe_evidence() -> None:
    """Sensitive JSON values are replaced while ordinary scalars remain intact."""

    assert redactor.redact_text(
        '{"api_key":"value","count":3,"enabled":true,"empty":null}\n'
    ) == (
        '{"api_key":"[REDACTED]","count":3,"enabled":true,"empty":null}\n'
    )


def test_assignment_parser_covers_quoted_keys_values_and_incomplete_forms() -> None:
    """Quoted assignments redact values and malformed empty forms make progress."""

    assert redactor.redact_text("'token' = 'quoted value'") == (
        "'token' = [REDACTED]"
    )
    assert redactor.redact_text("token='escaped\\' value'") == (
        "token=[REDACTED]"
    )
    assert redactor.redact_text("'token=value") == (
        "'token=[REDACTED]"
    )
    assert redactor.redact_text("token") == "token"
    assert redactor.redact_text("token=") == "token="
    assert redactor.redact_text("token=,") == "token=,"


def test_unstructured_patterns_cover_basic_jwt_and_provider_values() -> None:
    """Independent credential formats share one non-JSON redaction boundary."""

    provider_value = _synthetic_provider_token()
    assert redactor.redact_text("Authorization: Basic opaque-value") == (
        "Authorization: [REDACTED] [REDACTED]"
    )
    assert redactor.redact_text("header.payload.signature") == redactor.REDACTED
    assert redactor.redact_text(provider_value) == redactor.REDACTED


def test_command_argument_redaction_preserves_non_sensitive_options() -> None:
    """Only explicit sensitive option values and credential shapes are replaced."""

    assert redactor.redact_command_arguments(
        ["tool", "--mode=safe", "--token"]
    ) == ["tool", "--mode=safe", "--token"]
    assert redactor.redact_shell_command("") == ""


def test_empty_text_and_cli_main_preserve_stream_contract(monkeypatch) -> None:
    """Empty input is stable and the CLI writes only the redacted stream."""

    assert redactor.redact_text("") == ""
    input_stream = io.StringIO("password=value\nordinary\n")
    output_stream = io.StringIO()
    monkeypatch.setattr(sys, "stdin", input_stream)
    monkeypatch.setattr(sys, "stdout", output_stream)

    assert redactor.main() == 0
    assert output_stream.getvalue() == "password=[REDACTED]\nordinary\n"
