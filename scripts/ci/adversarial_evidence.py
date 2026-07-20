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
SOURCE_LINE_RECEIPT_RE = re.compile(
    r"(?<![A-Za-z0-9_-])source-line-sha256=([0-9a-fA-F]{64})(?![A-Za-z0-9_-])"
)


def adversarial_evidence_rejection_reason(
    evidence: str,
    path: str,
    line: int | None = None,
    *,
    require_location_citation: bool = True,
) -> str | None:
    """Return why probe evidence is circular, unbound, or lacks proof."""
    cleaned = evidence.strip()
    lowered = cleaned.casefold()
    if NEGATED_EVIDENCE_RE.search(cleaned):
        return "explicitly denies execution or an observed result"
    if any(phrase in lowered for phrase in CIRCULAR_EVIDENCE_PHRASES):
        return "repeats the implementation claim instead of citing independent proof"
    if require_location_citation:
        escaped_path = rf"(?<![A-Za-z0-9_./-]){re.escape(path)}"
        if line is None:
            path_citation = re.search(
                rf"{escaped_path}(?![A-Za-z0-9_./-])",
                cleaned,
                re.IGNORECASE,
            )
        else:
            escaped_line = re.escape(str(line))
            path_citation = re.search(
                rf"{escaped_path}(?::|#L|\s+line\s+){escaped_line}\b",
                cleaned,
                re.IGNORECASE,
            )
        if path and path_citation is None:
            suffix = " and positive line" if line is not None else ""
            return f"must cite the exact probe path{suffix}"
    source_receipts = SOURCE_LINE_RECEIPT_RE.findall(cleaned)
    lexical_evidence = SOURCE_LINE_RECEIPT_RE.sub("", cleaned)
    has_proof_anchor = INDEPENDENT_PROOF_RE.search(lexical_evidence) is not None
    if not has_proof_anchor:
        return (
            "must cite an executed command, test/assertion, log/check/SARIF receipt, "
            "source trace, diff, or CodeGraph path"
        )
    if not OBSERVED_RESULT_RE.search(lexical_evidence):
        return (
            "must state the observed proof result, such as an exit code, passed or failed "
            "test/assertion, rejected input, log value, or source-trace outcome"
        )
    if len(source_receipts) != 1:
        return (
            "must include exactly one source-line-sha256 receipt bound to the "
            "cited current-head line"
        )
    return None
