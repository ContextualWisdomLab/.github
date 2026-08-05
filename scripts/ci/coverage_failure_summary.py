#!/usr/bin/env python3
"""Publish bounded, credential-redacted coverage setup failure evidence."""

from __future__ import annotations

import html
import os
from pathlib import Path

from scripts.ci.sanitize_github_output_summary import sanitize_text

_COVERAGE_DELIMITER = "CWL_COVERAGE_SUMMARY_EOF"


def _safe_field(value: str, maximum_length: int) -> str:
    """Normalize, redact, bound, escape, and delimiter-proof one output field."""

    normalized = " ".join(value.split())
    redacted = sanitize_text(normalized)[:maximum_length]
    escaped = html.escape(redacted, quote=True)
    return escaped.replace(
        _COVERAGE_DELIMITER,
        "CWL_COVERAGE_SUMMARY_END",
    )


def publish_coverage_failure_summary(
    stage: str,
    error: BaseException,
    remediation: str,
) -> None:
    """Append one safe exact-stage failure envelope to ``GITHUB_OUTPUT``."""

    github_output = os.environ.get("GITHUB_OUTPUT")
    if not github_output:
        return

    safe_stage = _safe_field(stage, 256)
    safe_reason = _safe_field(
        f"{error.__class__.__name__}: {error}",
        4096,
    )
    safe_remediation = _safe_field(remediation, 1024)
    summary = (
        "## Coverage Decision\n"
        "- Result: FAIL\n"
        f"- Failed stage: {safe_stage}\n"
        "- Exact failure:\n"
        f"<pre>{safe_reason}</pre>\n"
        f"- Next action: {safe_remediation}\n"
    )
    with Path(github_output).open("a", encoding="utf-8") as output:
        output.write(
            f"coverage_summary<<{_COVERAGE_DELIMITER}\n"
            f"{summary}{_COVERAGE_DELIMITER}\n"
        )
