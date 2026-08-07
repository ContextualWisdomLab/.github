"""Security contracts for trusted conflict-scope control-file placement.

The snapshot and conflict allowlist are security control-plane inputs. They must
remain outside the pull-request worktree so the review-repair model cannot edit
the evidence used to authorize or verify its own writes.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from scripts.ci import pr_review_conflict_scope as scope


def _git(root: Path, *arguments: str) -> None:
    """Run one deterministic Git command in a temporary fixture repository."""
    subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
    )


def _repository(tmp_path: Path) -> Path:
    """Create a minimal repository used to exercise trust-boundary checks."""
    root = tmp_path / "repository"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "tests@example.invalid")
    _git(root, "config", "user.name", "Tests")
    (root / "conflicted.txt").write_text("before\n", encoding="utf-8")
    _git(root, "add", "conflicted.txt")
    _git(root, "commit", "-q", "-m", "fixture")
    return root


def _allowed_file(path: Path) -> Path:
    """Write a valid NUL-delimited conflict allowlist for the fixture."""
    path.write_bytes(os.fsencode("conflicted.txt") + b"\0")
    return path


def test_snapshot_output_inside_repository_fails_closed(tmp_path: Path) -> None:
    """Snapshot evidence cannot be written into the model-writable worktree."""
    root = _repository(tmp_path)
    output = root / "control-snapshot.json"

    with pytest.raises(ValueError, match="outside the repository worktree"):
        scope.write_snapshot(root, output)

    assert not output.exists()


@pytest.mark.parametrize("control_name", ["snapshot", "allowed-paths"])
def test_verify_rejects_control_input_inside_repository(
    tmp_path: Path, control_name: str
) -> None:
    """Verification rejects either authoritative input when it is in-worktree."""
    root = _repository(tmp_path)
    snapshot = tmp_path / "snapshot.json"
    allowed = _allowed_file(tmp_path / "allowed.zlist")
    scope.write_snapshot(root, snapshot)

    if control_name == "snapshot":
        internal_snapshot = root / "control-snapshot.json"
        internal_snapshot.write_bytes(snapshot.read_bytes())
        snapshot = internal_snapshot
    else:
        internal_allowed = root / "control-allowed.zlist"
        internal_allowed.write_bytes(allowed.read_bytes())
        allowed = internal_allowed

    with pytest.raises(ValueError, match="outside the repository worktree"):
        scope.verify_snapshot(root, snapshot, allowed)


def test_verify_rejects_external_symlink_resolving_into_repository(
    tmp_path: Path,
) -> None:
    """An outside-looking symlink cannot redirect trusted evidence into the worktree."""
    root = _repository(tmp_path)
    snapshot = tmp_path / "snapshot.json"
    allowed = _allowed_file(tmp_path / "allowed.zlist")
    scope.write_snapshot(root, snapshot)

    internal_snapshot = root / "control-snapshot.json"
    internal_snapshot.write_bytes(snapshot.read_bytes())
    linked_snapshot = tmp_path / "linked-snapshot.json"
    linked_snapshot.symlink_to(internal_snapshot)

    with pytest.raises(ValueError, match="outside the repository worktree"):
        scope.verify_snapshot(root, linked_snapshot, allowed)
