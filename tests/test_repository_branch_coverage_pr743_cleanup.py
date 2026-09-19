"""Regression contracts for PR 743 cleanup and Git configuration isolation."""

from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIRECTORY = REPOSITORY_ROOT / ".github" / "workflows"
REVIEW_WORKFLOW_PATH = WORKFLOW_DIRECTORY / "opencode-review-dispatch.yml"
TEMPORARY_REPAIR_WORKFLOW_PATHS = (
    WORKFLOW_DIRECTORY / "repair-pr743-git-config-red-test.yml",
    WORKFLOW_DIRECTORY / "one-shot-repair-uv-strix-ci.yml",
    WORKFLOW_DIRECTORY / "one-shot-pr743-apply-git-isolation.yml",
)


def test_opencode_runtime_git_calls_use_fully_isolated_configuration() -> None:
    """Every pre-helper Git call must use the complete isolated configuration block."""

    workflow = REVIEW_WORKFLOW_PATH.read_text(encoding="utf-8")
    marker = "          trusted_git() {"
    assert marker in workflow
    runtime = workflow.split(marker, 1)[0]
    count_key = "              GIT_CONFIG_COUNT=1 " + chr(92) + "\n"
    isolated_block = (
        "              GIT_CONFIG_NOSYSTEM=1 " + chr(92) + "\n"
        + "              GIT_CONFIG_GLOBAL=/dev/null " + chr(92) + "\n"
        + count_key
        + "              GIT_CONFIG_KEY_0=safe.directory " + chr(92) + "\n"
        + "              GIT_CONFIG_VALUE_0=/work " + chr(92) + "\n"
    )

    assert runtime.count(count_key) == 4
    assert runtime.count(isolated_block) == 4


def test_pr743_temporary_write_workflows_are_absent() -> None:
    """Completed one-shot branch writers must not remain in the mergeable tree."""

    for temporary_workflow_path in TEMPORARY_REPAIR_WORKFLOW_PATHS:
        assert not temporary_workflow_path.exists()
