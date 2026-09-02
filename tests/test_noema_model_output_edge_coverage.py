"""Edge regressions for Noema model-output parsing and telemetry helpers."""

from __future__ import annotations

from scripts.ci.noema_review_gate import (
    _extract_served_model,
    _strip_trailing_commas_outside_strings,
    extract_json_object,
)


def test_trailing_comma_stripper_preserves_escaped_string_content() -> None:
    """Quote/escape state must preserve backslashes and commas inside strings."""
    source = '{"value":"x\\\\y,",}'
    assert _strip_trailing_commas_outside_strings(source) == '{"value":"x\\\\y,"}'


def test_trailing_comma_stripper_handles_whitespace_before_comma() -> None:
    """Whitespace before a structural trailing comma must not hide the prior value."""
    source = '{"value": 1   ,   }'
    assert _strip_trailing_commas_outside_strings(source) == '{"value": 1      }'


def test_extract_json_object_recovers_only_lossless_trailing_comma() -> None:
    """The local second chance must recover a syntactically trailing comma."""
    assert extract_json_object('{"ok": true,}') == {"ok": True}


def test_extract_served_model_rejects_malformed_json() -> None:
    """Malformed response metadata must never fabricate a serving-model identity."""
    assert _extract_served_model("not-json") is None
