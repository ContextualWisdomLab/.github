"""Contract tests for the reusable default-branch Scorecard workflow."""

from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "scorecard-analysis.yml"


def test_scorecard_analysis_is_reusable_without_losing_branch_history_triggers() -> None:
    """Centralization must preserve push and scheduled SARIF refresh for callers."""
    workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")
    trigger_block = workflow_text.split("permissions:", 1)[0]

    assert "workflow_call:" in trigger_block
    assert "push:" in trigger_block
    assert 'branches: ["main"]' in trigger_block
    assert "schedule:" in trigger_block
    assert 'cron: "30 1 * * 6"' in trigger_block


def test_scorecard_analysis_coalesces_redundant_default_branch_runs() -> None:
    """Only the newest push or scheduled scan for one repository ref should run."""
    workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")
    concurrency_block = workflow_text.split("concurrency:", 1)[1].split(
        "permissions:", 1
    )[0]

    assert "scorecard-analysis-${{ github.repository }}-${{ github.ref }}" in concurrency_block
    assert "cancel-in-progress: true" in concurrency_block
    assert "queue: max" not in concurrency_block


def test_scorecard_analysis_keeps_authoritative_sarif_boundaries() -> None:
    """Reuse must retain pinned analysis, credential hygiene, and SARIF upload."""
    workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "persist-credentials: false" in workflow_text
    assert "ossf/scorecard-action@4eaacf0543bb3f2c246792bd56e8cdeffafb205a" in workflow_text
    assert "github/codeql-action/upload-sarif@db488ddef3bf6cb639b32c2e9a7c0a7ea8271d28" in workflow_text
    upload_step = workflow_text.split("      - name: Upload to code scanning\n", 1)[1]
    assert "continue-on-error: true" in upload_step
