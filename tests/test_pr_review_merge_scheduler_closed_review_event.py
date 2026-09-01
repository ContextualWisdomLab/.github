from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "pr-review-merge-scheduler.yml"


def test_closed_pull_request_review_event_skips_scan_job() -> None:
    """Do not spend scheduler capacity on reviews whose pull request is closed."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    scan_job = workflow.split("  scan-pr-queue:", 1)[1].split(
        "  org-queue-sweep:", 1
    )[0]
    admission = scan_job.split("    runs-on:", 1)[0]

    assert "github.event_name != 'pull_request_review'" in admission
    assert "github.event.pull_request.state == 'open'" in admission
