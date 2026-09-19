"""Repository-identity admission contract for the CodeQL dispatch handler."""

from __future__ import annotations

import pytest

from tests.test_codeql_scan_dispatch_workflow_contract import (
    _matching_pull_request,
    _run_validate_step,
)


def _matching_pull_request_for(repository: str) -> dict:
    """Bind the shared live-PR fixture to one target repository identity."""
    pull_request = _matching_pull_request()
    pull_request["base"]["repo"]["full_name"] = repository
    pull_request["head"]["repo"]["full_name"] = repository
    return pull_request


@pytest.mark.parametrize(
    "repository",
    (
        "ContextualWisdomLab/repository.",
        "ContextualWisdomLab/repo..name",
        "ContextualWisdomLab/..",
        "ContextualWisdomLab/.",
    ),
)
def test_codeql_scan_dispatch_rejects_noncanonical_target_repository(
    tmp_path, repository: str
) -> None:
    """Reject non-canonical target slugs in the real validation shell block."""
    result = _run_validate_step(
        tmp_path,
        {"TARGET_REPOSITORY": repository},
        _matching_pull_request_for(repository),
    )
    assert result.returncode != 0
    assert "PR metadata validation rejected a target outside ContextualWisdomLab" in result.stderr


@pytest.mark.parametrize(
    "repository",
    (
        "ContextualWisdomLab/pg-llm-batch",
        "ContextualWisdomLab/repository.name-1",
    ),
)
def test_codeql_scan_dispatch_keeps_valid_target_repository(
    tmp_path, repository: str
) -> None:
    """Preserve valid punctuation-bearing organization-local repository slugs."""
    result = _run_validate_step(
        tmp_path,
        {"TARGET_REPOSITORY": repository},
        _matching_pull_request_for(repository),
    )
    assert result.returncode == 0, result.stderr
