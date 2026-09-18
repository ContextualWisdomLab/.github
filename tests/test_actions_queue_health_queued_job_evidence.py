"""Regression contract for queued current-head jobs that materialize after run start."""

from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
from subprocess import CompletedProcess


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts/ci/actions_queue_health.py"
SPEC = importlib.util.spec_from_file_location("actions_queue_health_queued_job", MODULE_PATH)
assert SPEC and SPEC.loader
queue_health = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(queue_health)


def _pull_request() -> dict:
    """Return the open PR whose current head owns the queued run."""
    return {
        "number": 1,
        "state": "open",
        "base": {"ref": "main", "repo": {"full_name": "owner/repo"}},
        "head": {"sha": "head"},
        "updated_at": "2026-09-17T02:55:00Z",
    }


def _queued_run() -> dict:
    """Return an old run whose downstream job only recently became eligible."""
    return {
        "id": 910,
        "workflow_id": 911,
        "name": "required-check",
        "event": "pull_request",
        "status": "queued",
        "conclusion": "",
        "head_sha": "head",
        "created_at": "2026-09-17T00:00:00Z",
        "updated_at": "2026-09-17T02:58:00Z",
        "run_attempt": 1,
        "pull_requests": [{"number": 1, "head": {"sha": "head"}}],
    }


def _queued_job() -> dict:
    """Return the current downstream job with its own later queue timestamp."""
    return {
        "id": 912,
        "name": "dispatch-current-head",
        "status": "queued",
        "conclusion": None,
        "runner_id": None,
        "runner_name": None,
        "created_at": "2026-09-17T02:58:00Z",
        "steps": [],
    }


def test_queued_current_head_fetches_job_evidence_and_uses_job_queue_start() -> None:
    """Time a materialized queued job from its own eligibility, not the parent run."""
    queued_run = _queued_run()
    queued_job = _queued_job()
    responses: dict[str, object] = {
        "repos/owner/repo": {"default_branch": "main"},
        "repos/owner/repo/pulls?state=open&per_page=100": [_pull_request()],
        "repos/owner/repo/actions/runs?status=queued&per_page=50": [queued_run],
        "repos/owner/repo/actions/runs?status=completed&head_sha=head&per_page=50": [],
        "repos/owner/repo/actions/runs?status=cancelled&event=pull_request_target&per_page=50": [],
        "repos/owner/repo/actions/runs/910/jobs?per_page=100": {
            "total_count": 1,
            "jobs": [queued_job],
        },
    }
    for status in ("in_progress", "pending", "requested", "waiting"):
        responses[f"repos/owner/repo/actions/runs?status={status}&per_page=50"] = []

    requested_paths: list[str] = []

    def runner(args: list[str], **_: object) -> CompletedProcess[str]:
        """Return deterministic REST payloads and retain the exact evidence reads."""
        path = args[-1]
        requested_paths.append(path)
        if path not in responses:
            raise AssertionError(f"unexpected endpoint: {path}")
        return CompletedProcess(args, 0, json.dumps(responses[path]), "")

    snapshot = queue_health.collect_snapshot(
        ["owner/repo"],
        runner=runner,
        generated_at="2026-09-17T03:00:00Z",
    )
    assert snapshot["collection_errors"] == []
    observed_run = snapshot["repositories"][0]["runs"][0]
    assert "repos/owner/repo/actions/runs/910/jobs?per_page=100" in requested_paths
    assert [job["id"] for job in observed_run["jobs"]] == [912]
    assert observed_run["jobs"][0]["created_at"] == "2026-09-17T02:58:00Z"

    report = queue_health.build_report(
        snapshot,
        now=datetime(2026, 9, 17, 3, 0, tzinfo=timezone.utc),
    )
    row = report["runs"][0]
    assert row["job_id"] == 912
    assert row["queue_age_source"] == "job_created_at"
    assert row["queue_age_started_at"] == "2026-09-17T02:58:00Z"
    assert row["queue_age_seconds"] == 120
