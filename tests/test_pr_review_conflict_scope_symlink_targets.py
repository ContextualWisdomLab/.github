"""Security regressions for symlink targets in conflict-scope snapshots."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from scripts.ci import pr_review_conflict_scope as scope


def _git(root: Path, *arguments: str) -> None:
    """Run one fixture Git command through the fixed trusted executable."""
    subprocess.run(
        [scope._trusted_git_executable(), "-C", str(root), *arguments],
        check=True,
        capture_output=True,
    )


def _repository(tmp_path: Path) -> Path:
    """Create one minimal tracked repository for symlink-boundary tests."""
    root = tmp_path / "repository"
    root.mkdir()
    _git(root, "init", "-q")
    (root / "conflicted.txt").write_text("before\n", encoding="utf-8")
    (root / "stable.txt").write_text("stable\n", encoding="utf-8")
    _git(root, "add", "conflicted.txt", "stable.txt")
    return root


def _allowed_file(path: Path, *relative_paths: str) -> Path:
    """Write one authoritative NUL-delimited conflict-path inventory."""
    path.write_bytes(b"".join(os.fsencode(item) + b"\0" for item in relative_paths))
    return path


def test_repository_root_canonicalization_failure_is_redacted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Filesystem resolution failures do not expose platform-specific details."""
    root = _repository(tmp_path)

    def reject_resolution(_path: Path, *, strict: bool) -> Path:
        assert strict is True
        raise OSError("sensitive filesystem detail")

    monkeypatch.setattr(Path, "resolve", reject_resolution)

    with pytest.raises(ValueError, match="could not be canonicalized") as error:
        scope.build_snapshot(root)
    assert "sensitive filesystem detail" not in str(error.value)


def test_symlink_entry_metadata_failure_is_redacted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An uninspectable inventoried link fails closed without raw error detail."""
    root = _repository(tmp_path)
    linked_path = root / "linked.txt"
    os.symlink("stable.txt", linked_path)
    _git(root, "add", "linked.txt")
    original_lstat = os.lstat

    def reject_link_metadata(path: os.PathLike[str] | str) -> os.stat_result:
        if os.fspath(path) == os.fspath(linked_path):
            raise OSError("sensitive entry metadata detail")
        return original_lstat(path)

    monkeypatch.setattr(scope.os, "lstat", reject_link_metadata)

    with pytest.raises(ValueError, match="could not be inspected safely") as error:
        scope.build_snapshot(root)
    assert "sensitive entry metadata detail" not in str(error.value)


def test_snapshot_rejects_a_symlink_target_outside_the_repository(
    tmp_path: Path,
) -> None:
    """A tracked link cannot grant the repair model an external write path."""
    root = _repository(tmp_path)
    external = tmp_path / "external.txt"
    external.write_text("external\n", encoding="utf-8")
    os.symlink(external, root / "linked.txt")
    _git(root, "add", "linked.txt")

    with pytest.raises(ValueError, match="inside the repository"):
        scope.build_snapshot(root)


def test_snapshot_rejects_a_symlink_target_excluded_from_git_inventory(
    tmp_path: Path,
) -> None:
    """Ignored referents cannot hide writes from the authoritative inventory."""
    root = _repository(tmp_path)
    (root / ".gitignore").write_text("ignored-target.txt\n", encoding="utf-8")
    (root / "ignored-target.txt").write_text("ignored\n", encoding="utf-8")
    os.symlink("ignored-target.txt", root / "linked.txt")
    _git(root, "add", ".gitignore", "linked.txt")

    with pytest.raises(ValueError, match="Git inventory"):
        scope.build_snapshot(root)


def test_snapshot_rejects_a_dangling_symlink(tmp_path: Path) -> None:
    """Dangling links cannot become deferred writes outside the snapshot."""
    root = _repository(tmp_path)
    os.symlink("missing-target.txt", root / "linked.txt")
    _git(root, "add", "linked.txt")

    with pytest.raises(ValueError, match="regular file"):
        scope.build_snapshot(root)


def test_snapshot_rejects_a_symlink_to_a_directory(tmp_path: Path) -> None:
    """Directory links cannot expose an unbounded tree to the repair model."""
    root = _repository(tmp_path)
    (root / "target-directory").mkdir()
    os.symlink("target-directory", root / "linked-directory")
    _git(root, "add", "linked-directory")

    with pytest.raises(ValueError, match="regular file"):
        scope.build_snapshot(root)


def test_symlink_target_metadata_failure_is_redacted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A target disappearing during validation fails closed without raw detail."""
    root = _repository(tmp_path)
    target = root / "z-target.txt"
    target.write_text("target\n", encoding="utf-8")
    os.symlink("z-target.txt", root / "linked.txt")
    _git(root, "add", "linked.txt", "z-target.txt")
    original_lstat = Path.lstat

    def reject_target_metadata(path: Path) -> os.stat_result:
        if path == target:
            raise OSError("sensitive race detail")
        return original_lstat(path)

    monkeypatch.setattr(Path, "lstat", reject_target_metadata)

    with pytest.raises(ValueError, match="regular file") as error:
        scope.build_snapshot(root)
    assert "sensitive race detail" not in str(error.value)


def test_verify_rejects_an_allowed_path_replaced_by_an_external_symlink(
    tmp_path: Path,
) -> None:
    """Conflict authorization never permits introducing an external link."""
    root = _repository(tmp_path)
    snapshot = tmp_path / "snapshot.json"
    allowed = _allowed_file(tmp_path / "allowed.zlist", "conflicted.txt")
    scope.write_snapshot(root, snapshot)
    external = tmp_path / "external.txt"
    external.write_text("external\n", encoding="utf-8")
    (root / "conflicted.txt").unlink()
    os.symlink(external, root / "conflicted.txt")

    with pytest.raises(ValueError, match="inside the repository"):
        scope.verify_snapshot(root, snapshot, allowed)


def test_write_through_a_safe_tracked_symlink_is_detected(tmp_path: Path) -> None:
    """Writing through a safe link still changes its separately tracked referent."""
    root = _repository(tmp_path)
    os.symlink("stable.txt", root / "linked.txt")
    _git(root, "add", "linked.txt")
    snapshot = tmp_path / "snapshot.json"
    allowed = _allowed_file(tmp_path / "allowed.zlist", "conflicted.txt")
    scope.write_snapshot(root, snapshot)

    (root / "linked.txt").write_text("changed-through-link\n", encoding="utf-8")

    assert scope.verify_snapshot(root, snapshot, allowed) == ("stable.txt",)
