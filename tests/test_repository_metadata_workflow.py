"""Static contracts for the privileged repository metadata workflow."""

import os
from pathlib import Path
import stat
import subprocess

import pytest

from tests.test_opencode_workflow_shell_syntax import _extract_run_block


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "repository-metadata-reconcile.yml"
OWNER_TESTS = {
    "tests/test_repository_metadata_reconciliation.py",
    "tests/test_repository_metadata_convergence.py",
    "tests/test_repository_metadata_identity.py",
    "tests/test_repository_metadata_live_verification.py",
    "tests/test_repository_metadata_workflow.py",
    "tests/test_repository_metadata_workflow_pages.py",
    "tests/test_repository_label_taxonomy.py",
    "tests/test_repository_label_reconciliation.py",
    "tests/test_repository_label_convergence.py",
    "tests/test_repository_label_identity.py",
    "tests/test_repository_label_live_verification.py",
}


def _metadata_test_script() -> str:
    """Extract the metadata test step's executable shell body."""

    return _extract_run_block(
        WORKFLOW.read_text(encoding="utf-8"),
        "Run metadata contract tests at repository quality gates",
    )


def _write_command_recorder(path: Path) -> None:
    """Create a fake executable that records argv without running project code."""

    path.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$*" >> "$COMMAND_LOG"\n', encoding="utf-8"
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _record_metadata_commands(tmp_path: Path) -> list[str]:
    """Execute the workflow shell with inert commands and return recorded argv."""

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    for command_name in ("python", "git"):
        _write_command_recorder(fake_bin / command_name)
    command_log = tmp_path / "commands.log"
    environment = os.environ.copy()
    environment.update(
        PATH=f"{fake_bin}{os.pathsep}{environment['PATH']}",
        COMMAND_LOG=str(command_log),
    )
    result = subprocess.run(
        ["bash", "-c", _metadata_test_script()],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return command_log.read_text(encoding="utf-8").splitlines()


def _assert_metadata_commands(commands: list[str]) -> None:
    """Require the exact metadata-owner test set and no bare full-suite command."""

    pytest_commands = [command for command in commands if "-m pytest -q" in command]
    assert pytest_commands
    invoked_tests: set[str] = set()
    for command in pytest_commands:
        targets = {
            argument
            for argument in command.split()
            if argument.startswith("tests/") and argument.endswith(".py")
        }
        assert targets
        assert targets <= OWNER_TESTS
        invoked_tests.update(targets)
    assert invoked_tests == OWNER_TESTS
    assert sum(command.startswith("-m coverage run --branch") for command in commands) == 2
    assert sum(
        command.startswith("-m coverage report --fail-under=100")
        for command in commands
    ) == 2
    assert commands.count("-m coverage erase") == 1
    interrogate = next(
        command for command in commands if command.startswith("-m interrogate ")
    )
    assert "--fail-under 100" in interrogate
    assert "scripts/ci/reconcile_repository_metadata.py" in interrogate
    assert "scripts/ci/reconcile_repository_labels.py" in interrogate
    assert commands.count("diff --check") == 1


def test_metadata_apply_uses_dedicated_least_privilege_credential() -> None:
    """Repository settings writes must not reuse the review/merge credential."""
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "secrets.CWL_REPOSITORY_METADATA_TOKEN" in source
    apply_source = source.split("  apply:", 1)[1]
    assert "secrets.PR_REVIEW_MERGE_TOKEN" not in apply_source
    assert "Require dedicated repository settings credential" in apply_source
    assert 'test -n "${GH_TOKEN}"' in apply_source


def test_metadata_quality_step_runs_every_owned_test_without_the_full_suite(
    tmp_path: Path,
) -> None:
    """The hourly job must run every metadata-owner test and no unrelated suite."""

    commands = _record_metadata_commands(tmp_path)
    _assert_metadata_commands(commands)


def test_metadata_quality_step_rejects_flagged_bare_full_suite(tmp_path: Path) -> None:
    """A pytest flag must not disguise an untargeted repository-wide invocation."""

    commands = _record_metadata_commands(tmp_path)
    pytest_index = next(
        index for index, command in enumerate(commands) if "-m pytest -q" in command
    )
    commands[pytest_index] = "-m pytest -q -W error"

    with pytest.raises(AssertionError):
        _assert_metadata_commands(commands)
