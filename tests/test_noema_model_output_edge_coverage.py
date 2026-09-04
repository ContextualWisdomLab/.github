"""Edge regressions for Noema model-output parsing and telemetry helpers."""

from __future__ import annotations

import io
import json

from scripts.ci.noema_review_gate import (
    MAX_HTTP_ERROR_BODY_BYTES,
    _extract_http_error_served_model,
    _extract_http_error_telemetry,
    _extract_served_model,
    _strip_trailing_commas_outside_strings,
    extract_json_object,
)


class _UnreadableBody:
    """A response body whose read() fails, like a closed or drained socket."""

    def read(self, _size: int) -> bytes:
        raise OSError("body already consumed")


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


def test_extract_http_error_served_model_reads_the_canonical_field() -> None:
    body = json.dumps({"error": {"detail": {"model": "github_models/deepseek-v3"}}}).encode()
    assert _extract_http_error_served_model(io.BytesIO(body)) == "github_models/deepseek-v3"


def test_extract_http_error_served_model_fails_closed_on_unreadable_body() -> None:
    assert _extract_http_error_served_model(_UnreadableBody()) is None


def test_extract_http_error_served_model_fails_closed_on_oversized_body() -> None:
    oversized = json.dumps({"pad": "x" * MAX_HTTP_ERROR_BODY_BYTES}).encode()
    assert _extract_http_error_served_model(io.BytesIO(oversized)) is None


def test_extract_http_error_served_model_fails_closed_on_invalid_json() -> None:
    assert _extract_http_error_served_model(io.BytesIO(b"not-json")) is None


def test_extract_http_error_served_model_fails_closed_on_non_dict_payload() -> None:
    assert _extract_http_error_served_model(io.BytesIO(b"[]")) is None


def test_extract_http_error_served_model_fails_closed_on_missing_error_object() -> None:
    body = json.dumps({"error": "boom"}).encode()
    assert _extract_http_error_served_model(io.BytesIO(body)) is None


def test_extract_http_error_served_model_fails_closed_on_missing_detail_object() -> None:
    body = json.dumps({"error": {"detail": "boom"}}).encode()
    assert _extract_http_error_served_model(io.BytesIO(body)) is None


def test_extract_http_error_telemetry_ignores_a_non_dict_last_attempt() -> None:
    body = json.dumps({"error": {"detail": {"attempts": ["not-a-dict"]}}}).encode()
    assert _extract_http_error_telemetry(io.BytesIO(body)) == {}


def test_extract_http_error_telemetry_omits_unsafe_or_out_of_range_attempt_fields() -> None:
    body = json.dumps(
        {
            "error": {
                "detail": {
                    "attempts": [
                        {
                            "provider_name": "bad\r\nname",
                            "phase": "bad\r\nphase",
                            "attempt_number": 0,
                            "provider_status": 999,
                        }
                    ]
                }
            }
        }
    ).encode()
    assert _extract_http_error_telemetry(io.BytesIO(body)) == {}
