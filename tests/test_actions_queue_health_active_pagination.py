"""Active queue pagination covers large queues without accepting truncation."""

import json
from subprocess import CompletedProcess

import pytest

from tests.test_actions_queue_health import api_fixture_path

from tests.test_actions_queue_health_post_evidence_retry import _pull, queue_health


@pytest.mark.parametrize("count", [650, 1001])
def test_active_queue_uses_bounded_pagination_and_rejects_overflow(count):
    """Collect 650 exact records; reject 1001 without ever requesting page 21."""
    paths = []
    raw_paths = []
    runs = [
        {"id": n, "name": "Fixture", "status": "queued", "event": "pull_request", "head_sha": "head", "created_at": "2026-09-27T00:00:00Z"}
        for n in range(1, count + 1)
    ]

    def runner(args, **kwargs):
        """Serve immutable pages through the real pagination and parsing boundary."""
        raw_paths.append(args[-1])
        path = api_fixture_path(args[-1])
        paths.append(path)
        if path == "repos/owner/repo":
            payload = {"default_branch": "main"}
        elif "/pulls?" in path:
            payload = [_pull()]
        elif "status=queued&" in path:
            page = int(path.rsplit("&page=", 1)[1]) if "&page=" in path else 1
            payload = {"total_count": count, "workflow_runs": runs[(page - 1) * 50:page * 50]}
        else:
            payload = {"total_count": 0, "workflow_runs": []}
        return CompletedProcess(args, 0, json.dumps(payload), "")

    snapshot = queue_health.collect_snapshot(["owner/repo"], runner=runner, generated_at="2026-09-27T00:00:00Z")
    active_paths = [path for path in raw_paths if "/actions/runs?status=" in path and "status=completed" not in path and "event=pull_request_target" not in path]
    assert active_paths
    assert all("&created=%3C%3D2026-09-27T00%3A00%3A00Z" in path for path in active_paths)
    assert all("created=" not in path for path in raw_paths if path not in active_paths)
    assert not any("&page=21" in path for path in paths)
    if count == 650:
        assert snapshot["collection_errors"] == []
        assert [run["id"] for run in snapshot["repositories"][0]["runs"]] == list(range(1, 651))
        assert paths.count("repos/owner/repo/actions/runs?status=queued&per_page=50&page=13") == 2
    else:
        assert snapshot["repositories"] == []
        assert "pagination exceeds 20 pages" in snapshot["collection_errors"][0]["error"]
        assert not any("&page=" in path for path in raw_paths)
