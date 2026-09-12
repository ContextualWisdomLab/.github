"""Unit coverage for bounded OpenCode provider-failure metadata."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.ci import opencode_failure_envelope as envelope


def test_read_bounded_handles_missing_and_oversized_files(tmp_path: Path) -> None:
    """Missing artifacts are empty and large artifacts retain their true size."""
    assert envelope._read_bounded(tmp_path / "missing") == (b"", 0)
    large = tmp_path / "large"
    large.write_bytes(b"x" * (envelope.MAX_FAILURE_FILE_BYTES + 2))
    raw, byte_count = envelope._read_bounded(large)
    assert len(raw) == envelope.MAX_FAILURE_FILE_BYTES + 1
    assert byte_count == envelope.MAX_FAILURE_FILE_BYTES + 2
    assert envelope._last_error_event(raw) is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("openrouter/model:free", "openrouter/model:free"),
        (" unsafe value ", None),
        (1, None),
    ],
)
def test_safe_value_accepts_only_bounded_log_tokens(value: object, expected: str | None) -> None:
    """Arbitrary provider text cannot become a public-log token."""
    assert envelope._safe_value(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("HTTPError", "HTTPError"),
        ("bad error", None),
        ("x" * 65, None),
        (7, None),
    ],
)
def test_safe_exception_accepts_only_short_identifiers(
    value: object, expected: str | None
) -> None:
    """Exception telemetry is a type identifier, never an exception message."""
    assert envelope._safe_exception(value) == expected


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


@pytest.mark.parametrize(
    ("raw_json", "raw_stderr", "status", "reason", "malformed", "event", "expected"),
    [
        (b"request_too_large", b"", None, None, False, True, "request-too-large"),
        (b"ContextOverflowError", b"", None, None, False, True, "context-window"),
        (b"", b"payment required", None, None, False, False, "credit-exhausted"),
        (b"insufficient_quota", b"", None, None, False, True, "quota-or-budget"),
        (b"", b"", None, "no_eligible_route", False, True, "model-pool-exhausted"),
        (b"model_not_found", b"", None, None, False, True, "model-unavailable"),
        (b"", b"", 429, None, False, True, "rate-limit"),
        (b"", b"permission denied", None, None, False, False, "authentication-or-permission"),
        (b"", b"timed out", None, None, False, False, "timeout"),
        (b"", b"", 502, None, False, True, "provider-5xx"),
        (b"{}", b"", None, None, True, True, "malformed-response"),
        (b"{}", b"", None, None, False, False, "malformed-response"),
        (b"{}", b"", None, None, False, True, "provider-error"),
        (b"", b"", None, None, False, False, "no-provider-detail"),
    ],
)
def test_failure_class_preserves_distinct_safe_causes(
    raw_json: bytes,
    raw_stderr: bytes,
    status: int | None,
    reason: str | None,
    malformed: bool,
    event: bool,
    expected: str,
) -> None:
    """Each accepted causal category remains distinguishable."""
    assert (
        envelope._failure_class(
            raw_json,
            raw_stderr,
            status=status,
            reason=reason,
            malformed_body=malformed,
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
    assert "provider=nvidia_nim" in rendered
    assert "http-status=503" in rendered
    assert "exception=HTTPError" in rendered
    assert "duration-seconds=5" in rendered
    assert "served-model=nvidia/model:free" in rendered


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
