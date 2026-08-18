"""Resource-bound regressions for the organization readiness coordinator."""

from __future__ import annotations

import base64
from typing import Any

import pytest

from scripts.ci.organization_commercial_readiness_loop import GitHubClient, GitHubError


def _workflow(index: int) -> dict[str, Any]:
    """Return one high-signal workflow metadata record."""

    return {
        "id": index + 1,
        "name": f"Hourly Product Development {index}",
        "path": f".github/workflows/product-development-{index}.yml",
        "state": "active",
    }


def test_workflow_source_count_is_bounded_per_repository(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """More than 100 candidate sources fail closed before unbounded retention."""

    client = GitHubClient("token")
    pages = [[_workflow(index) for index in range(100)], [_workflow(100)]]
    source = b"on:\n  workflow_dispatch:\n"

    def fake(path: str, *, method: str = "GET", payload: Any = None) -> Any:
        del method, payload
        if "actions/workflows" in path:
            return {"workflows": pages.pop(0) if pages else []}
        if "/contents/" in path:
            return {
                "type": "file",
                "size": len(source),
                "sha": "a" * 40,
                "encoding": "base64",
                "content": base64.b64encode(source).decode(),
            }
        raise AssertionError(path)

    monkeypatch.setattr(client, "request", fake)

    with pytest.raises(GitHubError, match="workflow source limit"):
        client.list_workflows("ContextualWisdomLab/example", "a" * 40)


def test_workflow_source_bytes_are_bounded_per_repository(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Candidate source bytes above 10 MiB fail closed instead of exhausting memory."""

    client = GitHubClient("token")
    workflows = [_workflow(index) for index in range(11)]
    source = b"x" * 1_000_000

    def fake(path: str, *, method: str = "GET", payload: Any = None) -> Any:
        del method, payload
        if "actions/workflows" in path:
            current, workflows[:] = list(workflows), []
            return {"workflows": current}
        if "/contents/" in path:
            return {
                "type": "file",
                "size": len(source),
                "sha": "b" * 40,
                "encoding": "base64",
                "content": base64.b64encode(source).decode(),
            }
        raise AssertionError(path)

    monkeypatch.setattr(client, "request", fake)

    with pytest.raises(GitHubError, match="workflow source byte limit"):
        client.list_workflows("ContextualWisdomLab/example", "a" * 40)
