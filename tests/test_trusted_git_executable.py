"""Security regressions for the trusted Git executable boundary."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from scripts.ci import materialize_base_python_requirements as materializer


@dataclass(frozen=True)
class _CompletedGitCommand:
    """Provide the bounded subprocess result consumed by the materializer."""

    returncode: int = 0
    stdout: bytes = b"trusted-output"
    stderr: bytes = b""


def test_git_ignores_process_path_and_uses_absolute_default_path_executable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A pull-request-controlled PATH entry cannot select the Git executable."""

    malicious_directory = tmp_path / "malicious-bin"
    malicious_directory.mkdir()
    monkeypatch.setenv("PATH", str(malicious_directory))
    materializer._trusted_git_executable.cache_clear()

    which_calls: list[tuple[str, str | None]] = []
    subprocess_calls: list[tuple[list[str], dict[str, Any]]] = []

    def fake_which(command: str, *, path: str | None = None) -> str:
        which_calls.append((command, path))
        return "/usr/bin/git"

    def fake_run(
        command: list[str],
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[bytes]:
        subprocess_calls.append((command, kwargs))
        return _CompletedGitCommand()  # type: ignore[return-value]

    monkeypatch.setattr(materializer.shutil, "which", fake_which)
    monkeypatch.setattr(materializer.subprocess, "run", fake_run)

    assert materializer._git(tmp_path, "status", "--porcelain") == b"trusted-output"
    assert which_calls == [("git", os.defpath)]
    assert subprocess_calls[0][0] == [
        "/usr/bin/git",
        "-C",
        str(tmp_path),
        "status",
        "--porcelain",
    ]


@pytest.mark.parametrize("resolved_git", [None, "git"])
def test_git_fails_closed_when_default_path_has_no_absolute_executable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    resolved_git: str | None,
) -> None:
    """Missing or relative Git resolution cannot fall back to the process PATH."""

    materializer._trusted_git_executable.cache_clear()
    monkeypatch.setattr(
        materializer.shutil,
        "which",
        lambda _command, *, path=None: resolved_git,
    )

    def unexpected_run(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("an untrusted Git command must never execute")

    monkeypatch.setattr(materializer.subprocess, "run", unexpected_run)

    with pytest.raises(RuntimeError, match="trusted Git executable"):
        materializer._git(tmp_path, "status", "--porcelain")
