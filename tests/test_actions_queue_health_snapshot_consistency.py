"""Regression tests for stable queue-health identity and audit evidence."""

from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
from subprocess import CompletedProcess

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts/ci/actions_queue_health.py"
SPEC = importlib.util.spec_from_file_location("actions_queue_health_consistency", MODULE_PATH)
assert SPEC and SPEC.loader
queue_health = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(queue_health)
NOW = datetime(2026, 9, 2, 0, 0, tzinfo=timezone.utc)


def _pull(head_sha: str = "head") -> dict:
    """Return one complete open pull-request identity fixture."""
    return {
        "number": 1,
        "state": "open",
        "base": {"ref": "main", "repo": {"full_name": "owner/repo"}},
        "head": {"sha": head_sha},
        "updated_at": "2026-09-01T23:00:00Z",
    }


def _run(run_id: int, workflow_id: int, *, name: str = "shared-name") -> dict:
    """Return one current-head queued workflow run with stable workflow identity."""
    return {
        "id": run_id,
        "workflow_id": workflow_id,
        "name": name,
        "event": "pull_request",
        "status": "queued",
        "conclusion": "",
        "head_sha": "head",
        "created_at": "2026-09-01T23:30:00Z",
        "updated_at": "2026-09-01T23:30:00Z",
        "run_attempt": 1,
        "pull_requests": [{"number": 1, "head": {"sha": "head"}}],
        "jobs": [],
    }


def _runner_with_pull_transition(final_pulls: list[dict]):
    """Return a runner whose final pull read differs from its initial read."""
    pull_reads = 0

    def runner(args: list[str], **kwargs: object) -> CompletedProcess[str]:
        """Serve metadata, pull identities, and empty active-run partitions."""
        nonlocal pull_reads
        path = args[-1]
        if path == "repos/owner/repo":
            payload: object = {"default_branch": "main"}
        elif path == "repos/owner/repo/pulls?state=open&per_page=100":
            pull_reads += 1
            payload = [_pull()] if pull_reads == 1 else final_pulls
        elif "/actions/runs?status=" in path:
            payload = []
        else:  # pragma: no cover - any new endpoint must be explicitly governed.
            raise AssertionError(f"unexpected endpoint: {path}")
        return CompletedProcess(args, 0, json.dumps(payload), "")

    return runner


@pytest.mark.parametrize("final_pulls", [[_pull("new-head")], []])
def test_collect_snapshot_rejects_pull_identity_changes_during_run_sweep(
    final_pulls: list[dict],
) -> None:
    """A concurrent push or closure cannot corrupt current-head classification."""
    snapshot = queue_health.collect_snapshot(
        ["owner/repo"],
        runner=_runner_with_pull_transition(final_pulls),
        generated_at="2026-09-02T00:00:00Z",
    )
    assert snapshot["repositories"] == []
    assert snapshot["collection_errors"] == [
        {
            "repository": "owner/repo",
            "error": "pull-request identity snapshot changed during collection",
        }
    ]


def test_distinct_workflow_ids_with_same_display_name_are_not_duplicate_lanes() -> None:
    """Duplicate-lane evidence groups by stable workflow identity, not display name."""
    snapshot = {
        "generated_at": "2026-09-01T23:45:00Z",
        "repositories": [
            {
                "full_name": "owner/repo",
                "pull_requests": [_pull()],
                "runs": [_run(100, 501), _run(101, 502)],
            }
        ],
    }
    report = queue_health.build_report(snapshot, now=NOW)
    assert report["summary"]["duplicate_pending_lane_count"] == 0
    assert {row["workflow_id"] for row in report["runs"]} == {501, 502}
    assert {row["workflow_identity"] for row in report["runs"]} == {
        "workflow_id:501",
        "workflow_id:502",
    }


def test_same_workflow_id_across_runs_is_one_duplicate_lane() -> None:
    """Two pending runs of one workflow remain a true duplicate execution lane."""
    snapshot = {
        "generated_at": "2026-09-01T23:45:00Z",
        "repositories": [
            {
                "full_name": "owner/repo",
                "pull_requests": [_pull()],
                "runs": [_run(100, 501), _run(101, 501)],
            }
        ],
    }
    report = queue_health.build_report(snapshot, now=NOW)
    assert report["summary"]["duplicate_pending_lane_count"] == 1
    assert report["duplicate_pending_lanes"] == [
        {
            "repository": "owner/repo",
            "pull_request_number": 1,
            "workflow_identity": "workflow_id:501",
            "workflow_name": "shared-name",
            "count": 2,
        }
    ]


def test_queue_age_exports_the_timestamp_and_source_used_for_calculation() -> None:
    """Report consumers can reproduce queue age from exported evidence."""
    run = _run(100, 501)
    run["status"] = "in_progress"
    run["jobs"] = [
        {
            "id": 1000,
            "name": "second-stage",
            "status": "queued",
            "conclusion": None,
            "runner_id": None,
            "runner_name": None,
            "created_at": "2026-09-01T23:55:00Z",
            "steps": [],
        }
    ]
    report = queue_health.build_report(
        {
            "generated_at": "2026-09-01T23:56:00Z",
            "repositories": [
                {
                    "full_name": "owner/repo",
                    "pull_requests": [_pull()],
                    "runs": [run],
                }
            ],
        },
        now=NOW,
    )
    row = report["runs"][0]
    assert row["queue_age_started_at"] == "2026-09-01T23:55:00Z"
    assert row["queue_age_source"] == "job_created_at"
    assert row["queue_age_seconds"] == 300


def test_invalid_present_workflow_id_fails_closed() -> None:
    """Malformed stable workflow identity cannot silently fall back to a display name."""
    run = _run(100, 501)
    run["workflow_id"] = "501"
    with pytest.raises(queue_health.QueueHealthError, match="workflow id"):
        queue_health.build_report(
            {
                "generated_at": "2026-09-01T23:45:00Z",
                "repositories": [
                    {
                        "full_name": "owner/repo",
                        "pull_requests": [_pull()],
                        "runs": [run],
                    }
                ],
            },
            now=NOW,
        )


def test_queue_health_workflow_does_not_grant_unused_pull_request_permission() -> None:
    """The scheduler token keeps only permissions used outside the cross-repository token."""
    workflow = (ROOT / ".github/workflows/actions-queue-health.yml").read_text(encoding="utf-8")
    assert "pull-requests: read" not in workflow
