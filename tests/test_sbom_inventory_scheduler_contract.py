"""Executable contract for the central SBOM inventory scheduler."""

from pathlib import Path


WORKFLOW = Path(".github/workflows/sbom-inventory-scheduler.yml")


def _workflow_text() -> str:
    """Return the scheduler source as text for dependency-free contract checks."""
    return WORKFLOW.read_text(encoding="utf-8")


def test_sbom_inventory_scheduler_runs_hourly() -> None:
    """Organization license evidence must refresh once each hour."""
    workflow = _workflow_text()
    assert 'cron: "0 * * * *"' in workflow
    assert 'cron: "0 6 * * 1"' not in workflow


def test_sbom_inventory_scheduler_excludes_forks_before_collection() -> None:
    """Only repositories proven non-forks may become owned inventory targets."""
    workflow = _workflow_text()
    assert '"nameWithOwner,isFork"' in workflow
    assert ".[] | select(.isFork == false) | .nameWithOwner" in workflow
    assert 'repo_args+=(--repo "$repo")' in workflow
    assert '"${repo_args[@]}"' in workflow
    assert '--org "$ORG_LOGIN"' not in workflow


def test_sbom_inventory_scheduler_does_not_force_push() -> None:
    """Recurring publication must preserve concurrent branch history."""
    workflow = _workflow_text()
    assert "--force" not in workflow
    assert "--force-with-lease" not in workflow
