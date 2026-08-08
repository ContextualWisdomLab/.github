from __future__ import annotations

import base64
from typing import Any

import pytest

from scripts.ci.organization_commercial_readiness_loop import GitHubClient


def test_workflow_source_fetch_is_limited_to_writer_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ordinary CI workflows must not consume one contents request each."""
    client = GitHubClient("token")
    content_paths: list[str] = []

    def fake(path: str, *, method: str = "GET", payload: Any = None) -> Any:
        del method, payload
        if "actions/workflows" in path:
            return {
                "workflows": [
                    {
                        "id": 1,
                        "name": "Ordinary CI",
                        "path": ".github/workflows/ci.yml",
                        "state": "active",
                    },
                    {
                        "id": 2,
                        "name": "Hourly Product Development",
                        "path": ".github/workflows/hourly-product-development.yml",
                        "state": "active",
                    },
                ]
            }
        if "/contents/" in path:
            content_paths.append(path)
            data = b'on:\n  schedule:\n    - cron: "7 * * * *"\n'
            return {
                "type": "file",
                "size": len(data),
                "sha": "source-sha",
                "encoding": "base64",
                "content": base64.b64encode(data).decode(),
            }
        raise AssertionError(path)

    monkeypatch.setattr(client, "request", fake)

    records = client.list_workflows("ContextualWisdomLab/example", "a" * 40)

    assert records[0].content is None
    assert records[0].content_sha == ""
    assert records[1].content is not None
    assert len(content_paths) == 1
    assert "hourly-product-development.yml" in content_paths[0]
