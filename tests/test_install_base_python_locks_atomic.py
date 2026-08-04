"""Regression tests for aggregate trusted Python lock installation."""

from __future__ import annotations

import io
import json
import subprocess
from pathlib import Path

from scripts.ci import install_base_python_locks as installer


def _write_lock(root: Path, index: int, source: str) -> None:
    """Append one independently complete materialized lock candidate."""

    manifest_path = root / "manifest.json"
    manifest = (
        json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest_path.exists()
        else []
    )
    filename = f"requirements-{index:03d}.txt"
    manifest.append({"file": filename, "source": source})
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (root / filename).write_text(
        f"demo{index}==1 --hash=sha256:" + (str(index + 1) * 64) + "\n",
        encoding="utf-8",
    )


def test_independent_locks_install_in_one_aggregate_transaction(tmp_path: Path) -> None:
    """Multiple valid locks are resolved together and installed exactly once."""

    _write_lock(tmp_path, 0, "one/requirements-hashes.txt")
    _write_lock(tmp_path, 1, "two/requirements-hashes.txt")
    commands: list[list[str]] = []

    def fake_runner(command: list[str], **kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="")

    stdout = io.StringIO()
    result = installer.install_materialized_locks(
        tmp_path,
        runner=fake_runner,
        stdout=stdout,
    )

    assert result == 0
    assert len(commands) == 4
    assert all("--dry-run" in command for command in commands[:3])
    assert "--dry-run" not in commands[3]
    assert commands[2].count("-r") == 2
    assert commands[3].count("-r") == 2
    assert "installed=2 skipped=0" in stdout.getvalue()


def test_aggregate_preflight_conflict_blocks_install(tmp_path: Path) -> None:
    """Cross-lock dependency conflicts fail before any mutating pip install."""

    _write_lock(tmp_path, 0, "one/requirements-hashes.txt")
    _write_lock(tmp_path, 1, "two/requirements-hashes.txt")
    commands: list[list[str]] = []

    def fake_runner(command: list[str], **kwargs):
        commands.append(command)
        if len(commands) == 3:
            return subprocess.CompletedProcess(
                command,
                31,
                stdout="ERROR: ResolutionImpossible: conflicting dependencies",
            )
        return subprocess.CompletedProcess(command, 0, stdout="")

    stderr = io.StringIO()
    result = installer.install_materialized_locks(
        tmp_path,
        runner=fake_runner,
        stderr=stderr,
    )

    assert result == 31
    assert len(commands) == 3
    assert all("--dry-run" in command for command in commands)
    assert "preflight failed" in stderr.getvalue()
    assert "ResolutionImpossible" in stderr.getvalue()
