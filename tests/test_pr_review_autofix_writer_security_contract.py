"""Fail-closed contracts for the autonomous OpenCode PR writer."""

from __future__ import annotations

import re
from pathlib import Path


_AUTOFIX_WORKFLOW = Path(".github/workflows/pr-review-autofix.yml")
_TARGET_MODEL = "contextual-orchestrator/orchestrator/free"


def _workflow_text() -> str:
    """Return the autonomous writer workflow as canonical UTF-8 text."""
    return _AUTOFIX_WORKFLOW.read_text(encoding="utf-8")


def _step(workflow: str, step_name: str) -> str:
    """Return one named workflow step through the next step boundary."""
    start = workflow.index(f"      - name: {step_name}")
    next_start = workflow.find("\n      - name: ", start + 1)
    if next_start == -1:
        return workflow[start:]
    return workflow[start:next_start]


def _step_header(workflow: str, step_name: str) -> str:
    """Return one workflow step through its environment header, before script code."""
    step = _step(workflow, step_name)
    run_start = step.index("        run: |")
    return step[:run_start]


def test_writer_uses_the_gateway_free_pool_with_high_reasoning() -> None:
    """Pin the write-capable pool and its deliberate high-reasoning budget."""
    workflow = _workflow_text()

    assert f'"model": "{_TARGET_MODEL}"' in workflow
    assert '"orchestrator/free": {' in workflow
    assert workflow.count(f"MODEL: {_TARGET_MODEL}") == 2
    assert '"reasoningEffort": "high"' in workflow
    assert "COPILOT_GITHUB_TOKEN" not in workflow


def test_mutation_steps_never_fall_back_to_read_only_github_token() -> None:
    """Require explicit mutation authority for ordinary and conflict-repair pushes."""
    workflow = _workflow_text()

    ordinary_header = _step_header(workflow, "Commit and push autofix")
    conflict_header = _step_header(
        workflow, "Merge base branch and resolve conflicts with OpenCode"
    )
    for header in (ordinary_header, conflict_header):
        assert "steps.target_app_token.outputs.token" in header
        assert "github.token" not in header


def test_mutation_steps_fail_closed_before_any_git_write() -> None:
    """Reject missing explicit/app mutation credentials before commit or merge work."""
    workflow = _workflow_text()
    availability = (
        "secrets.PR_REVIEW_MERGE_TOKEN != '' || "
        "secrets.OPENCODE_APPROVE_TOKEN != '' || "
        "steps.target_app_token.outputs.available == 'true'"
    )

    ordinary = _step(workflow, "Commit and push autofix")
    conflict = _step(workflow, "Merge base branch and resolve conflicts with OpenCode")
    for step in (ordinary, conflict):
        assert "MUTATION_CREDENTIAL_AVAILABLE:" in step
        assert availability in step
        guard = 'if [ "$MUTATION_CREDENTIAL_AVAILABLE" != "true" ]; then'
        assert guard in step
        assert step.index(guard) < step.index("git ")


def test_read_only_fetch_may_use_workflow_token_without_expanding_write_scope() -> None:
    """Keep workflow-token fallback confined to demonstrably read-only steps."""
    workflow = _workflow_text()
    fetch_header = _step_header(workflow, "Fetch and checkout PR head")

    assert "github.token" in fetch_header
    assert "contents: read" in workflow
    assert "contents: write" not in workflow
    assert "pull-requests: write" not in workflow


def test_read_only_steps_do_not_prefer_mutation_credentials() -> None:
    """Use target-app or workflow read authority without exposing mutation secrets."""
    workflow = _workflow_text()

    for step_name in ("Fetch and checkout PR head", "Collect review feedback context"):
        header = _step_header(workflow, step_name)
        assert "steps.target_app_token.outputs.token || github.token" in header
        assert "PR_REVIEW_MERGE_TOKEN" not in header
        assert "OPENCODE_APPROVE_TOKEN" not in header


def test_autofix_job_has_no_job_level_timeout() -> None:
    """The autofix job must not carry a job-level timeout-minutes.

    This job's body IS a synchronous `opencode run` call (up to two
    invocations: the main autofix pass and a base-merge conflict-resolution
    pass) -- a job-level wall-clock bound here directly caps the model's own
    reasoning/tool-use time once elapsed, which
    docs/product-goal-directive.md #8 prohibits ("Model timeout은
    application·Agent·Gateway 공통 상한 없이 기본 null이다"). An earlier version
    of this job set timeout-minutes: 25, reasoning it gave the model call
    "generous room" -- that reasoning was itself the mistake: any fixed cap
    on a job whose body is the model call is exactly the forbidden
    inference-time cap, not a bound on a step that merely waits on a
    separate async verdict (contrast opencode-review.yml's
    poll_deadline_epoch, which bounds a step polling GitHub for a verdict a
    *different* process prepares, not the model call itself). See
    docs/doctoring/autofix-and-noema-review-model-job-timeout-removal.md.
    """
    workflow = _workflow_text()
    job = workflow.split("  autofix:\n", maxsplit=1)[1]
    job_header = job.split("    steps:\n", maxsplit=1)[0]

    match = re.search(r"^    timeout-minutes: (\d+)$", job_header, flags=re.MULTILINE)
    assert match is None, (
        "autofix must not declare a job-level timeout-minutes -- its body is "
        "a synchronous model call, so any job-level bound caps model "
        "inference time, which this org's model-timeout policy forbids"
    )
