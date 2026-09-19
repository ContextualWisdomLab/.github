from __future__ import annotations

import threading

import pytest

from organization_commercial_readiness_fixtures import (
    FailingDispatchClient,
    FakeClient,
    pull,
    repository_payload,
    snapshot,
)
from scripts.ci.organization_commercial_readiness_loop import GitHubError, main, run_once


def test_cli_fails_when_every_selected_repository_inspection_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fleet-wide inspection outage must make the scheduled job non-green."""
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    client = FakeClient(
        [repository_payload("broken")],
        {"ContextualWisdomLab/broken": [GitHubError("forbidden")]},
    )

    assert main([], client_factory=lambda: client) == 1


def test_cli_fails_when_every_planned_dispatch_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A run that cannot start any selected work must make the job non-green."""
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    review = snapshot("ContextualWisdomLab/review", pulls=(pull(1),))
    client = FailingDispatchClient(
        [repository_payload("review")],
        {review.full_name: [review, review]},
    )

    assert main([], client_factory=lambda: client) == 1


class _SerialSnapshotProbe(FakeClient):
    """Record the execution thread for every external snapshot call."""

    def __init__(
        self,
        repositories: list[dict[str, object]],
        snapshots: dict[str, list[object]],
    ) -> None:
        """Initialize one deterministic serial-admission probe."""
        super().__init__(repositories, snapshots)  # type: ignore[arg-type]
        self.snapshot_thread_ids: list[int] = []

    def snapshot(self, repository: str, default_branch: str):  # type: ignore[no-untyped-def]
        """Record the calling thread without a timing threshold."""
        self.snapshot_thread_ids.append(threading.get_ident())
        return super().snapshot(repository, default_branch)


def test_snapshot_inspection_is_serial_without_admission_authority() -> None:
    """Do not invent concurrent GitHub request admission without measured authority."""
    names = ("alpha", "bravo", "charlie")
    repositories = [repository_payload(name) for name in names]
    snapshots = {
        f"ContextualWisdomLab/{name}": [snapshot(f"ContextualWisdomLab/{name}")]
        for name in names
    }
    invocation_thread_id = threading.get_ident()
    client = _SerialSnapshotProbe(repositories, snapshots)

    report = run_once(
        client,
        organization="ContextualWisdomLab",
        rotation_seed=0,
        max_repositories=len(names),
        dry_run=True,
    )

    assert report.inspected_repositories == len(names)
    assert report.inspection_errors == ()
    assert client.snapshot_thread_ids == [invocation_thread_id] * len(names)
