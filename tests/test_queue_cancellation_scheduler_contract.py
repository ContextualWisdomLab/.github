"""Structural contracts for final-state queue cancellation revalidation."""

from __future__ import annotations

import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "pr-review-merge-scheduler.yml"
HELPER = ROOT / "scripts" / "ci" / "revalidate_queue_cancellation.sh"
TEMP_WRITER = ROOT / ".github" / "workflows" / "_temp_pr1348_final_revalidation_repair.yml"


def test_scheduler_revalidates_each_destructive_candidate() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert workflow.count("scripts/ci/revalidate_queue_cancellation.sh") == 2
    assert '"superseded"' in workflow
    assert '"aged-orphan"' in workflow
    assert 'gh api -X POST "/repos/${repo_full_name}/actions/runs/${run_id}/cancel"' not in workflow


def test_initial_snapshot_is_bounded_without_serial_live_ref_fanout() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    queue_block = workflow.split("# Queue hygiene, part 1:", 1)[1].split(
        "# Queue hygiene, part 2:", 1
    )[0]

    assert "/pulls?state=open&per_page=100" in queue_block
    assert "all(.[];" in queue_block
    assert 'test("^[0-9a-fA-F]{40}$")' in queue_block
    assert "/git/ref/heads/" not in queue_block
    assert "ORG_QUEUE_HYGIENE_MAX_REF_LOOKUPS" not in workflow


def test_revalidation_helper_is_executable_and_temp_writer_is_retired() -> None:
    assert HELPER.is_file()
    assert os.access(HELPER, os.X_OK)
    assert not TEMP_WRITER.exists()


def test_reconciled_scheduler_preserves_current_main_control_plane_fixes() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert '- cron: "0 * * * *"' in workflow
    assert '*/15 * * * *' not in workflow
    assert workflow.count("runs-on: ubuntu-24.04") >= 2
    scan_job = workflow.split("  scan-pr-queue:", 1)[1].split("  org-queue-sweep:", 1)[0]
    assert "github.event_name == 'pull_request_review'" in scan_job.split(
        "TRIGGER_REVIEWS:", 1
    )[1].splitlines()[0]
