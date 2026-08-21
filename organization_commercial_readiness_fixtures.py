"""Test fixtures for the organization commercial-readiness coordinator."""

from __future__ import annotations

from typing import Any

from scripts.ci.organization_commercial_readiness_loop import (
    GitHubError,
    PullRequestRecord,
    RepositorySnapshot,
    RunRecord,
    WorkflowRecord,
)


def workflow(
    *,
    workflow_id: int = 1,
    name: str = "Hourly Product Development",
    path: str = ".github/workflows/hourly-product-development.yml",
    state: str = "active",
    content: str | None = None,
) -> WorkflowRecord:
    """Build one workflow record."""
    return WorkflowRecord(workflow_id, name, path, state, f"sha-{workflow_id}", content)


def pull(
    number: int,
    *,
    draft: bool = False,
    base_ref: str = "main",
    head_sha: str | None = None,
    updated_at: str = "2026-08-08T00:00:00Z",
) -> PullRequestRecord:
    """Build one pull-request record."""
    return PullRequestRecord(
        number, draft, base_ref, head_sha or f"{number:040x}", updated_at
    )


def snapshot(
    repository: str,
    *,
    default_branch: str = "main",
    default_sha: str = "a" * 40,
    workflows: tuple[WorkflowRecord, ...] = (),
    runs: tuple[RunRecord, ...] = (),
    pulls: tuple[PullRequestRecord, ...] = (),
) -> RepositorySnapshot:
    """Build one repository snapshot."""
    return RepositorySnapshot(
        repository, default_branch, default_sha, workflows, runs, pulls
    )


def repository_payload(name: str) -> dict[str, Any]:
    """Return one eligible repository response."""
    return {
        "full_name": f"ContextualWisdomLab/{name}",
        "default_branch": "main",
        "archived": False,
        "disabled": False,
        "fork": False,
        "permissions": {"maintain": True},
    }


def manual_workflow(*, workflow_id: int = 9) -> WorkflowRecord:
    """Return one safe organization-dispatch product entrypoint."""
    return workflow(
        workflow_id=workflow_id,
        name="Commercial Product Development",
        path=".github/workflows/commercial-product-development.yml",
        content=(
            "# cwl-org-commercial-entrypoint: v1\n"
            "on:\n  workflow_dispatch:\n"
            "concurrency:\n  group: product-development\n"
            "permissions:\n  contents: write\n"
            "NVIDIA_API_KEY: ${{ secrets.NVIDIA_NIM_API_KEY }}\n"
        ),
    )


class FakeClient:
    """Deterministic GitHub boundary."""

    def __init__(
        self,
        repositories: list[dict[str, Any]],
        snapshots: dict[str, list[RepositorySnapshot | Exception]],
    ) -> None:
        """Initialize deterministic repository and snapshot responses."""
        self.repositories = repositories
        self.snapshots = snapshots
        self.dispatched_repairs: list[tuple[str, str]] = []
        self.dispatched_products: list[tuple[str, int, str]] = []

    def list_repositories(self, organization: str) -> list[dict[str, Any]]:
        """Return configured repositories."""
        assert organization == "ContextualWisdomLab"
        return self.repositories

    def snapshot(self, repository: str, default_branch: str) -> RepositorySnapshot:
        """Return or raise the next configured snapshot value."""
        value = self.snapshots[repository].pop(0)
        if isinstance(value, Exception):
            raise value
        assert value.default_branch == default_branch
        return value

    def dispatch_review_repair(self, repository: str, base_branch: str) -> None:
        """Record one repair dispatch."""
        self.dispatched_repairs.append((repository, base_branch))

    def dispatch_product_workflow(
        self, repository: str, workflow_id: int, default_branch: str
    ) -> None:
        """Record one product dispatch."""
        self.dispatched_products.append((repository, workflow_id, default_branch))


class FailingDispatchClient(FakeClient):
    """Reject review dispatches for failure-path tests."""

    def dispatch_review_repair(self, repository: str, base_branch: str) -> None:
        """Raise a bounded API failure."""
        del repository, base_branch
        raise GitHubError("dispatch rejected")
