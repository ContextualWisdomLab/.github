"""Execute real workflow lifecycle shells, not independently invented path fixtures."""

import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/procurement-workbench-ci.yml"


def steps():
    """Parse the candidate without coercing its GitHub event key."""
    return yaml.load(WORKFLOW.read_text(), Loader=yaml.BaseLoader)["jobs"]["quality"][
        "steps"
    ]


def step(name):
    """Find a named actual executable step."""
    return next(s for s in steps() if s["name"] == name)


def run(body, env, cwd):
    """Use a real shell with harmless synthetic service boundaries."""
    return subprocess.run(
        ["/bin/bash", "-euo", "pipefail", "-c", body],
        env=env,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=10,
    )


def prepare(tmp_path):
    """Invoke actual preparation and consume its exact output records."""
    base = tmp_path.resolve()
    workspace = base / "workspace"
    temp = base / "runner-temp"
    workspace.mkdir()
    temp.mkdir()
    output = base / "output"
    env = {
        **os.environ,
        "WORKSPACE_BASE": str(workspace),
        "TEMP_BASE": str(temp),
        "RUN_ID": "41",
        "RUN_ATTEMPT": "2",
        "PYTHON_VERSION": "3.14",
        "GITHUB_OUTPUT": str(output),
        "RUNNER_TEMP": str(temp),
        "GITHUB_RUN_ID": "41",
        "GITHUB_RUN_ATTEMPT": "2",
        "MATRIX_PYTHON_VERSION": "3.14",
        "GITHUB_ENV": str(base / "legacy-env"),
    }
    result = run(step("Prepare isolated job workspace")["run"], env, base)
    assert result.returncode == 0, result.stderr
    assert output.is_file(), (
        "preparation must publish step outputs, not reserved GITHUB_WORKSPACE overrides"
    )
    values = dict(line.split("=", 1) for line in output.read_text().splitlines())
    return env, values, workspace, temp


def test_prepare_checkout_cleanup_are_one_contiguous_lifecycle(tmp_path):
    """The actual producer paths must qualify for checkout and then be removed."""
    env, values, workspace, temp = prepare(tmp_path)
    source = Path(values["source_absolute"])
    private = Path(values["job_root"])
    assert source == workspace / values["source_relative"]
    assert source.parent == workspace
    assert source.is_dir() and private.is_dir()
    assert private.parent == temp
    assert "GITHUB_WORKSPACE" not in values
    assert (
        step("Checkout admitted product source")["with"]["path"]
        == "${{ steps.prepare.outputs.source_relative }}"
    )
    setup = step("Setup uv")["with"]
    assert setup["cache-local-path"] == "${{ steps.prepare.outputs.job_root }}/uv-cache"
    assert setup["enable-cache"] == "false" and setup["save-cache"] == "false"
    (private / "uv-cache").mkdir()
    (private / "uv-cache" / "sentinel").write_text("current-cache")
    victim = temp / "victim"
    victim.mkdir()
    (victim / "keep").write_text("keep")
    cleanup_env = {
        **env,
        "CLEANUP_SOURCE": str(source),
        "CLEANUP_PRIVATE": str(private),
    }
    cleanup = step("Cleanup job-private workspace")["run"]
    traversal = run(
        cleanup,
        {**cleanup_env, "CLEANUP_PRIVATE": str(private / ".." / "victim")},
        tmp_path,
    )
    assert traversal.returncode != 0
    assert "refusing unexpected cleanup path" in traversal.stderr
    assert (victim / "keep").read_text() == "keep"
    good = run(cleanup, cleanup_env, tmp_path)
    assert good.returncode == 0, good.stderr
    assert not source.exists() and not private.exists()
    assert (victim / "keep").read_text() == "keep"


def test_fresh_checkout_never_reads_stale_workspace_git(tmp_path):
    """A stale outer repository remains untouched; checkout sees an empty child."""
    env, values, workspace, temp = prepare(tmp_path)
    stale = workspace / ".git" / "hooks"
    stale.mkdir(parents=True)
    marker = temp / "hook-ran"
    hook = stale / "post-checkout"
    hook.write_text(f'#!/bin/sh\ntouch "{marker}"\n')
    hook.chmod(0o755)
    source = Path(values["source_absolute"])
    assert list(source.iterdir()) == []
    git_env = {**env, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"}
    git_env.pop("GIT_DIR", None)
    git_env.pop("GIT_WORK_TREE", None)
    for command in (
        ["git", "init", "-q", str(source)],
        [
            "git",
            "-C",
            str(source),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "--allow-empty",
            "-qm",
            "synthetic",
        ],
        [
            "git",
            "-C",
            str(source),
            "-c",
            "core.hooksPath=/dev/null",
            "checkout",
            "--detach",
        ],
    ):
        result = subprocess.run(
            command, env=git_env, capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0, result.stderr
    assert hook.exists() and not marker.exists()


@pytest.mark.parametrize(
    "name",
    [
        "Verify frozen lockfile",
        "Install frozen dependencies",
        "Run full pytest suite",
        "Run Ruff",
        "Check UI JavaScript syntax",
    ],
)
@pytest.mark.parametrize("exit_code", [0, 37])
def test_quality_shell_preserves_each_command_exit(tmp_path, name, exit_code):
    """Success and failure both use the actual wrappers with synthetic executables."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    witness = tmp_path / "called"
    for tool in ("uv", "node"):
        script = bin_dir / tool
        script.write_text(
            f'#!/bin/sh\nprintf called >> "{witness}"\nexit {exit_code}\n'
        )
        script.chmod(0o755)
    env = {
        **os.environ,
        "PATH": str(bin_dir),
        "PROCUREMENT_TEST_TEMP": str(tmp_path / "pytest"),
    }
    result = run(step(name)["run"], env, tmp_path)
    assert witness.read_text() == "called"
    assert result.returncode == exit_code


def test_checkout_path_is_direct_child_of_runner_workspace(tmp_path):
    """Portable path contract; pinned action boundary probe is retained in scratch."""
    env, values, workspace, temp = prepare(tmp_path)
    source = Path(values["source_absolute"])
    assert source.parent == workspace
    assert source.name == values["source_relative"]
    assert ".." not in values["source_relative"]


@pytest.mark.parametrize("linked", ["source", "private"])
def test_cleanup_rejects_replaced_roots_without_deleting_foreign_data(tmp_path, linked):
    """After preparation, a linked root must cause a nonpassing cleanup."""
    env, values, workspace, temp = prepare(tmp_path)
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (foreign / "keep").write_text("keep")
    target = Path(values["source_absolute" if linked == "source" else "job_root"])
    if linked == "private":
        (target / "home").rmdir()
    target.rmdir()
    target.symlink_to(foreign, target_is_directory=True)
    result = run(
        step("Cleanup job-private workspace")["run"],
        {
            **env,
            "CLEANUP_SOURCE": values["source_absolute"],
            "CLEANUP_PRIVATE": values["job_root"],
        },
        tmp_path,
    )
    assert result.returncode == 1
    assert "missing or linked cleanup root" in result.stderr
    assert (foreign / "keep").read_text() == "keep"


def test_preparation_export_failure_rolls_back_only_new_owned_directories(tmp_path):
    """A failed output write leaves no orphan and preserves foreign controls."""
    workspace = tmp_path.resolve() / "workspace"
    temp = tmp_path.resolve() / "temp"
    workspace.mkdir()
    temp.mkdir()
    sentinel = temp / "sentinel"
    sentinel.write_text("keep")
    env = {
        **os.environ,
        "WORKSPACE_BASE": str(workspace),
        "TEMP_BASE": str(temp),
        "RUN_ID": "71",
        "RUN_ATTEMPT": "1",
        "PYTHON_VERSION": "3.12",
        "GITHUB_OUTPUT": str(temp),
    }
    result = run(step("Prepare isolated job workspace")["run"], env, tmp_path)
    assert result.returncode != 0
    assert "IsADirectoryError" in result.stderr
    assert list(workspace.iterdir()) == []
    assert list(temp.iterdir()) == [sentinel]
    assert sentinel.read_text() == "keep"


def test_existing_run_directory_rejects_without_deleting_it(tmp_path):
    """A retained run root is never silently reused or removed on admission."""
    env, values, workspace, temp = prepare(tmp_path)
    source = Path(values["source_absolute"])
    sentinel = source / "old"
    sentinel.write_text("old")
    result = run(step("Prepare isolated job workspace")["run"], env, tmp_path)
    assert result.returncode != 0
    assert "FileExistsError" in result.stderr
    assert sentinel.read_text() == "old"
    assert Path(values["job_root"]).is_dir()


def test_pr_raw_metadata_cannot_fall_back_to_merge_identity():
    """Missing PR fields must remain empty until the event-specific guard."""
    env = step("Admit fixed procurement source")["env"]
    assert env["PR_HEAD_SHA"] == "${{ github.event.pull_request.head.sha }}"
    assert (
        env["HEAD_REPOSITORY"] == "${{ github.event.pull_request.head.repo.full_name }}"
    )
    assert (
        env["BASE_REPOSITORY"] == "${{ github.event.pull_request.base.repo.full_name }}"
    )
    assert all("||" not in v for v in env.values())


@pytest.mark.parametrize(
    "field", ["PR_HEAD_SHA", "HEAD_REPOSITORY", "BASE_REPOSITORY", "PR_NUMBER"]
)
def test_missing_pr_field_is_rejected_despite_valid_push_sha(tmp_path, field):
    """A merge/push SHA cannot replace an absent PR head field."""
    repository = "ContextualWisdomLab/procurement-workbench"
    env = {
        **os.environ,
        "CALLER_REPOSITORY": repository,
        "EVENT_NAME": "pull_request",
        "EVENT_REF": "refs/pull/7/merge",
        "PR_HEAD_SHA": "a" * 40,
        "PUSH_SHA": "b" * 40,
        "HEAD_REPOSITORY": repository,
        "BASE_REPOSITORY": repository,
        "PR_NUMBER": "7",
        "PUSH_DELETED": "false",
        "GITHUB_OUTPUT": str(tmp_path / "output"),
    }
    env[field] = ""
    result = run(step("Admit fixed procurement source")["run"], env, tmp_path)
    assert result.returncode == 1
    assert not (tmp_path / "output").exists()
