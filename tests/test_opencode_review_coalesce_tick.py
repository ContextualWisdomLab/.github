"""Contract for the push-burst coalescing tick.

See docs/doctoring/actions-capacity-root-cause-20260917.md for the
measurement this window is derived from, and
scripts/ci/pr_review_merge_scheduler_core.py's coalesce_enabled()/
head_stable_for_seconds() for the gate this tick's own dispatches pass
through -- the same gate used by every other scheduler invocation, so it
stays inert everywhere else unless this workflow's own env explicitly
turns it on. Fail-open horizon N and re-enable criteria live in
docs/adr/0028-opencode-review-coalesce-fail-open.md and
docs/doctoring/coalesce-fail-open-tick-max-age-20260918.md (#2233).
"""

from __future__ import annotations

import importlib
from pathlib import Path

WORKFLOW_PATH = Path(".github/workflows/opencode-review-coalesce-tick.yml")
FAIL_OPEN_DOCTORING = Path(
    "docs/doctoring/coalesce-fail-open-tick-max-age-20260918.md"
)
FAIL_OPEN_ADR = Path("docs/adr/0028-opencode-review-coalesce-fail-open.md")
SCHEDULER_CORE = Path("scripts/ci/pr_review_merge_scheduler_core.py")


def _workflow_text() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def _job_block() -> str:
    workflow = _workflow_text()
    return workflow.split("\njobs:\n", 1)[1]


def _scheduler_core():
    """Import the live scheduler module for constant/contract checks."""
    return importlib.import_module("scripts.ci.pr_review_merge_scheduler_core")


def test_tick_is_inert_by_default():
    """Job-level gate skips before runner admission when coalescing is off.

    Step-scoped gating (#2232) forced inert ticks onto the org runner queue
    (run 35219385415 queued 3h+). The flag must sit on the job, ahead of
    runs-on, so GitHub can complete the schedule run as skipped without a
    runner. See docs/doctoring/coalesce-tick-inert-runner-queue-20260917.md.
    """
    job = _job_block()
    header = job.split("runs-on:", 1)[0]
    assert "if: vars.OPENCODE_REVIEW_COALESCE_ENABLED == 'true'" in header
    assert "if: vars.OPENCODE_REVIEW_COALESCE_ENABLED != 'true'" not in job


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


def test_tick_documents_fail_open_instead_of_sole_schedule_dispatch():
    """Coalesce must never claim synchronize reviews depend only on this cron."""
    workflow = _workflow_text()
    # Comment lines wrap; strip the leading "# " and collapse whitespace so the
    # prose contract is stable across reflow.
    prose = " ".join(
        line[2:].strip() if line.startswith("# ") else ""
        for line in workflow.splitlines()
        if line.startswith("#")
    )
    assert "fail-open to immediate dispatch" in prose
    assert "never depend solely on this schedule" in prose
    assert "the only thing that dispatches" not in prose
    assert "coalesce-fail-open-tick-max-age-20260918.md" in prose
    assert "ADR-0028" in prose


def test_fail_open_horizon_defaults_unset_until_success_ticks_measured():
    """Default N=0 forces fail-open; positive N remains an explicit override."""
    sched = _scheduler_core()
    assert sched.DEFAULT_COALESCE_TICK_MAX_AGE_SECONDS == 0
    assert sched.DEFAULT_COALESCE_WINDOW_SECONDS == 300
    assert sched.coalesce_tick_max_age_seconds() == 0
    core = SCHEDULER_CORE.read_text(encoding="utf-8")
    assert "ADR-0028" in core
    assert "coalesce-fail-open-tick-max-age-20260918.md" in core
    assert "def recent_coalesce_tick_completed(" in core
    assert '!= "success"' in core


def test_fail_open_doctoring_and_adr_refuse_unmeasured_reenable_rules():
    """Zero successful ticks cannot authorize a positive horizon or admission rule."""
    assert FAIL_OPEN_DOCTORING.is_file(), f"missing {FAIL_OPEN_DOCTORING}"
    assert FAIL_OPEN_ADR.is_file(), f"missing {FAIL_OPEN_ADR}"
    text = FAIL_OPEN_DOCTORING.read_text(encoding="utf-8")
    adr = FAIL_OPEN_ADR.read_text(encoding="utf-8")
    assert "DEFAULT_COALESCE_TICK_MAX_AGE_SECONDS = 0" in text or "default N = **0**" in text
    assert "**0**" in text  # successful-tick sample size
    assert "no positive N or re-enable decision is authorized" in text
    assert "OPENCODE_REVIEW_COALESCE_ENABLED" in text
    assert "false" in text
    assert "actions-capacity-root-cause-20260917.md" in text
    assert "coalesce-tick-post-2242-live-verify-20260917.md" in text
    assert "- **Status:** Proposed" in adr
    assert "Leave N unset by default" in adr
    assert "DEFAULT_COALESCE_TICK_MAX_AGE_SECONDS = 0" in adr
    assert "360129488" in adr
    assert "Do **not** set `OPENCODE_REVIEW_COALESCE_ENABLED=true`" in adr
    for forbidden in ("candidate positive N", "≥3 live successful ticks", "candidate **600**", "start 600"):
        assert forbidden not in text
        assert forbidden not in adr
