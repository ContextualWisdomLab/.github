"""Fail-closed contracts for the autonomous OpenCode PR writer."""

from __future__ import annotations

from pathlib import Path


_AUTOFIX_WORKFLOW = Path(".github/workflows/pr-review-autofix.yml")
_TARGET_MODEL = "nvidia-nim/mistralai/mistral-small-4-119b-2603"


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


def test_writer_uses_supported_nvidia_mistral_small_with_high_reasoning() -> None:
    """Pin the write-capable model and its deliberate high-reasoning budget."""
    workflow = _workflow_text()

    assert f'"model": "{_TARGET_MODEL}"' in workflow
    assert '"mistralai/mistral-small-4-119b-2603": {' in workflow
    assert workflow.count(f"MODEL: {_TARGET_MODEL}") == 2
    assert '"reasoningEffort": "high"' in workflow
    assert "nvidia-nim/mistralai/mistral-nemotron" not in workflow
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


def test_mutation_steps_publish_through_one_protected_head_boundary() -> None:
    """Route ordinary and conflict commits through the same exact-head publisher."""
    workflow = _workflow_text()
    publisher = "trusted-autofix-source/scripts/ci/pr_head_publisher.py"

    ordinary = _step(workflow, "Commit and push autofix")
    conflict = _step(workflow, "Merge base branch and resolve conflicts with OpenCode")
    assert publisher in ordinary
    assert publisher in conflict
    assert "--kind review" in ordinary
    assert "--kind conflict" in conflict
    assert 'push "$expected_origin"' not in ordinary
    assert 'push "$expected_origin"' not in conflict


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
