"""Regression for CodeQL reruns whose earlier attempt never dispatched."""

from __future__ import annotations

from pathlib import Path

from tests.test_codeql_pr_workflow_contract import WORKFLOW_PATH, _run_coordinator
from tests.test_opencode_workflow_shell_syntax import _extract_run_block


DISPATCH_STEP_NAME = "Dispatch current-head CodeQL scan"


def test_rerun_without_authenticated_verdict_can_redispatch(tmp_path: Path) -> None:
    """A later attempt may dispatch when only an old-base verdict exists."""
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    coordinator = workflow.split("  dispatch-current-head:\n", 1)[1]
    admission = coordinator.split("\n    runs-on:", 1)[0]

    assert "github.run_attempt == 1" not in admission

    result, post_log, post_body = _run_coordinator(
        tmp_path,
        statuses=[
            {
                "context": f"codeql-dispatch/python/{'c' * 40}",
                "description": f"cwl1;h={'b' * 40};w=codeql-scan-dispatch;r=99",
                "target_url": (
                    "https://github.com/ContextualWisdomLab/.github/actions/runs/122"
                ),
                "state": "success",
                "creator": {"login": "opencode-agent[bot]"},
            },
        ],
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert post_log.read_text(encoding="utf-8").splitlines() == [
        "repos/ContextualWisdomLab/.github/dispatches"
    ]
    assert '"event_type":"codeql-scan"' in post_body.read_text(encoding="utf-8")


def test_status_lookup_paginates_complete_history_before_redispatch() -> None:
    """Recovery inspects every status page before treating a verdict as absent."""
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    script = _extract_run_block(workflow, DISPATCH_STEP_NAME)

    assert (
        'gh api --paginate --slurp '
        '"repos/${TARGET_REPOSITORY}/commits/${PR_HEAD_SHA}/statuses?per_page=100"'
        in script
    )
    assert ".[][]" in script
