"""Static contracts for the privileged repository metadata workflow."""

import os
from pathlib import Path
import stat
import subprocess
import textwrap


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "repository-metadata-reconcile.yml"


def _metadata_test_script() -> str:
    """Extract the metadata test step's executable shell body."""

    source = WORKFLOW.read_text(encoding="utf-8")
    step = source.split(
        "      - name: Run metadata contract tests at repository quality gates\n", 1
    )[1].split("\n\n  apply:\n", 1)[0]
    return textwrap.dedent(step.split("        run: |\n", 1)[1])


def _write_command_recorder(path: Path) -> None:
    """Create a fake executable that records argv without running project code."""

    path.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$*" >> "$COMMAND_LOG"\n', encoding="utf-8"
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


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
    commands = command_log.read_text(encoding="utf-8").splitlines()
    pytest_commands = [command for command in commands if "-m pytest -q" in command]
    assert pytest_commands
    assert "-m pytest -q" not in pytest_commands
    owner_tests = {
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
    invoked_tests = {
        argument
        for command in pytest_commands
        for argument in command.split()
        if argument.startswith("tests/")
    }
    assert invoked_tests == owner_tests
