"""Regression coverage for exact-head Strix rerun job selection."""

from scripts.ci import pr_review_merge_scheduler as sched


def _strix_job(name: str, job_id: int, conclusion: str) -> dict:
    """Build one exact-head job from the trusted Strix workflow."""
    return {
        "__typename": "CheckRun",
        "name": name,
        "status": "COMPLETED",
        "conclusion": conclusion,
        "startedAt": "2026-08-30T05:24:23Z",
        "detailsUrl": f"https://github.com/ContextualWisdomLab/bandscope/actions/runs/33294403831/job/{job_id}",
        "checkSuite": {
            "createdAt": "2026-08-30T05:22:18Z",
            "workflowRun": {"workflow": {"name": "Strix Security Scan"}},
        },
    }


def test_strix_job_selection_excludes_sibling_publisher() -> None:
    """A skipped status-publisher sibling must not count as the scan job."""
    pr = {
        "number": 1055,
        "statusCheckRollup": {
            "contexts": {
                "nodes": [
                    _strix_job("strix", 99212031836, "FAILURE"),
                    _strix_job("publish-manual-pr-evidence-status", 99212677006, "SKIPPED"),
                ]
            }
        },
    }
    assert sched.matching_actions_job_id(pr, sched.is_strix_scan_check_run) == "99212031836"
