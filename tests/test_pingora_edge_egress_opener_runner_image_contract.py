"""Workflow contracts for the Pingora Edge EgressWeave quality gate."""

from pathlib import Path


WORKFLOW = Path(".github/workflows/pingora-edge-egress-opener-quality-ci.yml")


def test_pingora_edge_egress_quality_uses_explicit_ubuntu_2404() -> None:
    """Keep this new queue-consuming gate off the starved floating runner alias."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "runs-on: ubuntu-latest" not in workflow
    assert "runs-on: ubuntu-24.04" in workflow


def test_pingora_edge_egress_quality_checks_out_the_pr_head_repository() -> None:
    """Fork PRs must fetch their exact head from the repository that owns it."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "repository: ${{ github.event.pull_request.head.repo.full_name || github.repository }}" in workflow
    assert "ref: ${{ github.event.pull_request.head.sha || github.sha }}" in workflow
