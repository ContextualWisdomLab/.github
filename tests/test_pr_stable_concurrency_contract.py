"""Executable PR-stable concurrency contracts for Gap G-03."""

from pathlib import Path
import re


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
REQUIRED_PR_WORKFLOWS = (
    "codeql-pr.yml",
    "noema-review.yml",
    "opencode-review.yml",
    "security-scan.yml",
)


def workflow_level_concurrency_group(workflow_text: str) -> str:
    """Return the actual workflow-level group value, excluding comments and sibling keys."""
    workflow_lines = workflow_text.splitlines()
    concurrency_index = next(
        (
            line_index
            for line_index, line_text in enumerate(workflow_lines)
            if line_text == "concurrency:"
        ),
        None,
    )
    if concurrency_index is None:
        raise AssertionError("workflow has no workflow-level concurrency block")

    group_index = next(
        (
            line_index
            for line_index in range(concurrency_index + 1, len(workflow_lines))
            if re.match(r"^  group:", workflow_lines[line_index])
        ),
        None,
    )
    if group_index is None:
        raise AssertionError("workflow-level concurrency block has no group")

    first_value = workflow_lines[group_index].split("group:", 1)[1].strip()
    if not first_value.startswith((">", "|")):
        return first_value

    value_parts: list[str] = []
    for line_text in workflow_lines[group_index + 1 :]:
        if re.match(r"^  [A-Za-z][A-Za-z0-9_-]*:", line_text):
            break
        if not line_text.strip() or line_text.lstrip().startswith("#"):
            continue
        if len(line_text) - len(line_text.lstrip()) < 4:
            break
        value_parts.append(line_text.strip())
    return " ".join(value_parts)


def test_required_pr_workflow_groups_are_repository_and_pr_stable() -> None:
    """Every required PR workflow must coalesce by repository and PR, not head SHA."""
    for workflow_name in REQUIRED_PR_WORKFLOWS:
        workflow_text = (
            REPOSITORY_ROOT / ".github" / "workflows" / workflow_name
        ).read_text(encoding="utf-8")
        group_value = workflow_level_concurrency_group(workflow_text)

        assert (
            "github.event.pull_request.base.repo.full_name" in group_value
            or "github.repository" in group_value
        ), f"{workflow_name} must scope concurrency to the target repository"
        assert (
            "github.event.pull_request.number" in group_value
        ), f"{workflow_name} must scope concurrency to the pull request number"
        assert (
            "github.event.pull_request.head.sha" not in group_value
        ), f"{workflow_name} must keep one concurrency identity across PR head changes"


def test_concurrency_group_parser_ignores_comments_and_sibling_settings() -> None:
    """Comments cannot make a group pass when its actual scalar omits the PR number."""
    workflow_text = """concurrency:
  # github.event.pull_request.number is commentary, not the group value
  group: >-
    repository-only-${{ github.repository }}
  cancel-in-progress: true
"""
    group_value = workflow_level_concurrency_group(workflow_text)
    assert group_value == "repository-only-${{ github.repository }}"
    assert "github.event.pull_request.number" not in group_value
