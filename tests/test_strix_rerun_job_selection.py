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


def test_cross_repo_strix_without_actions_write_dispatches_instead_of_rerun(monkeypatch) -> None:
    """A central sweep must dispatch Strix when its App token cannot rerun sibling-repo jobs."""
    head = "9b435f5159e1389e0e122b0a12e1a630fba1950f"
    pr = {
        "number": 1055,
        "baseRefName": "develop",
        "baseRefOid": "7" * 40,
        "headRefOid": head,
        "statusCheckRollup": {
            "contexts": {"nodes": [_strix_job("strix", 99212031836, "FAILURE")]}
        },
    }
    dispatches: list[tuple[list[str], dict]] = []

    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_REPOSITORY", "ContextualWisdomLab/.github")
    monkeypatch.setenv("GH_TOKEN", "opencode-app-token")
    monkeypatch.setenv("SCHEDULER_ACTIONS_TOKEN", "opencode-app-token")
    monkeypatch.setenv("SCHEDULER_DISPATCH_TOKEN", "central-workflow-token")
    monkeypatch.setenv("SCHEDULER_REQUIRED_WORKFLOW_REPOSITORY", "ContextualWisdomLab/.github")
    monkeypatch.delenv("SCHEDULER_ALLOW_CROSS_REPO_ACTIONS", raising=False)
    monkeypatch.setattr(sched, "active_review_run_refs", lambda *args, **kwargs: ([], []))
    monkeypatch.setattr(sched, "active_workflow_runs", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        sched,
        "rerun_actions_job",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("cross-repository Actions rerun must not use the read-only App token")
        ),
    )

    def record_dispatch(args, *, stdin=None):
        import json

        dispatches.append((list(args), json.loads(stdin or "{}")))
        return ""

    monkeypatch.setattr(sched, "run_github_dispatch", record_dispatch)

    assert (
        sched.dispatch_strix_evidence(
            "ContextualWisdomLab/bandscope",
            "Strix Security Scan",
            pr,
            dry_run=False,
        )
        == "dispatched"
    )
    assert dispatches[0][0][-3:] == ["repos/ContextualWisdomLab/.github/dispatches", "--input", "-"]
    assert dispatches[0][1]["event_type"] == "strix-scan"
    assert dispatches[0][1]["client_payload"]["pr_head_sha"] == head
