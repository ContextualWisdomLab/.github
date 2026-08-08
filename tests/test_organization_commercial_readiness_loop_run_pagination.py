from __future__ import annotations

from typing import Any

import pytest

from scripts.ci.organization_commercial_readiness_loop import GitHubClient


def test_active_writer_inventory_paginates_every_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A writer beyond the first 100 active runs must still hold the lease."""
    client = GitHubClient("token")
    requested_paths: list[str] = []

    def fake(path: str, *, method: str = "GET", payload: Any = None) -> Any:
        del method, payload
        requested_paths.append(path)
        status = path.split("status=")[1].split("&")[0]
        page = int(path.rsplit("page=", maxsplit=1)[1])
        if status == "queued" and page == 1:
            return {
                "workflow_runs": [
                    {
                        "id": index + 1,
                        "name": "Ordinary CI",
                        "path": ".github/workflows/ci.yml",
                        "status": "queued",
                        "head_sha": "a" * 40,
                    }
                    for index in range(100)
                ]
            }
        if status == "queued" and page == 2:
            return {
                "workflow_runs": [
                    {
                        "id": 101,
                        "name": "Hourly Product Development",
                        "path": ".github/workflows/hourly-product-development.yml",
                        "status": "queued",
                        "head_sha": "b" * 40,
                    }
                ]
            }
        return {"workflow_runs": []}

    monkeypatch.setattr(client, "request", fake)

    records = client.list_active_runs("ContextualWisdomLab/example")

    assert len(records) == 101
    assert records[-1].name == "Hourly Product Development"
    assert any("status=queued&per_page=100&page=2" in path for path in requested_paths)
