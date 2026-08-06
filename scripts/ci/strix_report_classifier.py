#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Classify a narrowly defined Strix report that explicitly reports no finding.

The classifier is deliberately conservative. It neutralizes only a structurally
complete report whose title, description, impact, technical analysis, and proof
of concept all independently state that no vulnerability exists. Any concrete
location, endpoint, CVE identifier, missing section, duplicate section, or
internally inconsistent security claim remains a blocking report.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Sequence

_REQUIRED_SECTIONS = (
    "description",
    "impact",
    "technical analysis",
    "proof of concept",
)
_TITLE_PATTERN = re.compile(
    r"^#\s+No(?:\s+Security)?\s+Vulnerabilit(?:y|ies)\s+Found(?:\b|\s)",
    re.IGNORECASE | re.MULTILINE,
)
_SECTION_PATTERN = re.compile(r"^##\s+([^\r\n#]+?)\s*$", re.MULTILINE)
_CONCRETE_FINDING_PATTERNS = (
    re.compile(r"^##\s+Code Analysis\s*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"\*\*Location\s+\d+\s*:\*\*", re.IGNORECASE),
    re.compile(r"\*\*Endpoint\s*:\*\*", re.IGNORECASE),
    re.compile(r"\bCVE-\d{4}-\d{4,}\b", re.IGNORECASE),
)


def _normalized_sections(report_text: str) -> dict[str, str] | None:
    """Return unique normalized second-level Markdown sections or ``None``."""
    matches = list(_SECTION_PATTERN.finditer(report_text))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        name = " ".join(match.group(1).casefold().split())
        if name in sections:
            return None
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(report_text)
        sections[name] = report_text[start:end].strip()
    return sections


def is_semantic_nonfinding_report(report_text: str) -> bool:
    """Return whether ``report_text`` is a complete, explicit no-finding report."""
    if not _TITLE_PATTERN.search(report_text):
        return False
    if any(pattern.search(report_text) for pattern in _CONCRETE_FINDING_PATTERNS):
        return False

    sections = _normalized_sections(report_text)
    if sections is None or any(name not in sections for name in _REQUIRED_SECTIONS):
        return False

    description = sections["description"].casefold()
    impact = sections["impact"].casefold()
    technical = sections["technical analysis"].casefold()
    proof = sections["proof of concept"].casefold()

    description_is_clean = (
        "found no vulnerabilities" in description
        and "no further vulnerabilities identified" in description
    )
    impact_is_clean = (
        "no security issues detected" in impact
        and "no exposed secrets" in impact
        and "no" in impact
        and "vulnerable patterns" in impact
    )
    technical_is_clean = (
        "0 findings" in technical
        and "detected no secrets" in technical
        and "no code" in technical
        and "insecure patterns" in technical
    )
    proof_is_clean = (
        re.search(r"\bN/A\b", sections["proof of concept"], re.IGNORECASE)
        is not None
        and "no vulnerabilities found" in proof
    )
    return all(
        (
            description_is_clean,
            impact_is_clean,
            technical_is_clean,
            proof_is_clean,
        )
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Return 0 for a semantic non-finding, 1 for a finding, and 2 for bad input."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) != 1:
        print("exactly one report path is required", file=sys.stderr)
        return 2

    report_path = Path(arguments[0])
    try:
        metadata = report_path.lstat()
    except OSError:
        print("report path must be a regular non-symlink file", file=sys.stderr)
        return 2
    if report_path.is_symlink() or not report_path.is_file() or metadata.st_size < 1:
        print("report path must be a regular non-symlink file", file=sys.stderr)
        return 2

    try:
        report_text = report_path.read_text(encoding="utf-8", errors="strict")
    except (OSError, UnicodeDecodeError):
        print("report must contain valid UTF-8", file=sys.stderr)
        return 2
    return 0 if is_semantic_nonfinding_report(report_text) else 1


if __name__ == "__main__":
    raise SystemExit(main())
