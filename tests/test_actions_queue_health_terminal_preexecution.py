"""Regression contracts for terminal failures that never obtained a runner."""

from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
from subprocess import CompletedProcess


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts/ci/actions_queue_health.py"
SPEC = importlib.util.spec_from_file_location("actions_queue_health_terminal", MODULE_PATH)
assert SPEC and SPEC.loader
queue_health = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(queue_health)


def _pull_request() -> dict:
    """Return the exact open-PR identity used by the failed run."""
    return {
        "number": 1,
        "state": "open",
        "base": {"ref": "main", "repo": {"full_name": "owner/repo"}},
        "head": {"sha": "head"},
        "updated_at": "2026-09-15T13:00:00Z",
    }


def _terminal_failure_run() -> dict:
    """Return a completed failure linked to the current pull-request head."""
    return {
        "id": 900,
        "workflow_id": 901,
        "name": "required-check",
        "event": "pull_request",
        "status": "completed",
        "conclusion": "failure",
        "head_sha": "head",
        "created_at": "2026-09-15T13:05:00Z",
        "updated_at": "2026-09-15T13:06:00Z",
        "run_attempt": 1,
        "pull_requests": [{"number": 1, "head": {"sha": "head"}}],
    }


def _terminal_failure_job() -> dict:
    """Return a failed materialized job with no runner and no executed step."""
    return {
        "id": 902,
        "name": "required-check",
        "status": "completed",
        "conclusion": "failure",
        "runner_id": None,
        "runner_name": None,
        "created_at": "2026-09-15T13:05:00Z",
        "steps": [],
    }


def test_terminal_preexecution_failure_survives_collection_and_is_not_product_failure() -> None:
    """Keep failed zero-step jobs as explicit non-passing admission evidence."""
    failed_run = _terminal_failure_run()
    failed_job = _terminal_failure_job()
    responses: dict[str, object] = {
        "repos/owner/repo": {"default_branch": "main"},
        "repos/owner/repo/pulls?state=open&per_page=100": [_pull_request()],
        "repos/owner/repo/actions/runs?status=completed&head_sha=head&per_page=50": [failed_run],
        "repos/owner/repo/actions/runs?status=cancelled&event=pull_request_target&per_page=50": [],
        "repos/owner/repo/actions/runs/900/jobs?per_page=100": {
            "total_count": 1,
            "jobs": [failed_job],
        },
    }
    for status in ("in_progress", "pending", "queued", "requested", "waiting"):
        responses[f"repos/owner/repo/actions/runs?status={status}&per_page=50"] = []

    def runner(args: list[str], **_: object) -> CompletedProcess[str]:
        """Return deterministic GitHub REST payloads for the regression specimen."""
        path = args[-1]
        if path not in responses:
            raise AssertionError(f"unexpected endpoint: {path}")
        return CompletedProcess(args, 0, json.dumps(responses[path]), "")

    snapshot = queue_health.collect_snapshot(
        ["owner/repo"],
        runner=runner,
        generated_at="2026-09-15T13:10:00Z",
    )
    observed_runs = snapshot["repositories"][0]["runs"]
    assert [run["id"] for run in observed_runs] == [900]
    assert observed_runs[0]["jobs"][0]["steps_count"] == 0
    assert observed_runs[0]["jobs"][0]["runner_id"] == 0

    report = queue_health.build_report(
        snapshot,
        now=datetime(2026, 9, 15, 13, 10, tzinfo=timezone.utc),
    )
    row = report["runs"][0]
    assert row["identity_state"] == "current_head"
    assert row["run_conclusion"] == "FAILURE"
    assert row["execution_state"] == "terminal_pre_execution_failure"
    assert row["admission_state"] == "terminal_pre_execution_failure"
    assert row["is_pending"] is False
    assert row["runner_assigned"] is False
    assert row["blocker"] == "terminal_pre_execution_failure_before_runner_assignment"
    assert row["recommended_action"] == "inspect_actions_control_plane_without_leaf_bypass"
    assert report["summary"]["terminal_pre_execution_failure_count"] == 1
    assert report["summary"]["terminal_job_count"] == 1
