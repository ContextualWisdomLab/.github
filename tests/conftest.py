"""Shared pytest collection safeguards for host-tool-dependent tests."""

from __future__ import annotations

import shutil

import pytest


_BASH_REQUIRED_TESTS = {
    "test_strix_provider_outage_without_findings_fails_closed",
}


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Skip bash-backed contract tests when the host has no bash executable."""
    if shutil.which("bash") is not None:
        return

    bash_unavailable = pytest.mark.skip(
        reason="bash is required to execute the extracted GitHub Actions run block"
    )
    for item in items:
        if item.name in _BASH_REQUIRED_TESTS:
            item.add_marker(bash_unavailable)
