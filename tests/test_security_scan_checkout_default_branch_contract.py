"""Contract: the central Security Scan names Git's initial branch explicitly.

Every `actions/checkout` step in `security-scan.yml` initialises a fresh
repository before fetching the exact SHA. Without an initial-branch setting
Git 2.28+ prints `hint: Using 'master' as the name for the initial branch`
(plus the Git 3.0 rename warning) on every hosted job -- observed live on
consumer runs (issue #2101). The repair is process-local Git configuration
through `GIT_CONFIG_COUNT` / `GIT_CONFIG_KEY_0` / `GIT_CONFIG_VALUE_0` at the
workflow level, so it reaches the action's internal `git init` without a
global gitconfig write and without hiding stderr.
"""

from __future__ import annotations

from pathlib import Path
import re

import pytest


WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/security-scan.yml"


def _workflow_level_env(workflow: str) -> str:
    """Return the top-level ``env:`` mapping text (between ``permissions:`` and ``jobs:``)."""
    header = workflow.split("\njobs:\n", 1)[0]
    match = re.search(r"(?ms)^env:\n((?:  .*\n)+)", header)
    assert match, "security-scan.yml has no workflow-level env: block"
    return match.group(1)


def _assert_jobs_do_not_override_initial_branch(body: str) -> None:
    """Reject job or step configuration that can shadow the workflow Git key."""
    assert "GIT_CONFIG_COUNT" not in body
    assert "GIT_CONFIG_KEY_0" not in body
    assert "git config --global" not in body
    assert "init.defaultBranch" not in body
    # The setting only matters because the exact-head checkouts exist.
    assert body.count("uses: actions/checkout@") >= 6


def test_workflow_level_git_config_names_the_initial_branch() -> None:
    """The three process-local Git config variables must be set exactly."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    env = _workflow_level_env(workflow)
    assert 'GIT_CONFIG_COUNT: "1"' in env
    assert "GIT_CONFIG_KEY_0: init.defaultBranch" in env
    assert "GIT_CONFIG_VALUE_0: main" in env
    assert "#2101" in workflow.split("\njobs:\n", 1)[0]


def test_no_step_overrides_or_globalises_the_initial_branch_setting() -> None:
    """Jobs must neither shadow the variables nor write a global gitconfig."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    body = workflow.split("\njobs:\n", 1)[1]
    _assert_jobs_do_not_override_initial_branch(body)


def test_git_config_value_override_is_rejected() -> None:
    """A job-level value override must not redirect checkout back to another branch name."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    body = workflow.split("\njobs:\n", 1)[1]
    hostile_body = (
        "  hostile-checkout:\n"
        "    runs-on: ubuntu-24.04\n"
        "    env:\n"
        "      GIT_CONFIG_VALUE_0: master\n"
        "    steps: []\n"
        + body
    )
    with pytest.raises(AssertionError):
        _assert_jobs_do_not_override_initial_branch(hostile_body)
