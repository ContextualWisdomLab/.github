"""Executable contract for the central SBOM inventory scheduler."""

from pathlib import Path


WORKFLOW = Path(".github/workflows/sbom-inventory-scheduler.yml")


def _workflow_text() -> str:
    """Return the scheduler source as text for dependency-free contract checks."""
    return WORKFLOW.read_text(encoding="utf-8")


def _step_body(name: str) -> str:
    """Return one named executable workflow step, excluding later steps."""
    workflow = _workflow_text()
    marker = f"      - name: {name}\n"
    start = workflow.index(marker)
    next_step = workflow.find("\n      - name: ", start + len(marker))
    return workflow[start : next_step if next_step != -1 else len(workflow)]


def test_sbom_inventory_scheduler_runs_hourly() -> None:
    """Organization license evidence must refresh once each hour."""
    workflow = _workflow_text()
    assert 'cron: "0 * * * *"' in workflow
    assert 'cron: "0 6 * * 1"' not in workflow


def test_sbom_inventory_scheduler_requires_cross_repo_credential() -> None:
    """Repository-scoped github.token must never publish a partial org inventory."""
    workflow = _workflow_text()
    credential_step = _step_body("Require organization-wide SBOM credential")
    assert "|| github.token" not in workflow
    assert (
        "GH_TOKEN: ${{ secrets.SBOM_INVENTORY_TOKEN || steps.aggregator_app_token.outputs.token }}"
        in credential_step
    )
    assert 'if [ -z "${GH_TOKEN:-}" ]; then' in credential_step
    assert "refusing partial inventory" in credential_step
    assert "exit 1" in credential_step


def test_sbom_inventory_scheduler_excludes_forks_before_collection() -> None:
    """Only repositories proven non-forks may become owned inventory targets."""
    discovery_step = _step_body("Discover live non-fork repositories")
    aggregation_step = _step_body("Aggregate org SBOM inventory")
    assert "gh repo list" in discovery_step
    assert '"nameWithOwner,isFork"' in discovery_step
    assert ".[] | select(.isFork == false) | .nameWithOwner" in discovery_step
    assert "cwl-nonfork-repositories.txt" in discovery_step
    assert 'repo_args+=(--repo "$repo")' in aggregation_step
    assert '"${repo_args[@]}"' in aggregation_step
    assert '--org "$ORG_LOGIN"' not in aggregation_step


def test_sbom_inventory_scheduler_authenticates_git_before_publication() -> None:
    """The non-persistent checkout must establish Git auth before remote mutation."""
    publication_step = _step_body("Open or update inventory PR")
    auth_index = publication_step.index("gh auth setup-git")
    first_remote_index = min(
        publication_step.index("git ls-remote"),
        publication_step.index("git push"),
    )
    assert auth_index < first_remote_index


def test_sbom_inventory_scheduler_does_not_force_push() -> None:
    """Recurring publication must preserve concurrent branch history."""
    publication_step = _step_body("Open or update inventory PR")
    assert "--force" not in publication_step
    assert "--force-with-lease" not in publication_step
