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
    # This test's own concern is job selection (the "strix" scan job, not its
    # "publish-manual-pr-evidence-status" sibling) -- not the separate live
    # head-freshness re-check `dispatch_strix_evidence` now performs before
    # any rerun, which needs a real `gh` call and has its own dedicated
    # coverage. Stub it to the happy path so this test stays focused.
    monkeypatch.setattr(sched, "live_dispatch_head_matches", lambda repo, pr: True)

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
