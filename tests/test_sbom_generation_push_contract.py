"""Contracts for default-branch dependency snapshot generation."""

from __future__ import annotations

from pathlib import Path


WORKFLOW = Path(".github/workflows/sbom-generation.yml")


def _workflow_text() -> str:
    """Return the centrally versioned SBOM workflow as UTF-8 text."""

    return WORKFLOW.read_text(encoding="utf-8")


def test_sbom_workflow_snapshots_supported_default_branch_pushes() -> None:
    """Default-branch commits must receive dependency graph snapshots."""

    workflow = _workflow_text()

    assert "on:\n  push:\n    branches: [main, master, develop]\n" in workflow
    assert "  pull_request:\n" in workflow
    assert "  release:\n" in workflow
    assert "dependency-snapshot: true" in workflow


def test_sbom_push_concurrency_is_bound_to_the_commit_sha() -> None:
    """A later default-branch push must not cancel another commit's snapshot."""

    workflow = _workflow_text()
    group_line = next(
        line.strip() for line in workflow.splitlines() if line.strip().startswith("group:")
    )

    assert "github.event.release.tag_name || github.sha" in group_line
    assert "github.event.release.tag_name || github.ref" not in group_line


def test_sbom_job_conditions_keep_push_runs_active_and_closed_prs_inert() -> None:
    """Pushes run the snapshot job while closed-PR events only cancel stale work."""

    workflow = _workflow_text()

    assert (
        "if: github.event_name == 'pull_request' && github.event.action == 'closed'"
        in workflow
    )
    assert (
        "if: github.event_name != 'pull_request' || github.event.action != 'closed'"
        in workflow
    )
    assert "generate-sbom:\n" in workflow
    assert "      contents: write\n" in workflow
