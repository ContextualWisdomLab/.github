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


@pytest.mark.parametrize(
    "candidate_kind, error_pattern",
    [
        ("relative", "must be absolute"),
        ("missing", "is unavailable"),
        ("directory", "regular executable"),
        ("non_executable", "regular executable"),
        ("symlink", "regular executable"),
    ],
)
def test_trusted_git_executable_validation_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    candidate_kind: str,
    error_pattern: str,
) -> None:
    """Only the fixed absolute regular executable can enumerate repository paths."""
    if candidate_kind == "relative":
        candidate = Path("git")
    elif candidate_kind == "missing":
        candidate = tmp_path / "missing-git"
    elif candidate_kind == "directory":
        candidate = tmp_path / "git-directory"
        candidate.mkdir()
    elif candidate_kind == "non_executable":
        candidate = tmp_path / "git-file"
        candidate.write_text("not executable\n", encoding="utf-8")
        candidate.chmod(0o644)
    else:
        target = tmp_path / "git-target"
        _write_executable(target, "#!/bin/sh\nexit 0\n")
        candidate = tmp_path / "git-link"
        candidate.symlink_to(target)

    monkeypatch.setattr(scope, "_TRUSTED_GIT_EXECUTABLE", candidate)

    with pytest.raises(RuntimeError, match=error_pattern):
        scope._trusted_git_executable()
