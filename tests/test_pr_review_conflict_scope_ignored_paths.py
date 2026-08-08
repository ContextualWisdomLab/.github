"""Regression tests for ignored worktree paths in conflict-repair scope."""

from __future__ import annotations

import subprocess
from pathlib import Path

from scripts.ci import pr_review_conflict_scope as scope


def _git(root: Path, *arguments: str) -> None:
    """Run one deterministic Git command in a temporary fixture repository."""
    subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
    )


def _repository(tmp_path: Path) -> Path:
    """Create a repository with one conflict path and an ignored namespace."""
    root = tmp_path / "repository"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "tests@example.invalid")
    _git(root, "config", "user.name", "Tests")
    (root / ".gitignore").write_text("private.env\nignored-output/\n", encoding="utf-8")
    (root / "conflicted.txt").write_text("conflict-before\n", encoding="utf-8")
    (root / "private.env").write_text("before\n", encoding="utf-8")
    _git(root, "add", ".gitignore", "conflicted.txt")
    _git(root, "commit", "-q", "-m", "fixture")
    return root


def _allowed_file(path: Path) -> Path:
    """Write the exact NUL-delimited conflict-path allowlist."""
    path.write_bytes(b"conflicted.txt\0")
    return path


def test_existing_ignored_file_change_is_out_of_scope(tmp_path: Path) -> None:
    """An ignored file present before model execution must remain immutable."""
    root = _repository(tmp_path)
    snapshot = tmp_path / "snapshot.json"
    allowed = _allowed_file(tmp_path / "allowed.zlist")
    scope.write_snapshot(root, snapshot)

    (root / "private.env").write_text("model-changed\n", encoding="utf-8")

    assert scope.verify_snapshot(root, snapshot, allowed) == ("private.env",)


def test_new_ignored_file_creation_is_out_of_scope(tmp_path: Path) -> None:
    """A model-created ignored path must not evade the conflict allowlist."""
    root = _repository(tmp_path)
    snapshot = tmp_path / "snapshot.json"
    allowed = _allowed_file(tmp_path / "allowed.zlist")
    scope.write_snapshot(root, snapshot)

    ignored_output = root / "ignored-output"
    ignored_output.mkdir()
    (ignored_output / "model.txt").write_text("created\n", encoding="utf-8")

    assert scope.verify_snapshot(root, snapshot, allowed) == (
        "ignored-output/model.txt",
    )
