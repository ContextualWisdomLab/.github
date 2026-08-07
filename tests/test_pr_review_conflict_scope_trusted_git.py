"""Security regressions for trusted Git execution in conflict-scope checks."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from scripts.ci import pr_review_conflict_scope as scope


def _write_executable(path: Path, content: str) -> None:
    """Write one executable fixture without following symbolic links."""
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def test_git_inventory_ignores_a_path_hijacked_executable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Repository inventory must execute the trusted absolute Git binary."""
    trusted_git = scope._trusted_git_executable()
    root = tmp_path / "repository"
    root.mkdir()
    subprocess.run(
        [trusted_git, "-C", str(root), "init", "-q"],
        check=True,
        capture_output=True,
    )
    (root / "tracked.txt").write_text("tracked\n", encoding="utf-8")
    subprocess.run(
        [trusted_git, "-C", str(root), "add", "tracked.txt"],
        check=True,
        capture_output=True,
    )

    marker = tmp_path / "path-hijack-executed"
    hostile_bin = tmp_path / "hostile-bin"
    hostile_bin.mkdir()
    _write_executable(
        hostile_bin / "git",
        f"#!/bin/sh\n: > {marker}\nexit 0\n",
    )
    monkeypatch.setenv(
        "PATH",
        f"{hostile_bin}{os.pathsep}{os.environ.get('PATH', '')}",
    )

    assert scope._git_paths(root) == ("tracked.txt",)
    assert not marker.exists()


def test_git_resolver_rejects_an_executable_outside_trusted_directories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An executable found outside the fixed system directories is rejected."""
    hostile_bin = tmp_path / "hostile-bin"
    hostile_bin.mkdir()
    _write_executable(hostile_bin / "git", "#!/bin/sh\nexit 0\n")
    monkeypatch.setattr(scope, "_TRUSTED_GIT_SEARCH_PATH", str(hostile_bin))

    with pytest.raises(RuntimeError, match="trusted system directory"):
        scope._trusted_git_executable()
