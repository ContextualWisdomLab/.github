# SPDX-License-Identifier: Apache-2.0
"""Tests for fail-closed Strix semantic non-finding classification."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.ci.strix_report_classifier import (
    is_semantic_nonfinding_report,
    main,
)


SEMANTIC_NONFINDING = """\
# No Vulnerabilities Found in Initial Scan

**ID:** vuln-0001
**Severity:** HIGH
**CVSS:** 7.3

## Description

Initial automated security scans found no vulnerabilities in the codebase. No
further vulnerabilities identified during initial scanning phase.

## Impact

No security issues detected during automated scanning of the provided codebase.
No exposed secrets, insecure configurations, or vulnerable patterns were found.

## Technical Analysis

Semgrep static analysis found 0 findings. Gitleaks detected no secrets. No code
files with insecure patterns were identified.

## Proof of Concept

N/A - No vulnerabilities found to demonstrate exploitation.

```text
N/A
```

## Remediation

Continue manual review and routine defense-in-depth scanning.
"""


@pytest.mark.parametrize(
    "title",
    [
        "# No Vulnerabilities Found in Initial Scan",
        "# No Security Vulnerability Found",
    ],
)
def test_semantic_nonfinding_requires_consistent_no_finding_sections(title: str):
    """A contradictory severity label cannot turn an explicit clean report into a finding."""
    report = SEMANTIC_NONFINDING.replace(
        "# No Vulnerabilities Found in Initial Scan",
        title,
        1,
    )

    assert is_semantic_nonfinding_report(report) is True


@pytest.mark.parametrize(
    "replacement",
    [
        "# Potential Vulnerability Found in Initial Scan",
        "## Description\n\nAn attacker can execute arbitrary commands.",
        "## Impact\n\nCredentials can be disclosed to an unauthenticated attacker.",
        "## Technical Analysis\n\nA command injection sink is reachable.",
        "## Proof of Concept\n\n`curl https://example.invalid/exploit`",
        "**Location 1:** `scripts/ci/runner.py:41`",
        "**Endpoint:** `/api/admin`",
        "CVE-2026-12345",
    ],
)
def test_semantic_nonfinding_rejects_real_or_internally_inconsistent_reports(
    replacement: str,
):
    """Any concrete security claim or missing clean section keeps the gate fail closed."""
    if replacement.startswith("# Potential"):
        report = SEMANTIC_NONFINDING.replace(
            "# No Vulnerabilities Found in Initial Scan",
            replacement,
            1,
        )
    elif replacement.startswith("## Description"):
        report = SEMANTIC_NONFINDING.replace(
            "## Description\n\nInitial automated security scans found no vulnerabilities in the codebase. No\nfurther vulnerabilities identified during initial scanning phase.",
            replacement,
            1,
        )
    elif replacement.startswith("## Impact"):
        report = SEMANTIC_NONFINDING.replace(
            "## Impact\n\nNo security issues detected during automated scanning of the provided codebase.\nNo exposed secrets, insecure configurations, or vulnerable patterns were found.",
            replacement,
            1,
        )
    elif replacement.startswith("## Technical"):
        report = SEMANTIC_NONFINDING.replace(
            "## Technical Analysis\n\nSemgrep static analysis found 0 findings. Gitleaks detected no secrets. No code\nfiles with insecure patterns were identified.",
            replacement,
            1,
        )
    elif replacement.startswith("## Proof"):
        report = SEMANTIC_NONFINDING.replace(
            "## Proof of Concept\n\nN/A - No vulnerabilities found to demonstrate exploitation.\n\n```text\nN/A\n```",
            replacement,
            1,
        )
    else:
        report = f"{SEMANTIC_NONFINDING}\n{replacement}\n"

    assert is_semantic_nonfinding_report(report) is False


def test_semantic_nonfinding_rejects_missing_or_duplicate_required_sections():
    """Incomplete and ambiguous report structure is never neutralized."""
    missing = SEMANTIC_NONFINDING.replace("## Impact", "## Operational Notes", 1)
    duplicate = SEMANTIC_NONFINDING.replace(
        "## Impact",
        "## Impact\n\nNo security issues detected.\n\n## Impact",
        1,
    )

    assert is_semantic_nonfinding_report(missing) is False
    assert is_semantic_nonfinding_report(duplicate) is False


def test_classifier_cli_reports_semantic_result(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
):
    """The CLI uses stable exit codes without echoing provider-controlled report text."""
    report = tmp_path / "report.md"
    report.write_text(SEMANTIC_NONFINDING, encoding="utf-8")

    assert main([str(report)]) == 0
    assert capsys.readouterr().out == ""

    report.write_text("# Real vulnerability\n", encoding="utf-8")
    assert main([str(report)]) == 1
    assert capsys.readouterr().out == ""


def test_classifier_cli_rejects_unsafe_inputs(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
):
    """Missing arguments, missing files, symlinks, and invalid UTF-8 fail closed."""
    assert main([]) == 2
    assert "exactly one report path" in capsys.readouterr().err

    missing = tmp_path / "missing.md"
    assert main([str(missing)]) == 2
    assert "regular non-symlink file" in capsys.readouterr().err

    target = tmp_path / "target.md"
    target.write_text(SEMANTIC_NONFINDING, encoding="utf-8")
    link = tmp_path / "link.md"
    link.symlink_to(target)
    assert main([str(link)]) == 2
    assert "regular non-symlink file" in capsys.readouterr().err

    invalid = tmp_path / "invalid.md"
    invalid.write_bytes(b"\xff")
    assert main([str(invalid)]) == 2
    assert "valid UTF-8" in capsys.readouterr().err


def test_gate_classifies_semantic_nonfinding_before_severity_threshold():
    """A fake HIGH label is neutralized before ordinary threshold handling."""
    gate = Path("scripts/ci/strix_quick_gate.sh").read_text(encoding="utf-8")
    function_start = gate.index(
        "vulnerability_file_is_retryable_model_inconsistency() {"
    )
    function_end = gate.index("\n}\n", function_start)
    function_body = gate[function_start:function_end]

    classifier_position = function_body.index(
        'python3 "$SCRIPT_DIR/strix_report_classifier.py" "$vuln_file"'
    )
    threshold_position = function_body.index(
        'vulnerability_file_is_below_threshold "$vuln_file"'
    )
    assert classifier_position < threshold_position
    assert 'case "$semantic_nonfinding_rc" in' in function_body
    assert "Invalid semantic non-finding classifier input" in function_body
