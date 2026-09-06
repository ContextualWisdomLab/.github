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


def test_dispatch_strix_reruns_scan_job_not_sibling_publisher(monkeypatch) -> None:
    """A skipped status-publisher sibling must never be selected as the Strix rerun target."""
    pr = {
        "number": 1055,
        "state": "OPEN",
        "headRefOid": "a" * 40,
        "statusCheckRollup": {
            "contexts": {
                "nodes": [
                    _strix_job("strix", 99212031836, "FAILURE"),
                    _strix_job("publish-manual-pr-evidence-status", 99212677006, "SKIPPED"),
                ]
            }
        },
    }
    reruns: list[tuple[str, str, str]] = []

    def record_rerun(repo: str, job_id: str, *, dry_run: bool, action: str) -> None:
        reruns.append((repo, job_id, action))

    monkeypatch.setattr(sched, "rerun_actions_job", record_rerun)
    monkeypatch.setattr(sched, "fetch_pr", lambda *_args: [pr])
    # Keep this test focused on sibling selection, not the independent API binding.
    monkeypatch.setattr(sched, "strix_rerun_identity_verified", lambda *_args: True)

    assert (
        sched.dispatch_strix_evidence(
            "ContextualWisdomLab/bandscope",
            "Strix Security Scan",
            pr,
            dry_run=False,
        )
        == "rerun"
    )
    assert reruns == [
        (
            "ContextualWisdomLab/bandscope",
            "99212031836",
            "rerun-strix-evidence",
        )
    ]
