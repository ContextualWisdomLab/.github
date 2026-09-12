"""Regression coverage for present malformed OpenCode gateway body aliases."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.ci import opencode_failure_envelope as envelope


@pytest.mark.parametrize(
    "body_value",
    [None, True, 503, []],
    ids=["null", "boolean", "integer", "array"],
)
@pytest.mark.parametrize(
    "outer_authority",
    [
        {"code": "provider_unavailable"},
        {"statusCode": 503},
    ],
    ids=["reason", "status"],
)
def test_present_unsupported_gateway_body_suppresses_outer_causal_authority(
    tmp_path: Path,
    body_value: object,
    outer_authority: dict[str, object],
) -> None:
    """A present unsupported body alias cannot preserve outer causal authority."""
    json_path = tmp_path / "event.jsonl"
    stderr_path = tmp_path / "stderr"
    json_path.write_text(
        json.dumps(
            {
                "type": "error",
                "error": {
                    "data": {
                        "responseBody": body_value,
                        **outer_authority,
                    }
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    stderr_path.write_text("", encoding="utf-8")

    rendered = envelope.format_failure_metadata(json_path, stderr_path, 1)

    assert "class=malformed-response" in rendered
    assert "reason=malformed_response" in rendered
    assert "http-status=unknown" in rendered
    assert "class=provider-5xx" not in rendered
