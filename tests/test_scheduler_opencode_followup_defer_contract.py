"""Cross-file contract for OpenCode follow-up rate-limit deferral."""

from __future__ import annotations

from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DISPATCH_WORKFLOW_PATH = (
    REPOSITORY_ROOT / ".github" / "workflows" / "opencode-review-dispatch.yml"
)
SCHEDULER_FACADE_PATH = (
    REPOSITORY_ROOT / "scripts" / "ci" / "pr_review_merge_scheduler.py"
)


def _merge_scheduler_step(workflow_source: str) -> str:
    """Return the OpenCode post-approval merge-scheduler step."""

    marker = "      - name: Run merge scheduler after approval\n"
    step_start = workflow_source.index(marker)
    try:
        step_end = workflow_source.index("\n      - name:", step_start + len(marker))
    except ValueError:
        step_end = len(workflow_source)
    return workflow_source[step_start:step_end]


def test_facade_signature_matches_the_live_opencode_followup_caller() -> None:
    """Fail when caller arguments drift away from the scoped defer predicate."""

    workflow_source = DISPATCH_WORKFLOW_PATH.read_text(encoding="utf-8")
    scheduler_step = _merge_scheduler_step(workflow_source)
    facade_source = SCHEDULER_FACADE_PATH.read_text(encoding="utf-8")

    assert workflow_source.startswith("name: OpenCode Review Dispatch\n")
    for required_argument in (
        '--max-prs 1',
        '--review-dispatch-limit 0',
        '--merge-mode direct_or_auto',
        '--pr-number "$PR_NUMBER"',
        '--no-trigger-reviews',
        '--enable-auto-merge',
        '--no-update-branches',
    ):
        assert required_argument in scheduler_step

    assert 'GITHUB_WORKFLOW", "") == "OpenCode Review Dispatch"' in facade_source
    assert '_argument_value(argument_values, "--max-prs") == "1"' in facade_source
    assert (
        '_argument_value(argument_values, "--review-dispatch-limit") == "0"'
        in facade_source
    )
    assert '== "direct_or_auto"' in facade_source


def test_followup_documents_the_authoritative_retry_owner() -> None:
    """Keep a bounded scheduler path after this best-effort caller defers."""

    workflow_source = DISPATCH_WORKFLOW_PATH.read_text(encoding="utf-8")
    scheduler_step = _merge_scheduler_step(workflow_source)
    facade_source = SCHEDULER_FACADE_PATH.read_text(encoding="utf-8")

    assert "scheduled scheduler paths remain authoritative" in scheduler_step
    assert "review-event and scheduled scheduler paths remain authoritative" in scheduler_step
    assert "Required PR Review Merge Scheduler heartbeat" in facade_source


def test_rate_limit_defer_stops_the_existing_outer_retry_loop() -> None:
    """Pair caller non-zero retry behavior with facade success-on-defer behavior."""

    workflow_source = DISPATCH_WORKFLOW_PATH.read_text(encoding="utf-8")
    scheduler_step = _merge_scheduler_step(workflow_source)
    facade_source = SCHEDULER_FACADE_PATH.read_text(encoding="utf-8")

    assert "for attempt in 1 2 3; do" in scheduler_step
    assert 'sleep "$((attempt * 5))"' in scheduler_step
    assert "and _is_opencode_post_approval_followup(argument_values)" in facade_source
    assert "return 0" in facade_source
    assert "scheduler_outcome=deferred_rate_limit" in facade_source
