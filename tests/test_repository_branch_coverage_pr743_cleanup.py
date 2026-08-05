"""Regression contracts for PR 743 cleanup and Git configuration isolation."""

from pathlib import Path


REVIEW_WORKFLOW_PATH = Path(".github/workflows/opencode-review-dispatch.yml")
TEMPORARY_REPAIR_WORKFLOW_PATH = Path(
    ".github/workflows/repair-pr743-git-config-red-test.yml"
)


def test_opencode_runtime_git_calls_use_fully_isolated_configuration() -> None:
    """Every pre-helper Git call must disable ambient system and global config."""
    workflow = REVIEW_WORKFLOW_PATH.read_text(encoding="utf-8")
    runtime = workflow.split("          trusted_git() {", 1)[0]
    count_key = "              GIT_CONFIG_COUNT=1 " + chr(92)
    no_system_key = "              GIT_CONFIG_NOSYSTEM=1 " + chr(92)
    no_global_key = "              GIT_CONFIG_GLOBAL=/dev/null " + chr(92)

    runtime_invocations = runtime.count(count_key)

    assert runtime_invocations == 3
    assert runtime.count(no_system_key) == runtime_invocations
    assert runtime.count(no_global_key) == runtime_invocations


def test_pr743_temporary_write_workflow_is_absent() -> None:
    """A completed one-shot branch writer must not remain in the mergeable tree."""
    assert not TEMPORARY_REPAIR_WORKFLOW_PATH.exists()
