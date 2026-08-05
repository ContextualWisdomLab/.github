"""Complete behavioral contracts for the central log-redaction primitive."""

from __future__ import annotations

import io
import runpy
import sys
from pathlib import Path

import pytest

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
    assert redactor.redact_text("token='unterminated") == (
        "token=[REDACTED]"
    )
    assert redactor.redact_text("'token=value") == (
        "'token=[REDACTED]"
    )
    assert redactor.redact_text("token") == "token"
    assert redactor.redact_text("token text") == "token text"
    assert redactor.redact_text("token=") == "token="
    assert redactor.redact_text("token=,") == "token=,"
    assert redactor.redact_text("token=value ordinary") == (
        "token=[REDACTED] ordinary"
    )
    assert redactor.redact_text("1token=value") == (
        "1token=[REDACTED]"
    )


def test_unstructured_patterns_cover_basic_jwt_and_provider_values() -> None:
    """Independent credential formats share one non-JSON redaction boundary."""

    provider_value = _synthetic_provider_token()
    assert redactor.redact_text("Authorization: Basic opaque-value") == (
        "Authorization: [REDACTED]"
    )
    assert redactor.redact_text("Basic opaque-value") == "Basic [REDACTED]"
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


def test_module_entry_point_exits_after_redacting_standard_input(monkeypatch) -> None:
    """Direct script execution preserves the same redacted stream contract."""

    input_stream = io.StringIO("secret=value\n")
    output_stream = io.StringIO()
    monkeypatch.setattr(sys, "stdin", input_stream)
    monkeypatch.setattr(sys, "stdout", output_stream)

    with pytest.raises(SystemExit) as raised:
        runpy.run_path(str(Path(redactor.__file__).resolve()), run_name="__main__")

    assert raised.value.code == 0
    assert output_stream.getvalue() == "secret=[REDACTED]\n"
