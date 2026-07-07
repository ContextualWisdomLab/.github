from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def workflow_text(name: str) -> str:
    return (REPO_ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")


def test_merge_scheduler_dispatches_one_review_by_default() -> None:
    workflow = workflow_text("pr-review-merge-scheduler.yml")

    assert workflow.count('default: "1"') >= 2
    assert "vars.REVIEW_DISPATCH_LIMIT || '1'" in workflow


def test_required_pull_request_workflows_cancel_superseded_runs() -> None:
    for filename in (
        "close-empty-pr.yml",
        "codeql-pr.yml",
        "osv-scanner-pr.yml",
        "security-scan.yml",
        "scorecard-pr.yml",
    ):
        workflow = workflow_text(filename)

        assert "concurrency:" in workflow
        assert "github.event.pull_request.base.repo.full_name || github.repository" in workflow
        assert "github.event.pull_request.number" in workflow
        assert "cancel-in-progress: true" in workflow


def test_cancelled_review_workflow_runs_do_not_spawn_more_queue_work() -> None:
    for filename in ("noema-review.yml", "pr-review-merge-scheduler.yml"):
        workflow = workflow_text(filename)

        assert "github.event.workflow_run.conclusion != 'cancelled'" in workflow


def test_unassociated_review_workflow_runs_do_not_scan_the_whole_pr_queue() -> None:
    workflow = workflow_text("pr-review-merge-scheduler.yml")

    assert "github.event.workflow_run.pull_requests[0].number" in workflow


def test_fix_scheduler_cancels_superseded_cron_runs() -> None:
    workflow = workflow_text("pr-review-fix-scheduler.yml")

    assert "central-pr-review-fix-scheduler-" in workflow
    assert "cancel-in-progress: true" in workflow
