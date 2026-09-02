"""Regression coverage for workflow cancellation before runner assignment."""

from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
from subprocess import CompletedProcess


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts/ci/actions_queue_health.py"
SPEC = importlib.util.spec_from_file_location("actions_queue_health", MODULE_PATH)
assert SPEC and SPEC.loader
queue_health = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(queue_health)


def test_collect_snapshot_classifies_cancelled_job_before_runner_assignment() -> None:
    """A cancelled current-head job with no runner or steps stays explicit evidence."""
    repository_name = "owner/repo"
    pull_request = {
        "number": 17,
        "state": "open",
        "base": {"ref": "main", "repo": {"full_name": repository_name}},
        "head": {"sha": "exact-head"},
        "updated_at": "2026-09-02T13:15:00Z",
    }
    cancelled_run = {
        "id": 1701,
        "name": "Repository Metadata Reconcile",
        "workflow_id": 9017,
        "event": "pull_request",
        "status": "completed",
        "conclusion": "cancelled",
        "head_sha": "exact-head",
        "created_at": "2026-09-02T13:00:00Z",
        "updated_at": "2026-09-02T13:08:00Z",
        "run_attempt": 1,
        "pull_requests": [{"number": 17, "head": {"sha": "exact-head"}}],
    }
    cancelled_job = {
        "id": 17001,
        "name": "validate",
        "status": "completed",
        "conclusion": "cancelled",
        "runner_id": 0,
        "runner_name": "",
        "created_at": "2026-09-02T13:00:00Z",
        "steps": [],
    }
    terminal_path = (
        f"repos/{repository_name}/actions/runs?status=completed"
        "&head_sha=exact-head&per_page=50"
    )

    def runner(args: list[str], **_: object) -> CompletedProcess[str]:
        """Return deterministic GitHub REST fixtures for the collector."""
        path = args[-1]
        if path == f"repos/{repository_name}":
            payload: object = {"default_branch": "main"}
        elif path == f"repos/{repository_name}/pulls?state=open&per_page=100":
            payload = [pull_request]
        elif path == terminal_path:
            payload = {"total_count": 1, "workflow_runs": [cancelled_run]}
        elif path == f"repos/{repository_name}/actions/runs/1701/jobs?per_page=100":
            payload = {"total_count": 1, "jobs": [cancelled_job]}
        elif path.startswith(f"repos/{repository_name}/actions/runs?status="):
            payload = {"total_count": 0, "workflow_runs": []}
        else:  # pragma: no cover - unexpected API expansion must fail loudly.
            raise AssertionError(f"unexpected GitHub API path: {path}")
        return CompletedProcess(args, 0, json.dumps(payload), "")

    snapshot = queue_health.collect_snapshot(
        [repository_name],
        runner=runner,
        generated_at="2026-09-02T13:16:00Z",
    )

    assert snapshot["collection_errors"] == []
    assert [run["id"] for run in snapshot["repositories"][0]["runs"]] == [1701]

    report = queue_health.build_report(
        snapshot,
        now=datetime(2026, 9, 2, 13, 16, tzinfo=timezone.utc),
    )
    row = report["runs"][0]
    assert row["identity_state"] == "current_head"
    assert row["run_conclusion"] == "CANCELLED"
    assert row["jobs_materialized"] is True
    assert row["runner_assigned"] is False
    assert row["admission_state"] == "cancelled_before_runner_assignment"
    assert row["blocker"] == "cancelled_before_runner_assignment"
    assert row["recommended_action"] == "inspect_actions_control_plane_without_leaf_bypass"
