#!/usr/bin/env python3
"""Validate that an adversarial probe cites independent proof."""

from __future__ import annotations

import re


CIRCULAR_EVIDENCE_PHRASES = (
    "handles this case",
    "properly handles all cases",
    "works as expected",
    "is correct",
    "is safe",
    "no issues found",
)
INDEPENDENT_PROOF_RE = re.compile(
    r"\b(?:assert(?:ion|ed|s)?|check|codegraph|command|coverage|diff|exit code|"
    r"gate|log|run|sarif|source|test(?:ed|ing|s)?|trace)\b|\bline\s+[1-9][0-9]*\b",
    re.IGNORECASE,
)


def adversarial_evidence_rejection_reason(evidence: str, path: str) -> str | None:
    """Return why probe evidence is circular or lacks a concrete proof anchor."""
    cleaned = evidence.strip()
    lowered = cleaned.casefold()
    if any(phrase in lowered for phrase in CIRCULAR_EVIDENCE_PHRASES):
        return "repeats the implementation claim instead of citing independent proof"
    if path and path.casefold() in lowered:
        return None
    if INDEPENDENT_PROOF_RE.search(cleaned):
        return None
    return (
        "must cite an executed command, test/assertion, log/check/SARIF receipt, "
        "source trace, diff, CodeGraph path, or exact changed file"
    )
