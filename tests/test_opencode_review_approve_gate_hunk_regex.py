"""Regression tests for the approval gate's precompiled diff-hunk parser."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest


GATE_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "ci"
    / "opencode_review_approve_gate.sh"
)
ASSIGNMENT_RE = re.compile(
    r'^HUNK_HEADER_RE = re\.compile\((r"[^"\n]+")\)$',
    re.MULTILINE,
)


def approval_gate_hunk_regex() -> re.Pattern[str]:
    """Load the exact module-level hunk regex embedded in the shell gate."""
    source = GATE_PATH.read_text(encoding="utf-8")
    matches = ASSIGNMENT_RE.findall(source)
    assert len(matches) == 1
    assert source.count("match = HUNK_HEADER_RE.match(raw_line)") == 1
    return re.compile(ast.literal_eval(matches[0]))


@pytest.mark.parametrize(
    ("header", "groups"),
    [
        ("@@ -7 +11 @@", ("11", None)),
        ("@@ -7,3 +11,4 @@", ("11", "4")),
        ("@@ -0,0 +1,0 @@", ("1", "0")),
    ],
)
def test_precompiled_hunk_regex_preserves_supported_git_headers(header, groups):
    """The optimization preserves optional old/new count parsing semantics."""
    match = approval_gate_hunk_regex().match(header)
    assert match is not None
    assert match.groups() == groups


@pytest.mark.parametrize("header", ["prefix @@ -7 +11 @@", "@@ -7 +x @@", "not a hunk"])
def test_precompiled_hunk_regex_rejects_non_headers(header):
    """Only anchored numeric Git hunk headers enter changed-line accounting."""
    assert approval_gate_hunk_regex().match(header) is None
