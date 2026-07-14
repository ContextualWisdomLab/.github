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
OBSERVED_RESULT_RE = re.compile(
    r"\b(?:blocked|confirm(?:ed|s)|contains?|disproved|exit code\s+[0-9]+|failed|matched|"
    r"observed|pass(?:ed)?|raised|rejected|rejects|reported|returned|showed)\b",
    re.IGNORECASE,
)
NEGATED_EVIDENCE_RE = re.compile(
    r"\b(?:no|without)\s+(?:command|test|assertion|check|probe)\s+"
    r"(?:was\s+|were\s+)?(?:run|ran|executed|performed|invoked|passed|failed)\b|"
    r"\b(?:not|never)\s+(?:run|executed|performed|invoked|observed|tested|checked)\b|"
    r"\bno\s+(?:observed\s+)?(?:result|output|outcome|receipt)\s+"
    r"(?:was\s+|were\s+)?(?:reported|observed|produced|recorded|available)\b",
    re.IGNORECASE,
)


def adversarial_evidence_rejection_reason(evidence: str, path: str) -> str | None:
    """Return why probe evidence is circular or lacks a concrete proof anchor."""
    cleaned = evidence.strip()
    lowered = cleaned.casefold()
    if NEGATED_EVIDENCE_RE.search(cleaned):
        return "explicitly denies execution or an observed result"
    if any(phrase in lowered for phrase in CIRCULAR_EVIDENCE_PHRASES):
        return "repeats the implementation claim instead of citing independent proof"
    if path and path.casefold() in lowered:
        has_proof_anchor = True
    else:
        has_proof_anchor = INDEPENDENT_PROOF_RE.search(cleaned) is not None
    if not has_proof_anchor:
        return (
            "must cite an executed command, test/assertion, log/check/SARIF receipt, "
            "source trace, diff, CodeGraph path, or exact changed file"
        )
    if not OBSERVED_RESULT_RE.search(cleaned):
        return (
            "must state the observed proof result, such as an exit code, passed or failed "
            "test/assertion, rejected input, log value, or source-trace outcome"
        )
    return None
