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


def test_pull_request_close_events_cancel_superseded_runs_without_heavy_jobs() -> None:
    workflows = (
        "close-empty-pr.yml",
        "codeql-pr.yml",
        "noema-review.yml",
        "opencode-review.yml",
        "osv-scanner-pr.yml",
        "pr-review-merge-scheduler.yml",
        "scorecard-pr.yml",
        "security-scan.yml",
        "strix.yml",
    )

    for filename in workflows:
        workflow = workflow_text(filename)

        assert "closed" in workflow
        assert "cancel-closed-pr-runs:" in workflow
        assert (
            'PR closed; this run only cancels older runs through workflow concurrency.'
            in workflow
        )
        assert "github.event.action != 'closed'" in workflow

    strix = workflow_text("strix.yml")

    assert (
        "cancel-in-progress: ${{ github.event_name == 'pull_request_target' && "
        "github.event.action == 'closed' }}"
    ) in strix


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


def test_security_scan_skips_dependency_review_when_dependency_graph_is_unavailable() -> None:
    workflow = workflow_text("security-scan.yml")

    assert "id: dependency_review_support" in workflow
    assert "/dependency-graph/compare/${BASE_SHA}...${HEAD_SHA}" in workflow
    assert '"$status" = "403"' in workflow
    assert '"$status" = "404"' in workflow
    assert "steps.dependency_review_support.outputs.supported == 'true'" in workflow


def test_scorecard_sarif_filters_only_required_upload_permission_noise() -> None:
    """Scorecard uploads should not re-open alerts for their own SARIF permission."""
    for filename in ("scorecard-pr.yml", "scorecard-analysis.yml", "security-scan.yml"):
        workflow = workflow_text(filename)

        assert "Filter necessary SARIF upload permission findings" in workflow
        assert 'result.get("ruleId") == "TokenPermissionsID"' in workflow
        assert '"\'security-events\' permission set to \'write\'" in message' in workflow
        assert "Filtered {removed} necessary security-events SARIF upload permission finding(s)." in workflow


def test_repository_declares_fuzzing_surface_for_scorecard() -> None:
    """Keep the central workflow repo discoverable by Scorecard Fuzzing."""
    clusterfuzzlite = REPO_ROOT / ".clusterfuzzlite" / "Dockerfile"
    atheris_harness = REPO_ROOT / "fuzz" / "fuzz_opencode_normalize_output.py"

    assert clusterfuzzlite.is_file()
    assert "FROM scratch" in clusterfuzzlite.read_text(encoding="utf-8")
    assert atheris_harness.is_file()
    assert "import atheris" in atheris_harness.read_text(encoding="utf-8")
