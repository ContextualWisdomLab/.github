"""Tests for pr_review_autofix_context.py."""

import pytest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts", "ci")))
import pr_review_autofix_context
from pr_review_autofix_context import repo_parts

def test_repo_parts_valid():
    """Test repo_parts with valid OWNER/NAME formats."""
    assert repo_parts("owner/name") == ("owner", "name")
    assert repo_parts("octocat/Hello-World") == ("octocat", "Hello-World")

def test_repo_parts_invalid():
    """Test repo_parts with invalid formats that should raise ValueError."""
    invalid_cases = [
        "ownername",  # missing slash
        "/name",      # missing owner
        "owner/",     # missing name
        "",           # empty string
        "/",          # just slash
    ]
    for case in invalid_cases:
        with pytest.raises(ValueError, match="repo must be OWNER/NAME, got"):
            repo_parts(case)
