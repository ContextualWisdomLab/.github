"""Regression tests for the trusted Git subprocess boundary."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.ci import materialize_base_python_requirements as materializer


def _git(repo: Path, *args: str) -> str:
    """Run Git while constructing an isolated fixture repository."""
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _committed_repository(path: Path, marker: str) -> Path:
    """Create one repository whose committed marker identifies its object database."""
    path.mkdir()
    _git(path, "init", "--quiet")
    _git(path, "config", "user.name", "Materializer Test")
    _git(path, "config", "user.email", "materializer@example.invalid")
    (path / "marker.txt").write_text(f"{marker}\n", encoding="utf-8")
    _git(path, "add", "marker.txt")
    _git(path, "commit", "--quiet", "-m", "fixture")
    return path


def test_read_only_git_ignores_ambient_repository_redirection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GIT_DIR cannot redirect exact-base reads into an attacker repository."""
    intended = _committed_repository(tmp_path / "intended", "intended")
    attacker = _committed_repository(tmp_path / "attacker", "attacker")
    monkeypatch.setenv("GIT_DIR", str(attacker / ".git"))

    observed = materializer._git(intended, "show", "HEAD:marker.txt")

    assert observed == b"intended\n"
