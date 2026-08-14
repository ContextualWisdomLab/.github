"""Regression coverage for nested requirements-directory lock discovery."""

from __future__ import annotations

import subprocess
from pathlib import Path

from scripts.ci import materialize_base_python_requirements as materializer


def _git(repo: Path, *args: str) -> str:
    """Run one Git command in the isolated fixture repository."""
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_base_hash_locks_discovers_direct_children_of_requirements_directories(
    tmp_path: Path,
) -> None:
    """Hash-pinned ``requirements/ci.txt`` files are trusted lock candidates."""
    repo = tmp_path / "repo"
    lock_directory = repo / "requirements"
    lock_directory.mkdir(parents=True)
    _git(repo, "init")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@example.invalid")

    lock_content = "demo==1 --hash=sha256:" + ("a" * 64) + "\n"
    (lock_directory / "ci.txt").write_text(lock_content, encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "base")
    base_sha = _git(repo, "rev-parse", "HEAD")

    assert materializer.base_hash_locks(repo, base_sha) == [
        ("requirements/ci.txt", lock_content.encode())
    ]
