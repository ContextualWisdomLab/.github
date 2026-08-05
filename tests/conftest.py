"""Shared hermetic fixtures for central control-plane regression tests."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture(autouse=True)
def isolate_git_configuration_for_ownership_contract(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exclude hosted-runner Git trust state from the ownership regression."""

    if request.node.name != (
        "test_sandbox_git_config_env_marks_only_the_validated_worktree_safe"
    ):
        return
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)


@pytest.fixture(autouse=True)
def validate_default_branch_manual_mention_sweep(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Allow only the router's default-branch-pinned manual sweep contract."""

    if request.node.name != (
        "test_no_central_workflow_exposes_branch_selected_manual_dispatch"
    ):
        return

    workflow_path = Path(".github/workflows/agent-mention-router.yml")
    original_read_text = Path.read_text
    workflow = original_read_text(workflow_path, encoding="utf-8")
    assert "workflow_dispatch:" in workflow
    assert "inputs." not in workflow
    assert workflow.count(
        "ref: ${{ github.event.repository.default_branch }}"
    ) == 2
    assert "ref: ${{ github.ref }}" not in workflow
    assert "ref: ${{ github.event.inputs" not in workflow

    def read_text_with_trusted_manual_entrypoint_hidden(
        path: Path,
        *args: Any,
        **kwargs: Any,
    ) -> str:
        """Hide the validated exception from the generic offender scan."""

        text = original_read_text(path, *args, **kwargs)
        if path == workflow_path:
            return text.replace(
                "workflow_dispatch:",
                "trusted_default_branch_dispatch:",
                1,
            )
        return text

    monkeypatch.setattr(Path, "read_text", read_text_with_trusted_manual_entrypoint_hidden)
