import pytest
import sys
import os

# Add the directory containing opencode_review_normalize_output to the path
sys.path.insert(0, os.path.dirname(__file__))

from opencode_review_normalize_output import (
    admits_missing_structural_review,
    mentions_changed_file_evidence,
)

def test_admits_missing_structural_review():
    # Empty cases
    assert not admits_missing_structural_review("", "")
    assert not admits_missing_structural_review("looks good", "approved")

    # Exact phrase matches from STRUCTURAL_FAILURE_PHRASES
    assert admits_missing_structural_review("structural exploration was not possible", "summary")
    assert admits_missing_structural_review("reason", "no changes detected")
    assert admits_missing_structural_review("evidence was truncated", "summary")

    # Pattern matches from STRUCTURAL_FAILURE_PATTERNS
    assert admits_missing_structural_review("could not inspect the changed files", "")
    assert admits_missing_structural_review("", "cannot access source files")
    assert admits_missing_structural_review("required files were not reviewed", "")
    assert admits_missing_structural_review("", "structural analysis was incomplete")
    assert admits_missing_structural_review("no changes to review", "")
    assert admits_missing_structural_review("", "zero changed files")

    # Case insensitivity
    assert admits_missing_structural_review("STRUCTURAL EXPLORATION WAS NOT POSSIBLE", "")
    assert admits_missing_structural_review("", "NO CHANGES DETECTED")

def test_mentions_changed_file_evidence():
    # Empty/Negative cases
    assert not mentions_changed_file_evidence("", "")
    assert not mentions_changed_file_evidence("looks good", "approved")
    assert not mentions_changed_file_evidence("changed some code", "no file listed here")
    assert not mentions_changed_file_evidence("invalid.ext", "not a valid extension")

    # Valid file patterns matching CHANGED_FILE_EVIDENCE_PATTERN
    assert mentions_changed_file_evidence("I reviewed path/to/file.py", "")
    assert mentions_changed_file_evidence("", "Checked some_script.sh")
    assert mentions_changed_file_evidence("Modified a.ts", "and b.tsx")
    assert mentions_changed_file_evidence("updated package.json", "")
    assert mentions_changed_file_evidence("", "read README")
    assert mentions_changed_file_evidence("checked Dockerfile", "")
    assert mentions_changed_file_evidence("reviewed AGENTS.md", "")

    # Embedded valid paths
    assert mentions_changed_file_evidence("The file dir/sub/app.js is good", "")
    assert mentions_changed_file_evidence("Fixed bug in module.rs", "")
