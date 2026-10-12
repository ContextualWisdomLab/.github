"""Contracts for the repository-wide production coverage boundary."""

from __future__ import annotations

import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised by the Python 3.10 CI lane
    import tomli as tomllib


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ALLOWED_COVERAGE_OMISSIONS = {
    "tests/*",
    "scripts/ci/contextual_orchestrator_review_launcher.py",
}


def test_production_coverage_omissions_are_explicitly_allowlisted() -> None:
    """Reject production exclusions that manufacture a 100% coverage result."""

    with (REPOSITORY_ROOT / "pyproject.toml").open("rb") as config_file:
        project_configuration = tomllib.load(config_file)

    configured_omissions = set(
        project_configuration["tool"]["coverage"]["run"]["omit"]
    )

    assert configured_omissions == ALLOWED_COVERAGE_OMISSIONS
