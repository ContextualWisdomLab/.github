"""Contract for the push-burst coalescing tick.

See docs/doctoring/actions-capacity-root-cause-20260917.md for the
measurement this window is derived from, and
scripts/ci/pr_review_merge_scheduler_core.py's coalesce_enabled()/
head_stable_for_seconds() for the gate this tick's own dispatches pass
through -- the same gate used by every other scheduler invocation, so it
stays inert everywhere else unless this workflow's own env explicitly
turns it on.
"""

from __future__ import annotations

from pathlib import Path

WORKFLOW_PATH = Path(".github/workflows/opencode-review-coalesce-tick.yml")


def _workflow_text() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def _job_block() -> str:
    workflow = _workflow_text()
    return workflow.split("\njobs:\n", 1)[1]


def test_tick_is_inert_by_default():
    """The job's own admission gate, not just documentation, must be the flag."""
    job = _job_block()
    assert "if: vars.OPENCODE_REVIEW_COALESCE_ENABLED == 'true'" in job


def test_tick_runs_every_five_minutes_and_never_carries_manual_dispatch():
    """workflow_dispatch: is a branch-selectable manual entrypoint; central
    workflows must not carry it (test_no_central_workflow_exposes_branch_selected_manual_dispatch)."""
    workflow = _workflow_text()
    on_block = workflow.split("\non:\n", 1)[1].split("\nconcurrency:", 1)[0]
    assert 'cron: "*/5 * * * *"' in on_block
    assert "workflow_dispatch:" not in workflow


def test_tick_does_not_stack():
    """At most one tick runs; a slow tick is never cut off mid-dispatch."""
    workflow = _workflow_text()
    concurrency_block = workflow.split("\nconcurrency:\n", 1)[1].split("\npermissions:\n", 1)[0]
    assert "group: opencode-review-coalesce-tick" in concurrency_block
    assert "cancel-in-progress: false" in concurrency_block


def test_tick_bounds_its_own_wall_clock():
    job = _job_block()
    assert "timeout-minutes: 4" in job


def test_tick_enables_coalescing_for_its_own_invocations_only():
    """Only this workflow's env sets the flag; nothing else should."""
    job = _job_block()
    assert 'OPENCODE_REVIEW_COALESCE_ENABLED: "true"' in job


def test_tick_scopes_each_repository_pass_to_review_dispatch_only():
    """This tick coalesces reviews; it must not merge or update branches."""
    dispatch_step = _workflow_text().split(
        "      - name: Dispatch a coalesced OpenCode review for each stabilized head\n",
        1,
    )[1]
    assert "--no-enable-auto-merge" in dispatch_step
    assert "--no-update-branches" in dispatch_step
    assert "--branch-update-limit 0" in dispatch_step
    assert "--trigger-reviews" in dispatch_step
    assert '--review-workflow "Required OpenCode Review"' in dispatch_step


def test_tick_reuses_the_existing_scheduler_cli_unmodified():
    """No parallel dispatch/dedup logic -- reuse the one, already-tested path."""
    dispatch_step = _workflow_text().split(
        "      - name: Dispatch a coalesced OpenCode review for each stabilized head\n",
        1,
    )[1]
    assert "python3 scripts/ci/pr_review_merge_scheduler.py" in dispatch_step
    assert "/dispatches" not in dispatch_step


def test_tick_searches_the_whole_organization_not_one_repository():
    workflow = _workflow_text()
    assert "org:ContextualWisdomLab is:pr is:open draft:false" in workflow
    assert "search(query:" in workflow


def test_tick_permissions_match_the_existing_scheduler_scan_job():
    """Same permission shape scan-pr-queue already carries for this same call path."""
    job = _job_block()
    job_permissions = job.split("    permissions:\n", 1)[1].split("\n    env:", 1)[0]
    for line in (
        "contents: write",
        "actions: write",
        "pull-requests: write",
        "id-token: write",
    ):
        assert line in job_permissions
