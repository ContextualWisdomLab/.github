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
    skipped_job = {
        "id": 17002,
        "name": "publish optional evidence",
        "status": "completed",
        "conclusion": "skipped",
        "runner_id": 0,
        "runner_name": "",
        "created_at": "2026-09-02T13:00:00Z",
        "steps": [],
    }
    missing_steps_job = {
        "id": 17003,
        "name": "cancelled without step evidence",
        "status": "completed",
        "conclusion": "cancelled",
        "runner_id": 0,
        "runner_name": "",
        "created_at": "2026-09-02T13:00:00Z",
    }
    null_steps_job = {
        **missing_steps_job,
        "id": 17004,
        "name": "cancelled with null step evidence",
        "steps": None,
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
            payload = {
                "total_count": 4,
                "jobs": [
                    cancelled_job,
                    skipped_job,
                    missing_steps_job,
                    null_steps_job,
                ],
            }
        elif "status=startup_failure" in path:
            raise AssertionError(
                "GitHub workflow-run status filtering does not accept startup_failure"
            )
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
    cancelled_row = next(row for row in report["runs"] if row["job_id"] == 17001)
    assert cancelled_row["identity_state"] == "current_head"
    assert cancelled_row["run_conclusion"] == "CANCELLED"
    assert cancelled_row["jobs_materialized"] is True
    assert cancelled_row["runner_assigned"] is False
    assert cancelled_row["admission_state"] == "cancelled_before_runner_assignment"
    assert cancelled_row["blocker"] == "cancelled_before_runner_assignment"
    assert cancelled_row["recommended_action"] == (
        "inspect_actions_control_plane_without_leaf_bypass"
    )

    skipped_row = next(row for row in report["runs"] if row["job_id"] == 17002)
    assert skipped_row["run_conclusion"] == "CANCELLED"
    assert skipped_row["admission_state"] != "cancelled_before_runner_assignment"
    for unavailable_step_job_id in (17003, 17004):
        unavailable_step_row = next(
            row for row in report["runs"] if row["job_id"] == unavailable_step_job_id
        )
        assert unavailable_step_row["admission_state"] != (
            "cancelled_before_runner_assignment"
        )
    assert report["summary"]["cancelled_before_runner_assignment_count"] == 1


def test_collect_snapshot_retains_cancelled_pull_request_target_current_head() -> None:
    """A target-triggered cancellation uses linked PR head identity, not base SHA."""
    repository_name = "owner/repo"
    pull_request = {
        "number": 23,
        "state": "open",
        "base": {"ref": "main", "repo": {"full_name": repository_name}},
        "head": {"sha": "exact-target-head"},
        "updated_at": "2026-09-02T13:20:00Z",
    }
    cancelled_run = {
        "id": 2301,
        "name": "Target Review",
        "workflow_id": 9023,
        "event": "pull_request_target",
        "status": "completed",
        "conclusion": "cancelled",
        "head_sha": "base-commit-sha",
        "created_at": "2026-09-02T13:00:00Z",
        "updated_at": "2026-09-02T13:05:00Z",
        "run_attempt": 1,
        "pull_requests": [
            {"number": 23, "head": {"sha": "exact-target-head"}}
        ],
    }
    cancelled_job = {
        "id": 23001,
        "name": "review",
        "status": "completed",
        "conclusion": "cancelled",
        "runner_id": 0,
        "runner_name": "",
        "created_at": "2026-09-02T13:00:00Z",
        "steps": [],
    }
    head_terminal_path = (
        f"repos/{repository_name}/actions/runs?status=completed"
        "&head_sha=exact-target-head&per_page=50"
    )
    target_cancelled_path = (
        f"repos/{repository_name}/actions/runs?status=cancelled"
        "&event=pull_request_target&per_page=50"
    )

    def runner(args: list[str], **_: object) -> CompletedProcess[str]:
        """Model GitHub target runs whose run-level SHA is the base commit."""
        path = args[-1]
        if path == f"repos/{repository_name}":
            payload: object = {"default_branch": "main"}
        elif path == f"repos/{repository_name}/pulls?state=open&per_page=100":
            payload = [pull_request]
        elif path == head_terminal_path:
            payload = {"total_count": 0, "workflow_runs": []}
        elif path == target_cancelled_path:
            payload = {"total_count": 1, "workflow_runs": [cancelled_run]}
        elif "status=startup_failure" in path:
            raise AssertionError(
                "GitHub workflow-run status filtering does not accept startup_failure"
            )
        elif path == f"repos/{repository_name}/actions/runs/2301/jobs?per_page=100":
            payload = {"total_count": 1, "jobs": [cancelled_job]}
        elif path.startswith(f"repos/{repository_name}/actions/runs?status="):
            payload = {"total_count": 0, "workflow_runs": []}
        else:  # pragma: no cover - unexpected API expansion must fail loudly.
            raise AssertionError(f"unexpected GitHub API path: {path}")
        return CompletedProcess(args, 0, json.dumps(payload), "")

    snapshot = queue_health.collect_snapshot(
        [repository_name],
        runner=runner,
        generated_at="2026-09-02T13:21:00Z",
    )

    assert snapshot["collection_errors"] == []
    assert [run["id"] for run in snapshot["repositories"][0]["runs"]] == [2301]
    report = queue_health.build_report(
        snapshot,
        now=datetime(2026, 9, 2, 13, 21, tzinfo=timezone.utc),
    )
    assert report["runs"][0]["identity_state"] == "current_head"
    assert report["runs"][0]["admission_state"] == (
        "cancelled_before_runner_assignment"
    )


def test_collect_snapshot_rejects_head_change_after_target_evidence_read() -> None:
    """Terminal evidence is rejected when its PR identity changes before completion."""
    repository_name = "owner/repo"
    original_pull_request = {
        "number": 29,
        "state": "open",
        "base": {"ref": "main", "repo": {"full_name": repository_name}},
        "head": {"sha": "original-head"},
        "updated_at": "2026-09-02T13:22:00Z",
    }
    changed_pull_request = {
        **original_pull_request,
        "head": {"sha": "replacement-head"},
        "updated_at": "2026-09-02T13:24:00Z",
    }
    cancelled_run = {
        "id": 2901,
        "name": "Target Review",
        "workflow_id": 9029,
        "event": "pull_request_target",
        "status": "completed",
        "conclusion": "cancelled",
        "head_sha": "base-commit-sha",
        "created_at": "2026-09-02T13:00:00Z",
        "updated_at": "2026-09-02T13:05:00Z",
        "run_attempt": 1,
        "pull_requests": [{"number": 29, "head": {"sha": "original-head"}}],
    }
    cancelled_job = {
        "id": 29001,
        "name": "review",
        "status": "completed",
        "conclusion": "cancelled",
        "runner_id": 0,
        "runner_name": "",
        "created_at": "2026-09-02T13:00:00Z",
        "steps": [],
    }
    head_terminal_path = (
        f"repos/{repository_name}/actions/runs?status=completed"
        "&head_sha=original-head&per_page=50"
    )
    target_cancelled_path = (
        f"repos/{repository_name}/actions/runs?status=cancelled"
        "&event=pull_request_target&per_page=50"
    )
    pull_read_count = 0

    def runner(args: list[str], **_: object) -> CompletedProcess[str]:
        """Advance the PR head only after terminal/job evidence has been read."""
        nonlocal pull_read_count
        path = args[-1]
        if path == f"repos/{repository_name}":
            payload: object = {"default_branch": "main"}
        elif path == f"repos/{repository_name}/pulls?state=open&per_page=100":
            pull_read_count += 1
            payload = [
                changed_pull_request if pull_read_count >= 3 else original_pull_request
            ]
        elif path == head_terminal_path:
            payload = {"total_count": 0, "workflow_runs": []}
        elif path == target_cancelled_path:
            payload = {"total_count": 1, "workflow_runs": [cancelled_run]}
        elif path == f"repos/{repository_name}/actions/runs/2901/jobs?per_page=100":
            payload = {"total_count": 1, "jobs": [cancelled_job]}
        elif "status=startup_failure" in path:
            raise AssertionError(
                "GitHub workflow-run status filtering does not accept startup_failure"
            )
        elif path.startswith(f"repos/{repository_name}/actions/runs?status="):
            payload = {"total_count": 0, "workflow_runs": []}
        else:  # pragma: no cover - unexpected API expansion must fail loudly.
            raise AssertionError(f"unexpected GitHub API path: {path}")
        return CompletedProcess(args, 0, json.dumps(payload), "")

    snapshot = queue_health.collect_snapshot(
        [repository_name],
        runner=runner,
        generated_at="2026-09-02T13:25:00Z",
    )

    assert snapshot["repositories"] == []
    assert snapshot["collection_errors"] == [
        {
            "repository": repository_name,
            "error": "pull-request identity snapshot changed during evidence collection",
        }
    ]
    assert pull_read_count == 3
