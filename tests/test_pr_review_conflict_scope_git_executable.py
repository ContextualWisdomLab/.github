"""Security regressions for the conflict-scope Git executable boundary."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from scripts.ci import pr_review_conflict_scope as scope


def _repository(tmp_path: Path) -> Path:
    """Create one minimal repository through the trusted system Git binary."""
    root = tmp_path / "repository"
    root.mkdir()
    git = scope._trusted_git_executable()
    subprocess.run([git, "-C", str(root), "init", "-q"], check=True)
    (root / "tracked.txt").write_text("tracked\n", encoding="utf-8")
    subprocess.run([git, "-C", str(root), "add", "tracked.txt"], check=True)
    return root


def test_git_inventory_ignores_a_path_precedence_executable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A malicious executable named git on PATH cannot reach the subprocess sink."""
    root = _repository(tmp_path)
    attacker_directory = tmp_path / "attacker-bin"
    attacker_directory.mkdir()
    marker = tmp_path / "path-hijack-executed"
    malicious_git = attacker_directory / "git"
    malicious_git.write_text(
        f"#!/bin/sh\nprintf exploited > {marker}\nexit 99\n",
        encoding="utf-8",
    )
    malicious_git.chmod(0o755)
    monkeypatch.setenv("PATH", os.fspath(attacker_directory))

    assert scope._git_paths(root) == ("tracked.txt",)
    assert not marker.exists()


def test_relative_trusted_git_path_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The configured Git executable cannot be resolved relative to attacker state."""
    monkeypatch.setattr(scope, "_TRUSTED_GIT_EXECUTABLE", Path("git"))
    with pytest.raises(RuntimeError, match="must be absolute"):
        scope._trusted_git_executable()


def test_missing_trusted_git_path_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing fixed Git executable cannot fall back to PATH lookup."""
    monkeypatch.setattr(
        scope,
        "_TRUSTED_GIT_EXECUTABLE",
        tmp_path / "missing-git",
    )
    with pytest.raises(RuntimeError, match="unavailable"):
        scope._trusted_git_executable()


@pytest.mark.parametrize("candidate_kind", ["symlink", "non_executable"])
def test_untrusted_git_file_types_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    candidate_kind: str,
) -> None:
    """Symbolic links and non-executable files cannot become the Git authority."""
    candidate = tmp_path / "git"
    if candidate_kind == "symlink":
        target = tmp_path / "git-target"
        target.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        target.chmod(0o755)
        candidate.symlink_to(target)
    else:
        candidate.write_text("not executable\n", encoding="utf-8")
        candidate.chmod(0o644)
    monkeypatch.setattr(scope, "_TRUSTED_GIT_EXECUTABLE", candidate)

    with pytest.raises(RuntimeError, match="regular executable"):
        scope._trusted_git_executable()


@pytest.mark.parametrize("mode", [0o775, 0o757])
def test_writable_trusted_git_executable_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: int,
) -> None:
    """Group- or world-writable executables cannot become the Git authority."""
    candidate = tmp_path / "git"
    candidate.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    candidate.chmod(mode)
    monkeypatch.setattr(scope, "_TRUSTED_GIT_EXECUTABLE", candidate)

    with pytest.raises(RuntimeError, match="group- or world-writable"):
        scope._trusted_git_executable()
