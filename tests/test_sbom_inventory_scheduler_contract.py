"""Executable contract for the central SBOM inventory scheduler."""

import subprocess
from pathlib import Path


WORKFLOW = Path(".github/workflows/sbom-inventory-scheduler.yml")
LINEAGE_RECONCILER = Path("scripts/ci/reconcile_sbom_publication_lineage.sh")


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


def _git(
    repository_path: Path,
    *arguments: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run one isolated Git command and return its captured result."""
    return subprocess.run(
        ["git", *arguments],
        cwd=repository_path,
        check=check,
        text=True,
        capture_output=True,
    )


def _commit_file(repository_path: Path, relative_path: str, content: str, message: str) -> str:
    """Write and commit one fixture file, then return the resulting commit SHA."""
    target_path = repository_path / relative_path
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(content, encoding="utf-8")
    _git(repository_path, "add", relative_path)
    _git(repository_path, "commit", "-m", message)
    return _git(repository_path, "rev-parse", "HEAD").stdout.strip()


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
    assert "--strategy=ours" not in publication_step
    assert "reconcile_sbom_publication_lineage.sh" in publication_step


def test_sbom_inventory_publication_fails_closed_before_overwriting_prior_repairs(
    tmp_path: Path,
) -> None:
    """A refresh must stop before treating prior owner repairs as generated data."""
    repository_path = tmp_path / "publication-repository"
    repository_path.mkdir()
    _git(repository_path, "init", "-b", "main")
    _git(repository_path, "config", "user.name", "SBOM Fixture")
    _git(repository_path, "config", "user.email", "sbom-fixture@example.invalid")
    _commit_file(repository_path, "dependency.lock", "vulnerable\n", "base")
    _commit_file(repository_path, "docs/sbom/inventory.md", "base inventory\n", "base inventory")
    _commit_file(repository_path, "docs/sbom/inventory.json", "{}\n", "base inventory json")

    _git(repository_path, "switch", "-c", "publication")
    _commit_file(repository_path, "dependency.lock", "repaired\n", "repair dependency")
    previous_head = _commit_file(
        repository_path,
        "tests/security-regression.txt",
        "repair stays covered\n",
        "cover repair",
    )

    _git(repository_path, "switch", "main")
    _commit_file(repository_path, "application.txt", "protected main update\n", "advance main")
    generated_head = _commit_file(
        repository_path,
        "docs/sbom/inventory.md",
        "fresh inventory\n",
        "generate inventory",
    )

    result = subprocess.run(
        [str(LINEAGE_RECONCILER.resolve()), previous_head, generated_head],
        cwd=repository_path,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode != 0
    assert "prior publication head contains non-inventory change" in result.stderr
    assert _git(repository_path, "rev-parse", "HEAD").stdout.strip() == generated_head
    assert (repository_path / "application.txt").read_text(encoding="utf-8") == "protected main update\n"
    assert (repository_path / "docs/sbom/inventory.md").read_text(encoding="utf-8") == "fresh inventory\n"
    assert not (repository_path / ".git" / "MERGE_HEAD").exists()


def test_sbom_inventory_publication_merges_generated_only_lineage(tmp_path: Path) -> None:
    """A generated-only predecessor may merge while the fresh inventory remains authoritative."""
    repository_path = tmp_path / "generated-only-repository"
    repository_path.mkdir()
    _git(repository_path, "init", "-b", "main")
    _git(repository_path, "config", "user.name", "SBOM Fixture")
    _git(repository_path, "config", "user.email", "sbom-fixture@example.invalid")
    _commit_file(repository_path, "application.txt", "base\n", "base")
    _commit_file(repository_path, "docs/sbom/inventory.md", "base inventory\n", "base inventory")
    _commit_file(repository_path, "docs/sbom/inventory.json", "{}\n", "base inventory json")

    _git(repository_path, "switch", "-c", "publication")
    previous_head = _commit_file(
        repository_path,
        "docs/sbom/inventory.md",
        "previous inventory\n",
        "previous inventory",
    )

    _git(repository_path, "switch", "main")
    _commit_file(repository_path, "application.txt", "protected main update\n", "advance main")
    generated_head = _commit_file(
        repository_path,
        "docs/sbom/inventory.md",
        "fresh inventory\n",
        "generate inventory",
    )

    subprocess.run(
        [str(LINEAGE_RECONCILER.resolve()), previous_head, generated_head],
        cwd=repository_path,
        check=True,
        text=True,
        capture_output=True,
    )

    assert (repository_path / "application.txt").read_text(encoding="utf-8") == "protected main update\n"
    assert (repository_path / "docs/sbom/inventory.md").read_text(encoding="utf-8") == "fresh inventory\n"
    assert _git(repository_path, "merge-base", "--is-ancestor", previous_head, "HEAD").returncode == 0
    assert len(_git(repository_path, "show", "-s", "--format=%P", "HEAD").stdout.split()) == 2


def test_sbom_inventory_publication_rejects_generated_non_inventory_paths(
    tmp_path: Path,
) -> None:
    """A generated commit must not acquire authority over neighboring owner files."""
    repository_path = tmp_path / "generated-owner-path-repository"
    repository_path.mkdir()
    _git(repository_path, "init", "-b", "main")
    _git(repository_path, "config", "user.name", "SBOM Fixture")
    _git(repository_path, "config", "user.email", "sbom-fixture@example.invalid")
    _commit_file(repository_path, "application.txt", "base\n", "base")
    _commit_file(repository_path, "docs/sbom/inventory.md", "base inventory\n", "base inventory")
    _commit_file(repository_path, "docs/sbom/inventory.json", "{}\n", "base inventory json")

    _git(repository_path, "switch", "-c", "publication")
    previous_head = _commit_file(
        repository_path,
        "docs/sbom/inventory.md",
        "previous inventory\n",
        "previous inventory",
    )

    _git(repository_path, "switch", "main")
    _commit_file(repository_path, "application.txt", "protected main update\n", "advance main")
    (repository_path / "docs/sbom/inventory.md").write_text(
        "fresh inventory\n",
        encoding="utf-8",
    )
    (repository_path / "docs/sbom/reviewer-notes.md").write_text(
        "must remain product-owned\n",
        encoding="utf-8",
    )
    _git(
        repository_path,
        "add",
        "docs/sbom/inventory.md",
        "docs/sbom/reviewer-notes.md",
    )
    _git(repository_path, "commit", "-m", "generate inventory with owner path")
    generated_head = _git(repository_path, "rev-parse", "HEAD").stdout.strip()

    result = subprocess.run(
        [str(LINEAGE_RECONCILER.resolve()), previous_head, generated_head],
        cwd=repository_path,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode != 0
    assert "generated inventory head contains non-inventory change" in result.stderr
    assert _git(repository_path, "rev-parse", "HEAD").stdout.strip() == generated_head
    assert not (repository_path / ".git" / "MERGE_HEAD").exists()


def test_sbom_inventory_publication_rejects_non_inventory_workspace_side_effects(
    tmp_path: Path,
) -> None:
    """An uncommitted generator side effect outside the inventory fails closed."""
    repository_path = tmp_path / "generated-workspace-side-effect-repository"
    repository_path.mkdir()
    _git(repository_path, "init", "-b", "main")
    _git(repository_path, "config", "user.name", "SBOM Fixture")
    _git(repository_path, "config", "user.email", "sbom-fixture@example.invalid")
    _commit_file(repository_path, "owner.txt", "protected\n", "base owner")
    _commit_file(repository_path, "docs/sbom/inventory.md", "base inventory\n", "base inventory")
    _commit_file(repository_path, "docs/sbom/inventory.json", "{}\n", "base inventory json")
    generated_head = _commit_file(
        repository_path,
        "docs/sbom/inventory.md",
        "fresh inventory\n",
        "generate inventory",
    )
    (repository_path / "owner.txt").write_text("generator side effect\n", encoding="utf-8")

    result = subprocess.run(
        [str(LINEAGE_RECONCILER.resolve()), generated_head, generated_head],
        cwd=repository_path,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode != 0
    assert "working tree contains non-inventory change" in result.stderr
    assert _git(repository_path, "rev-parse", "HEAD").stdout.strip() == generated_head
    assert not (repository_path / ".git" / "MERGE_HEAD").exists()


def test_sbom_inventory_publication_fails_closed_on_non_inventory_conflict(
    tmp_path: Path,
) -> None:
    """A non-inventory conflict must abort instead of choosing either writer silently."""
    repository_path = tmp_path / "conflict-repository"
    repository_path.mkdir()
    _git(repository_path, "init", "-b", "main")
    _git(repository_path, "config", "user.name", "SBOM Fixture")
    _git(repository_path, "config", "user.email", "sbom-fixture@example.invalid")
    _commit_file(repository_path, "dependency.lock", "base\n", "base")
    _commit_file(repository_path, "docs/sbom/inventory.md", "base inventory\n", "base inventory")
    _commit_file(repository_path, "docs/sbom/inventory.json", "{}\n", "base inventory json")

    _git(repository_path, "switch", "-c", "publication")
    previous_head = _commit_file(repository_path, "dependency.lock", "publication repair\n", "repair")

    _git(repository_path, "switch", "main")
    _commit_file(repository_path, "dependency.lock", "protected main repair\n", "advance main")
    generated_head = _commit_file(
        repository_path,
        "docs/sbom/inventory.md",
        "fresh inventory\n",
        "generate inventory",
    )

    result = subprocess.run(
        [str(LINEAGE_RECONCILER.resolve()), previous_head, generated_head],
        cwd=repository_path,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode != 0
    assert "prior publication head contains non-inventory change" in result.stderr
    assert _git(repository_path, "rev-parse", "HEAD").stdout.strip() == generated_head
    assert not (repository_path / ".git" / "MERGE_HEAD").exists()
