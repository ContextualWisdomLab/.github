"""Regression contracts for manual Strix dispatch isolation."""

from __future__ import annotations

from typing import Any

from scripts.ci import pr_review_merge_scheduler_core as scheduler


def _check(
    *,
    event: str,
    conclusion: str = "SUCCESS",
    status: str = "COMPLETED",
    created_at: str = "2026-09-07T00:00:00Z",
    details_url: str | None = None,
) -> dict[str, Any]:
    """Build one Strix CheckRun with an explicit Actions trigger."""
    node: dict[str, Any] = {
        "__typename": "CheckRun",
        "name": "strix",
        "status": status,
        "conclusion": conclusion,
        "startedAt": created_at,
        "checkSuite": {
            "createdAt": created_at,
            "workflowRun": {
                "event": event,
                "workflow": {"name": "Strix Security Scan"},
            },
        },
    }
    if details_url is not None:
        node["detailsUrl"] = details_url
    return node


def _pull_request(*nodes: dict[str, Any]) -> dict[str, Any]:
    """Build one current-head PR rollup."""
    return {
        "number": 1061,
        "headRefOid": "a" * 40,
        "statusCheckRollup": {"contexts": {"nodes": list(nodes)}},
    }


def test_graphql_and_helpers_preserve_workflow_event() -> None:
    """Both paginated query shapes retain the event used for authority."""
    assert "workflowRun {\n              event" in scheduler.PULL_REQUEST_FIELDS_FRAGMENT
    assert "workflowRun { event workflow { name } }" in scheduler.PR_CONTEXTS_PAGE_QUERY
    assert scheduler.workflow_run_event({}) == ""
    manual = _check(event=" workflow_dispatch ")
    assert scheduler.workflow_run_event(manual) == "workflow_dispatch"
    assert scheduler.is_manual_workflow_dispatch(manual)
    assert not scheduler.is_strix_context(manual)
    assert scheduler.is_strix_context(_check(event="pull_request_target"))


def test_newer_manual_run_cannot_hide_required_failure() -> None:
    """A newer manual run stays distinct from required Strix evidence."""
    required = _check(
        event="pull_request_target",
        conclusion="FAILURE",
        created_at="2026-09-07T00:00:00Z",
    )
    manual = _check(
        event="workflow_dispatch",
        created_at="2026-09-07T00:01:00Z",
    )
    pull_request = _pull_request(required, manual)

    assert len(scheduler.latest_check_runs(pull_request)) == 2
    assert scheduler.strix_evidence_state(pull_request) == "failed"
    assert scheduler.failed_status_checks(pull_request) == ["strix"]


def test_manual_action_required_and_job_are_not_scheduler_authority() -> None:
    """Manual Deep runs cannot block or become the required rerun target."""
    manual = _check(
        event="workflow_dispatch",
        conclusion="ACTION_REQUIRED",
        details_url="https://github.com/o/r/actions/runs/1/job/11",
    )
    required = _check(
        event="repository_dispatch",
        details_url="https://github.com/o/r/actions/runs/2/job/22",
    )
    pull_request = _pull_request(manual, required)

    assert scheduler.action_required_checks(pull_request) == []
    assert (
        scheduler.matching_actions_job_id(
            pull_request,
            scheduler.is_strix_context,
        )
        == "22"
    )


def test_active_review_runs_ignore_manual_dispatch(monkeypatch: Any) -> None:
    """A same-head manual run cannot suppress the required Strix dispatch."""
    manual_run = {
        "id": 9500,
        "name": "Strix Security Scan",
        "event": "workflow_dispatch",
        "head_sha": "a" * 40,
        "pull_requests": [{"number": 1061}],
    }
    monkeypatch.setattr(
        scheduler,
        "active_workflow_runs",
        lambda repository, statuses=("queued", "in_progress"): [manual_run],
    )
    monkeypatch.delenv("SCHEDULER_REQUIRED_WORKFLOW_REPOSITORY", raising=False)

    current, stale = scheduler.active_review_run_refs(
        "ContextualWisdomLab/.github",
        "Strix Security Scan",
        _pull_request(),
        run_title="Strix Security Scan",
        workflow_aliases=frozenset({"Strix"}),
    )

    assert current == []
    assert stale == []

def test_manual_non_strix_checks_remain_scheduler_authority() -> None:
    """Manual non-Strix failures remain visible to the central scheduler."""
    failed = {
        "__typename": "CheckRun",
        "name": "dependency-review",
        "status": "COMPLETED",
        "conclusion": "FAILURE",
        "startedAt": "2026-09-07T00:00:00Z",
        "checkSuite": {
            "createdAt": "2026-09-07T00:00:00Z",
            "workflowRun": {
                "event": "workflow_dispatch",
                "workflow": {"name": "Security Scan"},
            },
        },
    }
    blocked = {
        **failed,
        "name": "release-approval",
        "conclusion": "ACTION_REQUIRED",
    }
    pull_request = _pull_request(failed, blocked)

    assert scheduler.failed_status_checks(pull_request) == ["dependency-review"]
    assert scheduler.action_required_checks(pull_request) == ["release-approval"]


def test_manual_non_strix_run_remains_active(monkeypatch: Any) -> None:
    """Manual OpenCode activity is not silently reclassified as Strix."""
    manual_run = {
        "id": 9600,
        "name": "Required OpenCode Review",
        "event": "workflow_dispatch",
        "head_sha": "a" * 40,
        "pull_requests": [{"number": 1061}],
    }
    monkeypatch.setattr(
        scheduler,
        "active_workflow_runs",
        lambda repository, statuses=("queued", "in_progress"): [manual_run],
    )
    monkeypatch.delenv("SCHEDULER_REQUIRED_WORKFLOW_REPOSITORY", raising=False)

    current, stale = scheduler.active_review_run_refs(
        "ContextualWisdomLab/.github",
        "Required OpenCode Review",
        _pull_request(),
        run_title="Required OpenCode Review",
        workflow_aliases=frozenset(scheduler.OPENCODE_WORKFLOW_NAMES),
    )

    assert current == [("ContextualWisdomLab/.github", "9600")]
    assert stale == []
