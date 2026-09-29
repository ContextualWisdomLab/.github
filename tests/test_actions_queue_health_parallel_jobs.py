"""Bounded concurrent job reads preserve full evidence and repository failures."""

from threading import Barrier

import pytest

from tests.test_actions_queue_health_post_evidence_retry import queue_health


@pytest.mark.parametrize("failed", [False, True])
def test_parallel_jobs_preserve_sorted_evidence_and_fail_closed(monkeypatch, failed):
    """Four readers must rendezvous; a failed read still invalidates the repository."""
    barrier = Barrier(4, timeout=3)
    runs = [
        {"id": n, "status": "QUEUED", "conclusion": "", "pull_requests": [{"number": 1, "head_sha": "head"}]}
        for n in range(8, 0, -1)
    ]
    monkeypatch.setattr(queue_health, "_read_pull_request_snapshot", lambda *a, **k: [{"number": 1, "state": "open", "head_sha": "head"}])
    monkeypatch.setattr(queue_health, "_normalise_run", lambda repo, run, jobs: {**run, "jobs": jobs})

    def github_json(path, **kwargs):
        """Serve independent job reads with a barrier that rejects serial execution."""
        if path == "repos/owner/repo":
            return {"default_branch": "main"}
        if "/jobs?" in path:
            number = int(path.split("/runs/")[1].split("/")[0])
            barrier.wait()
            if failed and number == 8:
                raise queue_health.QueueHealthError("job evidence unavailable")
            return {"total_count": 1, "jobs": [{"id": number}]}
        return {"total_count": len(runs) if "status=queued&" in path else 0, "workflow_runs": runs if "status=queued&" in path else []}

    monkeypatch.setattr(queue_health, "github_json", github_json)
    snapshot = queue_health.collect_snapshot(["owner/repo"], generated_at="2026-09-27T00:00:00Z")
    if failed:
        assert snapshot["repositories"] == []
        assert snapshot["collection_errors"] == [{"repository": "owner/repo", "error": "job evidence unavailable"}]
    else:
        assert snapshot["collection_errors"] == []
        assert [run["id"] for run in snapshot["repositories"][0]["runs"]] == list(range(1, 9))
        assert all(run["jobs"] == [{"id": run["id"]}] for run in snapshot["repositories"][0]["runs"])
