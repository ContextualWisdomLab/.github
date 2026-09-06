"""Regression coverage for pre-job GitHub Actions startup failures."""

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


def test_collect_snapshot_preserves_current_head_startup_failure_without_jobs() -> None:
    """A terminal startup failure with zero jobs must remain visible and explicit."""
    repository_name = "owner/repo"
    pull_request = {
        "number": 7,
        "state": "open",
        "base": {"ref": "main", "repo": {"full_name": repository_name}},
        "head": {"sha": "exact-head"},
        "updated_at": "2026-09-02T10:28:00Z",
    }
    startup_failure_run = {
        "id": 701,
        "name": "CodeQL PR",
        "workflow_id": 9001,
        "event": "pull_request",
        "status": "completed",
        "conclusion": "startup_failure",
        "head_sha": "exact-head",
        "created_at": "2026-09-02T10:28:00Z",
        "updated_at": "2026-09-02T10:28:00Z",
        "run_attempt": 1,
        "pull_requests": [{"number": 7, "head": {"sha": "exact-head"}}],
    }
    requested_paths: list[str] = []
    terminal_path = (
        f"repos/{repository_name}/actions/runs?status=completed"
        "&head_sha=exact-head&per_page=50"
    )

    def runner(args: list[str], **_: object) -> CompletedProcess[str]:
        """Return deterministic GitHub REST fixtures for the collector."""
        path = args[-1]
        requested_paths.append(path)
        if path == f"repos/{repository_name}":
            payload: object = {"default_branch": "main"}
        elif path == f"repos/{repository_name}/pulls?state=open&per_page=100":
            payload = [pull_request]
        elif path == terminal_path:
            payload = {"total_count": 1, "workflow_runs": [startup_failure_run]}
        elif path == f"repos/{repository_name}/actions/runs/701/jobs?per_page=100":
            payload = {"total_count": 0, "jobs": []}
        elif path.startswith(f"repos/{repository_name}/actions/runs?status="):
            payload = {"total_count": 0, "workflow_runs": []}
        else:  # pragma: no cover - unexpected API expansion must fail loudly.
            raise AssertionError(f"unexpected GitHub API path: {path}")
        return CompletedProcess(args, 0, json.dumps(payload), "")

    snapshot = queue_health.collect_snapshot(
        [repository_name],
        runner=runner,
        generated_at="2026-09-02T10:30:00Z",
    )

    assert snapshot["collection_errors"] == []
    assert snapshot["repositories"][0]["runs"] == [
        {
            "repository": repository_name,
            "id": 701,
            "workflow_name": "CodeQL PR",
            "event": "pull_request",
            "status": "COMPLETED",
            "conclusion": "STARTUP_FAILURE",
            "head_sha": "exact-head",
            "created_at": "2026-09-02T10:28:00Z",
            "updated_at": "2026-09-02T10:28:00Z",
            "run_attempt": 1,
            "concurrency_group": "unavailable_from_actions_api",
            "pull_requests": [{"number": 7, "head_sha": "exact-head"}],
            "jobs": [],
            "workflow_id": 9001,
            "workflow_identity": "workflow_id:9001",
        }
    ]
    assert terminal_path in requested_paths
    assert f"repos/{repository_name}/actions/runs/701/jobs?per_page=100" in requested_paths

    report = queue_health.build_report(
        snapshot,
        now=datetime(2026, 9, 2, 10, 30, tzinfo=timezone.utc),
    )
    row = report["runs"][0]
    assert row["identity_state"] == "current_head"
    assert row["execution_state"] == "terminal"
    assert row["run_conclusion"] == "STARTUP_FAILURE"
    assert row["jobs_materialized"] is False
    assert row["blocker"] == "startup_failure_before_job_materialization"
    assert row["recommended_action"] == "inspect_actions_control_plane_without_leaf_bypass"


def test_collect_snapshot_retains_old_failure_for_unchanged_current_head() -> None:
    """Current-head startup failures must not disappear merely because they are old."""
    repository_name = "owner/repo"
    pull_request = {
        "number": 8,
        "state": "open",
        "base": {"ref": "main", "repo": {"full_name": repository_name}},
        "head": {"sha": "unchanged-head"},
        "updated_at": "2026-09-02T10:29:00Z",
    }
    old_current_failure = {
        "id": 801,
        "name": "CodeQL PR",
        "workflow_id": 9001,
        "event": "pull_request",
        "status": "completed",
        "conclusion": "startup_failure",
        "head_sha": "unchanged-head",
        "created_at": "2026-08-01T10:00:00Z",
        "updated_at": "2026-08-01T10:00:00Z",
        "run_attempt": 1,
        "pull_requests": [{"number": 8, "head": {"sha": "unchanged-head"}}],
    }
    terminal_path = (
        f"repos/{repository_name}/actions/runs?status=completed"
        "&head_sha=unchanged-head&per_page=50"
    )
    requested_paths: list[str] = []

    def runner(args: list[str], **_: object) -> CompletedProcess[str]:
        """Return an old but still current-head terminal failure by exact SHA."""
        path = args[-1]
        requested_paths.append(path)
        if path == f"repos/{repository_name}":
            payload: object = {"default_branch": "main"}
        elif path == f"repos/{repository_name}/pulls?state=open&per_page=100":
            payload = [pull_request]
        elif path == terminal_path:
            payload = {"total_count": 1, "workflow_runs": [old_current_failure]}
        elif path == f"repos/{repository_name}/actions/runs/801/jobs?per_page=100":
            payload = {"total_count": 0, "jobs": []}
        elif path.startswith(f"repos/{repository_name}/actions/runs?status="):
            payload = {"total_count": 0, "workflow_runs": []}
        else:  # pragma: no cover - unexpected API expansion must fail loudly.
            raise AssertionError(f"unexpected GitHub API path: {path}")
        return CompletedProcess(args, 0, json.dumps(payload), "")

    snapshot = queue_health.collect_snapshot(
        [repository_name],
        runner=runner,
        generated_at="2026-09-02T10:30:00Z",
    )

    assert snapshot["collection_errors"] == []
    assert [run["id"] for run in snapshot["repositories"][0]["runs"]] == [801]
    assert terminal_path in requested_paths
    assert not any("&created=" in path for path in requested_paths)
