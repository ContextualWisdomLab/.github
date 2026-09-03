"""Contract tests for the reusable default-branch Scorecard workflow."""

from pathlib import Path
from typing import Any

import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "scorecard-analysis.yml"


def _load_workflow() -> dict[str, Any]:
    """Parse the workflow as YAML while retaining GitHub expression strings."""
    parsed_workflow = yaml.load(
        WORKFLOW_PATH.read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    assert isinstance(parsed_workflow, dict)
    return parsed_workflow


def _step_by_name(workflow: dict[str, Any], step_name: str) -> dict[str, Any]:
    """Return one named analysis step from the parsed workflow."""
    analysis_job = workflow["jobs"]["analysis"]
    for workflow_step in analysis_job["steps"]:
        if workflow_step.get("name") == step_name:
            return workflow_step
    raise AssertionError(f"missing Scorecard workflow step: {step_name}")


def test_scorecard_analysis_is_reusable_without_losing_branch_history_triggers() -> None:
    """Centralization must preserve push and scheduled SARIF refresh for callers."""
    workflow = _load_workflow()
    trigger_configuration = workflow["on"]

    assert trigger_configuration["workflow_call"] == ""
    assert trigger_configuration["push"]["branches"] == ["main"]
    assert trigger_configuration["schedule"] == [{"cron": "30 1 * * 6"}]


def test_scorecard_analysis_coalesces_only_duplicate_exact_revision_runs() -> None:
    """An older delayed event must never cancel a scan for a newer revision."""
    workflow = _load_workflow()
    concurrency_configuration = workflow["concurrency"]

    assert concurrency_configuration == {
        "group": (
            "scorecard-analysis-${{ github.repository }}-${{ github.ref }}-"
            "${{ github.sha }}"
        ),
        "cancel-in-progress": "true",
    }


def test_scorecard_analysis_keeps_authoritative_sarif_boundaries() -> None:
    """Reuse must retain pinned analysis, credential hygiene, and SARIF upload."""
    workflow = _load_workflow()
    analysis_job = workflow["jobs"]["analysis"]

    assert workflow["permissions"] == "read-all"
    assert analysis_job["permissions"] == {
        "security-events": "write",
        "id-token": "write",
        "contents": "read",
        "issues": "read",
        "pull-requests": "read",
        "checks": "read",
    }

    checkout_step = _step_by_name(workflow, "Checkout code")
    assert checkout_step["uses"] == (
        "actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0"
    )
    assert checkout_step["with"]["persist-credentials"] == "false"

    analysis_step = _step_by_name(workflow, "Run analysis")
    assert analysis_step["uses"] == (
        "ossf/scorecard-action@4eaacf0543bb3f2c246792bd56e8cdeffafb205a"
    )
    assert analysis_step["with"] == {
        "results_file": "results.sarif",
        "results_format": "sarif",
        "publish_results": "false",
    }

    upload_step = _step_by_name(workflow, "Upload to code scanning")
    assert upload_step["continue-on-error"] == "true"
    assert upload_step["uses"] == (
        "github/codeql-action/upload-sarif@db488ddef3bf6cb639b32c2e9a7c0a7ea8271d28"
    )
    assert upload_step["with"] == {"sarif_file": "results.sarif"}
