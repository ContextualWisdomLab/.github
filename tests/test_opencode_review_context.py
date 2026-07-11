"""Tests for OpenCode review context resolution."""

from __future__ import annotations

import json
import runpy
import sys

import pytest

from scripts.ci import opencode_review_context as context


BASE_SHA = "a" * 40
HEAD_SHA = "b" * 40


def write_event(tmp_path, payload):
    """Write a GitHub event payload and return the path."""
    path = tmp_path / "event.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_pull_request_event_writes_shell_and_github_env(tmp_path):
    """Resolve a pull_request_target event into validated shell and GitHub env files."""
    event_path = write_event(
        tmp_path,
        {
            "pull_request": {
                "number": 380,
                "base": {"sha": BASE_SHA, "repo": {"full_name": "ContextualWisdomLab/.github"}},
                "head": {"sha": HEAD_SHA},
            }
        },
    )
    shell_env = tmp_path / "context.env"
    github_env = tmp_path / "github.env"

    assert (
        context.main(
            [
                "--event-path",
                str(event_path),
                "--env-file",
                str(shell_env),
                "--github-env",
                str(github_env),
                "--changed-files-file",
                "/tmp/changed-files.txt",
            ]
        )
        == 0
    )

    assert "export GH_REPOSITORY=ContextualWisdomLab/.github" in shell_env.read_text(encoding="utf-8")
    github_env_text = github_env.read_text(encoding="utf-8")
    assert f"PR_BASE_SHA={BASE_SHA}" in github_env_text
    assert f"HEAD_SHA={HEAD_SHA}" in github_env_text
    assert "OPENCODE_CHANGED_FILES_FILE=/tmp/changed-files.txt" in github_env_text


def test_workflow_dispatch_inputs_use_default_repository(tmp_path):
    """Resolve workflow_dispatch input values when no pull_request object exists."""
    event_path = write_event(
        tmp_path,
        {
            "inputs": {
                "pr_number": "12",
                "pr_base_sha": BASE_SHA,
                "pr_head_sha": HEAD_SHA,
            }
        },
    )
    shell_env = tmp_path / "context.env"

    assert (
        context.main(
            [
                "--event-path",
                str(event_path),
                "--env-file",
                str(shell_env),
                "--default-repository",
                "ContextualWisdomLab/example",
            ]
        )
        == 0
    )

    shell_env_text = shell_env.read_text(encoding="utf-8")
    assert "export GH_REPOSITORY=ContextualWisdomLab/example" in shell_env_text
    assert "export PR_NUMBER=12" in shell_env_text


def test_invalid_context_value_fails_closed(tmp_path):
    """Reject values that are unsafe for shell environment materialization."""
    event_path = write_event(
        tmp_path,
        {
            "inputs": {
                "target_repository": "ContextualWisdomLab/.github\nBAD=value",
                "pr_number": "12",
                "pr_base_sha": BASE_SHA,
                "pr_head_sha": HEAD_SHA,
            }
        },
    )

    with pytest.raises(SystemExit):
        context.main(["--event-path", str(event_path), "--env-file", str(tmp_path / "context.env")])


def test_load_event_requires_json_object(tmp_path):
    """Reject event payloads that are not JSON objects."""
    event_path = tmp_path / "event.json"
    event_path.write_text("[]", encoding="utf-8")

    with pytest.raises(SystemExit):
        context.load_event(event_path)


def test_load_event_reports_unreadable_payload(tmp_path):
    """Reject missing event payload files with a closed failure."""
    with pytest.raises(SystemExit):
        context.load_event(tmp_path / "missing.json")


def test_module_entrypoint_invokes_main(tmp_path, monkeypatch):
    """Exercise the script entrypoint used by the workflow shell step."""
    event_path = write_event(
        tmp_path,
        {
            "inputs": {
                "pr_number": "12",
                "pr_base_sha": BASE_SHA,
                "pr_head_sha": HEAD_SHA,
            }
        },
    )
    shell_env = tmp_path / "context.env"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "opencode_review_context.py",
            "--event-path",
            str(event_path),
            "--env-file",
            str(shell_env),
            "--default-repository",
            "ContextualWisdomLab/.github",
        ],
    )

    with pytest.raises(SystemExit) as excinfo:
        runpy.run_path(context.__file__, run_name="__main__")

    assert excinfo.value.code == 0
    assert "export PR_NUMBER=12" in shell_env.read_text(encoding="utf-8")
