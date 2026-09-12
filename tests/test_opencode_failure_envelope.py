"""Unit coverage for bounded OpenCode provider-failure metadata."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.ci import opencode_failure_envelope as envelope


def test_failure_artifact_tail_budget_remains_16_kib() -> None:
    """The canonical successor preserves the carried 16 KiB JSONL tail bound."""
    assert envelope.MAX_FAILURE_FILE_BYTES == 16_384


def test_read_bounded_handles_missing_and_oversized_files(tmp_path: Path) -> None:
    """Missing artifacts are empty and large artifacts retain their true size."""
    assert envelope._read_bounded(tmp_path / "missing") == (b"", 0)
    large = tmp_path / "large"
    large.write_bytes(b"x" * (envelope.MAX_FAILURE_FILE_BYTES + 2))
    raw, byte_count = envelope._read_bounded(large)
    assert raw == b""
    assert byte_count == envelope.MAX_FAILURE_FILE_BYTES + 2
    assert envelope._last_error_event(raw) is None
    assert (
        envelope._last_error_event(b"x" * (envelope.MAX_FAILURE_FILE_BYTES + 1))
        is None
    )

    final_event = b'{"type":"error","error":{"data":{}}}\n'
    large.write_bytes(b"x" * envelope.MAX_FAILURE_FILE_BYTES + b"\n" + final_event)
    raw, byte_count = envelope._read_bounded(large)
    assert raw == final_event
    assert byte_count == envelope.MAX_FAILURE_FILE_BYTES + 1 + len(final_event)

    event_prefix = b'{"type":"error","error":{"padding":"'
    event_suffix = b'"}}\n'
    aligned_event = (
        event_prefix
        + b"x"
        * (envelope.MAX_FAILURE_FILE_BYTES - len(event_prefix) - len(event_suffix))
        + event_suffix
    )
    assert len(aligned_event) == envelope.MAX_FAILURE_FILE_BYTES
    large.write_bytes(b"x\n" + aligned_event)
    raw, byte_count = envelope._read_bounded(large)
    assert raw == aligned_event
    assert byte_count == 2 + envelope.MAX_FAILURE_FILE_BYTES
    assert envelope._last_error_event(raw) is not None


@pytest.mark.parametrize(
    ("value", "allowed_values", "expected"),
    [
        ("queue_admission", frozenset({"queue_admission"}), "queue_admission"),
        ("not_allowlisted", frozenset({"queue_admission"}), None),
        (1, frozenset({"queue_admission"}), None),
    ],
)
def test_safe_enum_accepts_only_exact_allowlisted_tokens(
    value: object, allowed_values: frozenset[str], expected: str | None
) -> None:
    """Lexical shape alone cannot make provider data public."""
    assert envelope._safe_enum(value, allowed_values) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (429, 429),
        ("503", 503),
        (True, None),
        (99, None),
        (600, None),
        ("429 ", None),
        ("abc", None),
    ],
)
def test_safe_http_status_rejects_non_http_values(
    value: object, expected: int | None
) -> None:
    """Only three-digit HTTP status values survive normalization."""
    assert envelope._safe_http_status(value) == expected


def test_last_error_event_uses_last_valid_error_and_rejects_bad_utf8() -> None:
    """JSON-lines noise is ignored while invalid UTF-8 fails closed."""
    raw = (
        b"not-json\n"
        b'{"type":"text"}\n'
        b'{"type":"error","error":{"name":"First"}}\n'
        b'{"type":"error","error":{"name":"Last"}}\n'
    )
    assert envelope._last_error_event(raw) == {
        "type": "error",
        "error": {"name": "Last"},
    }
    assert envelope._last_error_event(b"\xff") is None


@pytest.mark.parametrize(
    ("data", "expected", "malformed"),
    [
        ({"detail": {"phase": "direct"}}, {"phase": "direct"}, False),
        ({"error_detail": {"phase": "legacy"}}, {"phase": "legacy"}, False),
        (
            {"body": {"error": {"detail": {"phase": "mapping"}}}},
            {"phase": "mapping"},
            False,
        ),
        (
            {"response_body": '{"error":{"detail":{"phase":"json"}}}'},
            {"phase": "json"},
            False,
        ),
        ({"responseBody": "[]"}, {}, True),
        ({"responseBody": "not-json"}, {}, True),
        ({"responseBody": "\ud800"}, {}, True),
        ({"responseBody": "x" * (envelope.MAX_GATEWAY_BODY_BYTES + 1)}, {}, True),
        ({"body": []}, {}, True),
        ({"body": {}}, {}, False),
    ],
)
def test_gateway_detail_accepts_only_known_bounded_shapes(
    data: dict[str, object], expected: dict[str, object], malformed: bool
) -> None:
    """Only canonical detail containers are available to the formatter."""
    assert envelope._gateway_detail(data) == (expected, malformed)


def test_gateway_detail_fails_closed_on_excessive_json_depth() -> None:
    """Deep provider envelopes cannot crash diagnostics with RecursionError."""
    deeply_nested = "[" * 10_000 + "0" + "]" * 10_000

    assert envelope._gateway_detail({"responseBody": deeply_nested}) == ({}, True)


def test_gateway_detail_rejects_response_body_over_16_kib() -> None:
    """The canonical gateway response-body parse budget is exactly 16 KiB."""
    body = json.dumps({"detail": {"padding": "x" * 16_384}})
    assert 16_384 < len(body.encode("utf-8")) < 32_768

    assert envelope._gateway_detail({"responseBody": body}) == ({}, True)


def test_gateway_detail_rejects_oversized_mapping_body() -> None:
    """Dictionary gateway bodies obey the same 16 KiB input boundary."""
    body = {"detail": {"padding": "x" * envelope.MAX_GATEWAY_BODY_BYTES}}

    assert envelope._gateway_detail({"responseBody": body}) == ({}, True)


def test_format_failure_metadata_rejects_conflicting_gateway_aliases(
    tmp_path: Path,
) -> None:
    """Conflicting validated causes across body aliases fail closed."""
    json_path = tmp_path / "event.jsonl"
    stderr_path = tmp_path / "stderr"
    json_path.write_text(
        json.dumps(
            {
                "type": "error",
                "error": {
                    "data": {
                        "responseBody": {
                            "error": {
                                "detail": {
                                    "terminal_reason": "payment_required",
                                    "attempts": [{"provider_status": 402}],
                                }
                            }
                        },
                        "body": {
                            "error": {
                                "detail": {
                                    "terminal_reason": "provider_unavailable",
                                    "attempts": [{"provider_status": 503}],
                                }
                            }
                        },
                    }
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    stderr_path.write_text("", encoding="utf-8")

    rendered = envelope.format_failure_metadata(json_path, stderr_path, 1)

    assert "class=provider-error" in rendered
    assert "reason=unknown" in rendered
    assert "http-status=unknown" in rendered
    assert "class=credit-exhausted" not in rendered
    assert "class=provider-5xx" not in rendered


def test_last_error_event_fails_closed_on_excessive_json_depth() -> None:
    """Deep top-level JSONL events cannot crash failure diagnostics."""
    deeply_nested = (
        '{"type":"error","error":{"data":'
        + "[" * 5_000
        + "0"
        + "]" * 5_000
        + "}}\n"
    ).encode("utf-8")

    assert len(deeply_nested) < envelope.MAX_FAILURE_FILE_BYTES
    assert envelope._last_error_event(deeply_nested) is None


@pytest.mark.parametrize(
    ("has_json", "has_stderr", "status", "reason", "malformed", "event", "expected"),
    [
        (False, False, 413, None, False, True, "request-too-large"),
        (False, False, None, "request_too_large", False, True, "request-too-large"),
        (False, False, None, "context_overflow", False, True, "context-window"),
        (False, False, 402, None, False, True, "credit-exhausted"),
        (False, False, None, "insufficient_quota", False, True, "quota-or-budget"),
        (False, False, None, "no_eligible_route", False, True, "model-pool-exhausted"),
        (False, False, None, "model_not_found", False, True, "model-unavailable"),
        (False, False, 429, None, False, True, "rate-limit"),
        (False, False, 403, None, False, True, "authentication-or-permission"),
        (False, False, None, "timeout", False, True, "timeout"),
        (False, False, 502, None, False, True, "provider-5xx"),
        (False, False, 502, "payment_required", False, True, "provider-error"),
        (True, False, None, None, True, True, "malformed-response"),
        (True, False, None, None, False, False, "malformed-response"),
        (True, False, None, None, False, True, "provider-error"),
        (False, True, None, None, False, False, "provider-error"),
        (False, False, None, None, False, False, "no-provider-detail"),
    ],
)
def test_failure_class_preserves_distinct_safe_causes(
    has_json: bool,
    has_stderr: bool,
    status: int | None,
    reason: str | None,
    malformed: bool,
    event: bool,
    expected: str,
) -> None:
    """Each accepted causal category remains distinguishable."""
    assert (
        envelope._failure_class(
            status=status,
            reason=reason,
            malformed_body=malformed,
            has_json_artifact=has_json,
            has_stderr_artifact=has_stderr,
            has_event=event,
        )
        == expected
    )


def test_format_failure_metadata_handles_direct_detail_and_string_status(
    tmp_path: Path,
) -> None:
    """Direct gateway detail fields produce one deterministic safe line."""
    json_path = tmp_path / "event.jsonl"
    stderr_path = tmp_path / "stderr"
    json_path.write_text(
        json.dumps(
            {
                "type": "error",
                "error": {
                    "name": "HTTPError",
                    "data": {
                        "status_code": "503",
                        "detail": {
                            "phase": "response_error",
                            "stop_reason": "provider_unavailable",
                            "model": "nvidia/model:free",
                            "attempts": [
                                {
                                    "provider": "nvidia_nim",
                                    "phase": "connecting",
                                }
                            ],
                        },
                    },
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    stderr_path.write_text("", encoding="utf-8")

    rendered = envelope.format_failure_metadata(json_path, stderr_path, 5)

    assert "class=provider-5xx" in rendered
    assert "phase=connecting" in rendered
    assert "reason=provider_unavailable" in rendered
    assert "provider=unknown" in rendered
    assert "http-status=503" in rendered
    assert "exception=unknown" in rendered
    assert "duration-seconds=5" in rendered
    assert "served-model=unknown" in rendered


def test_format_failure_metadata_limits_attempts_and_defaults_fields(
    tmp_path: Path,
) -> None:
    """Oversized attempt arrays and unsafe scalars degrade to explicit absence."""
    secret = "github" + "_pat_" + "NEVERPRINTTHISVALUE123456"
    json_path = tmp_path / "event.jsonl"
    stderr_path = tmp_path / "stderr"
    json_path.write_text(
        json.dumps(
            {
                "type": "error",
                "error": {
                    "name": f"bad exception {secret}",
                    "data": {
                        "code": f"unsafe code {secret}",
                        "detail": {
                            "error_code": f"unsafe reason {secret}",
                            "attempts": [{}] * 65,
                            "model": f"unsafe model {secret}",
                        },
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    stderr_path.write_text("", encoding="utf-8")

    rendered = envelope.format_failure_metadata(json_path, stderr_path, -4)

    assert "phase=unknown reason=provider_error provider=unknown" in rendered
    assert "http-status=unknown exception=unknown duration-seconds=0" in rendered
    assert "served-model=unknown" in rendered
    assert secret not in rendered


def test_format_failure_metadata_rejects_credential_shaped_tokens(
    tmp_path: Path,
) -> None:
    """Structured identifiers cannot smuggle credential-shaped values into logs."""
    secret = "github" + "_pat_" + "NEVERPRINTTHISVALUE123456"
    json_path = tmp_path / "event.jsonl"
    stderr_path = tmp_path / "stderr"
    json_path.write_text(
        json.dumps(
            {
                "type": "error",
                "error": {
                    "name": secret,
                    "data": {
                        "detail": {
                            "phase": secret,
                            "terminal_reason": secret,
                            "model": secret,
                            "attempts": [{"provider_name": secret}],
                        }
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    stderr_path.write_text("", encoding="utf-8")

    rendered = envelope.format_failure_metadata(json_path, stderr_path, 1)

    assert secret not in rendered
    assert "phase=unknown" in rendered
    assert "reason=provider_error" in rendered
    assert "provider=unknown" in rendered
    assert "exception=unknown" in rendered
    assert "served-model=unknown" in rendered


def test_format_failure_metadata_rejects_unproven_identifier_provenance(
    tmp_path: Path,
) -> None:
    """Lexically safe unknown identifiers cannot become public diagnostics."""
    secret = "BYTEZ" + "_TEST_SECRET_1234567890"
    json_path = tmp_path / "event.jsonl"
    stderr_path = tmp_path / "stderr"
    json_path.write_text(
        json.dumps(
            {
                "type": "error",
                "error": {
                    "name": secret,
                    "data": {
                        "detail": {
                            "phase": secret,
                            "terminal_reason": secret,
                            "model": secret,
                            "attempts": [{"provider_name": secret}],
                        }
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    stderr_path.write_text("", encoding="utf-8")

    rendered = envelope.format_failure_metadata(json_path, stderr_path, 1)

    assert secret not in rendered
    assert "phase=unknown reason=provider_error provider=unknown" in rendered
    assert "exception=unknown" in rendered
    assert "served-model=unknown" in rendered


def test_format_failure_metadata_ignores_provider_prose_for_causal_class(
    tmp_path: Path,
) -> None:
    """Untrusted event prose cannot override the structured gateway cause."""
    json_path = tmp_path / "event.jsonl"
    stderr_path = tmp_path / "stderr"
    json_path.write_text(
        json.dumps({"type": "text", "text": "payment required; rate limit; timeout"})
        + "\n"
        + json.dumps(
            {
                "type": "error",
                "error": {
                    "name": "HTTPError",
                    "data": {
                        "statusCode": 502,
                        "detail": {"terminal_reason": "provider_unavailable"},
                        "message": "payment required",
                    },
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    stderr_path.write_text("authentication failed", encoding="utf-8")

    rendered = envelope.format_failure_metadata(json_path, stderr_path, 1)

    assert "class=provider-5xx" in rendered
    assert "reason=provider_unavailable" in rendered
    assert "class=credit-exhausted" not in rendered
    assert "class=authentication-or-permission" not in rendered


def test_main_prints_metadata_and_rejects_invalid_arguments(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The CLI has one strict invocation shape and delegates to the formatter."""
    json_path = tmp_path / "event.jsonl"
    stderr_path = tmp_path / "stderr"
    json_path.write_text("", encoding="utf-8")
    stderr_path.write_text("", encoding="utf-8")
    assert envelope.main([str(json_path), str(stderr_path), "0"]) == 0
    assert "class=no-provider-detail" in capsys.readouterr().out

    assert envelope.main([str(json_path), str(stderr_path), "-1"]) == 2
    assert "usage:" in capsys.readouterr().err
    monkeypatch.setattr(
        envelope.sys,
        "argv",
        ["opencode_failure_envelope.py", str(json_path), str(stderr_path), "1"],
    )
    assert envelope.main() == 0

def test_format_failure_metadata_rejects_conflicting_status_authorities(
    tmp_path: Path,
) -> None:
    """Conflicting validated HTTP statuses cannot select a public cause."""
    json_path = tmp_path / "event.jsonl"
    stderr_path = tmp_path / "stderr"
    json_path.write_text(
        json.dumps(
            {
                "type": "error",
                "error": {
                    "data": {
                        "statusCode": 429,
                        "detail": {
                            "attempts": [{"provider_status": 502}],
                        },
                    }
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    stderr_path.write_text("", encoding="utf-8")

    rendered = envelope.format_failure_metadata(json_path, stderr_path, 1)

    assert "class=provider-error" in rendered
    assert "reason=unknown" in rendered
    assert "http-status=unknown" in rendered
    assert "class=rate-limit" not in rendered
    assert "class=provider-5xx" not in rendered


def test_format_failure_metadata_rejects_conflicting_reason_authorities(
    tmp_path: Path,
) -> None:
    """Conflicting validated reason fields cannot select a public cause."""
    json_path = tmp_path / "event.jsonl"
    stderr_path = tmp_path / "stderr"
    json_path.write_text(
        json.dumps(
            {
                "type": "error",
                "error": {
                    "data": {
                        "detail": {
                            "terminal_reason": "payment_required",
                            "error_code": "provider_unavailable",
                        }
                    }
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    stderr_path.write_text("", encoding="utf-8")

    rendered = envelope.format_failure_metadata(json_path, stderr_path, 1)

    assert "class=provider-error" in rendered
    assert "reason=unknown" in rendered
    assert "http-status=unknown" in rendered
    assert "class=credit-exhausted" not in rendered
    assert "class=provider-5xx" not in rendered


def test_format_failure_metadata_rejects_cross_family_authority_conflict(
    tmp_path: Path,
) -> None:
    """A validated status and reason must resolve to the same causal class."""
    json_path = tmp_path / "event.jsonl"
    stderr_path = tmp_path / "stderr"
    json_path.write_text(
        json.dumps(
            {
                "type": "error",
                "error": {
                    "data": {
                        "statusCode": 502,
                        "detail": {"terminal_reason": "payment_required"},
                    }
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    stderr_path.write_text("", encoding="utf-8")

    rendered = envelope.format_failure_metadata(json_path, stderr_path, 1)

    assert "class=provider-error" in rendered
    assert "reason=unknown" in rendered
    assert "http-status=unknown" in rendered
