"""Regression coverage for reviewed OpenCode failure-envelope authority boundaries."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.ci import opencode_failure_envelope as envelope


def _render(tmp_path: Path, error: object) -> str:
    """Render one structured error event through the public diagnostic seam."""
    json_path = tmp_path / "event.jsonl"
    stderr_path = tmp_path / "stderr"
    json_path.write_text(
        json.dumps({"type": "error", "error": error}) + "\n",
        encoding="utf-8",
    )
    stderr_path.write_text("", encoding="utf-8")
    return envelope.format_failure_metadata(json_path, stderr_path, 1)


@pytest.mark.parametrize(
    "error",
    [
        None,
        "not-an-object",
        [],
        {"data": None},
        {"data": "not-an-object"},
        {"data": []},
    ],
    ids=[
        "null-error",
        "string-error",
        "list-error",
        "null-data",
        "string-data",
        "list-data",
    ],
)
def test_present_malformed_error_containers_fail_closed(
    tmp_path: Path, error: object
) -> None:
    """Present non-object error containers remain malformed-response authority."""
    rendered = _render(tmp_path, error)

    assert "class=malformed-response" in rendered
    assert "reason=malformed_response" in rendered
    assert "http-status=unknown" in rendered


def test_gateway_status_and_provider_status_keep_separate_layers(tmp_path: Path) -> None:
    """A gateway 502 may wrap an upstream 503 without erasing the structured cause."""
    rendered = _render(
        tmp_path,
        {
            "data": {
                "statusCode": 502,
                "detail": {
                    "terminal_reason": "eligible_candidates_exhausted",
                    "attempts": [{"provider_status": 503}],
                },
            }
        },
    )

    assert "class=model-pool-exhausted" in rendered
    assert "reason=eligible_candidates_exhausted" in rendered
    assert "http-status=502" in rendered


@pytest.mark.parametrize(
    ("status", "reason", "expected_class"),
    [
        (503, "eligible_candidates_exhausted", "model-pool-exhausted"),
        (504, "provider_timeout", "timeout"),
        (503, "model_not_found", "model-unavailable"),
    ],
)
def test_specific_reason_refines_compatible_generic_5xx(
    tmp_path: Path,
    status: int,
    reason: str,
    expected_class: str,
) -> None:
    """Allowlisted terminal reasons refine only compatible generic 5xx statuses."""
    rendered = _render(
        tmp_path,
        {"data": {"statusCode": status, "detail": {"terminal_reason": reason}}},
    )

    assert f"class={expected_class}" in rendered
    assert f"reason={reason}" in rendered
    assert f"http-status={status}" in rendered


def test_specific_reason_does_not_refine_incompatible_generic_5xx(
    tmp_path: Path,
) -> None:
    """Credit/auth/rate-like contradictions remain fail-closed under generic 5xx."""
    rendered = _render(
        tmp_path,
        {
            "data": {
                "statusCode": 502,
                "detail": {"terminal_reason": "payment_required"},
            }
        },
    )

    assert "class=provider-error" in rendered
    assert "reason=unknown" in rendered
    assert "http-status=unknown" in rendered
