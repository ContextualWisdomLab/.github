from __future__ import annotations

import pytest

from organization_commercial_readiness_fixtures import (
    FailingDispatchClient,
    FakeClient,
    pull,
    repository_payload,
    snapshot,
)
from scripts.ci.organization_commercial_readiness_loop import GitHubError, main


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
