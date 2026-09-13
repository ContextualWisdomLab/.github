"""Regression contracts for Required OpenCode pre-review coverage RCA routing."""

from scripts.ci import pr_review_fix_scheduler as fix


def _required_opencode_check(
    *,
    name: str,
    conclusion: str | None,
    status: str = "COMPLETED",
    created_at: str = "2026-09-13T00:00:00Z",
) -> dict:
    """Build one Required OpenCode Review check-run fixture."""
    return {
        "__typename": "CheckRun",
        "name": name,
        "status": status,
        "conclusion": conclusion,
        "checkSuite": {
            "createdAt": created_at,
            "workflowRun": {"workflow": {"name": "Required OpenCode Review"}},
        },
    }


def _pr_with_checks(*checks: dict) -> dict:
    """Build the minimal clean same-head PR context required by RCA classification."""
    return {
        "number": 2079,
        "isDraft": False,
        "baseRefName": "main",
        "baseRefOid": "b" * 40,
        "headRefName": "feature",
        "headRefOid": "a" * 40,
        "headRepository": {"nameWithOwner": "owner/repo"},
        "mergeStateStatus": "CLEAN",
        "reviews": {"nodes": []},
        "reviewThreads": {"nodes": []},
        "statusCheckRollup": {"contexts": {"nodes": list(checks)}},
    }


def test_required_opencode_coverage_failure_routes_to_rca_without_review() -> None:
    """A failed source-backed coverage gate must reach RCA before model review exists."""
    pr = _pr_with_checks(
        _required_opencode_check(name="coverage-evidence", conclusion="FAILURE")
    )

    assert fix.current_head_failed_checks(pr) == ("coverage-evidence",)
    assert fix.needs_rca_repair(pr) == (
        True,
        ("current-head failed check(s) require RCA: coverage-evidence",),
    )


def test_required_opencode_orchestrator_failure_stays_nonrecursive() -> None:
    """The OpenCode orchestration status must not recursively dispatch its own repair."""
    pr = _pr_with_checks(
        _required_opencode_check(name="opencode-review", conclusion="FAILURE")
    )

    assert fix.current_head_failed_checks(pr) == ()
    assert fix.needs_rca_repair(pr) == (False, ())


def test_pending_required_opencode_coverage_attempt_supersedes_stale_failure() -> None:
    """A pending coverage rerun must retire stale failure evidence until it is terminal."""
    pr = _pr_with_checks(
        _required_opencode_check(
            name="coverage-evidence",
            conclusion="FAILURE",
            created_at="2026-09-13T00:00:00Z",
        ),
        _required_opencode_check(
            name="coverage-evidence",
            conclusion=None,
            status="IN_PROGRESS",
            created_at="2026-09-13T00:05:00Z",
        ),
    )

    assert fix.current_head_failed_checks(pr) == ()
    assert fix.needs_rca_repair(pr) == (False, ())


def test_newer_required_opencode_coverage_success_supersedes_stale_failure() -> None:
    """A newer successful coverage attempt must retire the older failure evidence."""
    pr = _pr_with_checks(
        _required_opencode_check(
            name="coverage-evidence",
            conclusion="FAILURE",
            created_at="2026-09-13T00:00:00Z",
        ),
        _required_opencode_check(
            name="coverage-evidence",
            conclusion="SUCCESS",
            created_at="2026-09-13T00:05:00Z",
        ),
    )

    assert fix.current_head_failed_checks(pr) == ()
    assert fix.needs_rca_repair(pr) == (False, ())
