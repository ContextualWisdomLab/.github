"""Shared hermetic fixtures for central control-plane regression tests."""

from __future__ import annotations

import os

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
