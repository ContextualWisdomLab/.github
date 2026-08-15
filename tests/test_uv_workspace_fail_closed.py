"""Regression tests for fail-closed uv workspace materialization."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.ci import materialize_base_python_requirements as materializer


def _git(repo: Path, *args: str) -> str:
    """Run a git command in the fixture repository and return trimmed stdout."""
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _commit_uv_project(tmp_path: Path, pyproject_text: str) -> tuple[Path, str]:
    """Commit one root uv project and return its repository and exact base SHA."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@example.invalid")
    (repo / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    (repo / "pyproject.toml").write_text(pyproject_text, encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "base")
    return repo, _git(repo, "rev-parse", "HEAD")


def test_true_uv_workspace_fails_before_exporter_bootstrap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A partial workspace reconstruction cannot reach tool download or export."""
    repo, base_sha = _commit_uv_project(
        tmp_path,
        """[project]
name = "workspace-root"
version = "0"

[tool.uv.workspace]
members = ["packages/*"]
credential = "sk_live_should_not_be_logged"
""",
    )
    bootstrap_called = False

    def unexpected_bootstrap() -> str:
        nonlocal bootstrap_called
        bootstrap_called = True
        raise AssertionError("workspace rejection must precede trusted uv bootstrap")

    monkeypatch.setattr(materializer, "_install_trusted_uv", unexpected_bootstrap)

    with pytest.raises(
        RuntimeError,
        match=r"uv workspace.*not supported",
    ) as raised:
        materializer.materialize(repo, base_sha, tmp_path / "output")

    error_message = str(raised.value)
    assert "packages/*" not in error_message
    assert "sk_live_should_not_be_logged" not in error_message
    assert not bootstrap_called


def test_workspace_like_comment_is_not_a_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Detection uses parsed TOML structure rather than vulnerable text matching."""
    repo, base_sha = _commit_uv_project(
        tmp_path,
        """# [tool.uv.workspace]
[project]
name = "standalone"
version = "0"
""",
    )
    monkeypatch.setattr(materializer, "_install_trusted_uv", lambda: "/usr/bin/uv")
    hashed = b"dependency==1 --hash=sha256:" + (b"a" * 64) + b"\n"
    monkeypatch.setattr(
        materializer,
        "_run_uv_export",
        lambda _work, _uv_path: subprocess.CompletedProcess(
            ["uv", "export"], 0, hashed, b""
        ),
    )

    manifest = materializer.materialize(repo, base_sha, tmp_path / "output")

    assert manifest == [{"file": "requirements-000.txt", "source": "uv.lock"}]


def test_malformed_tracked_pyproject_fails_before_exporter_bootstrap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Malformed immutable-base metadata is diagnosed before any tool egress."""
    repo, base_sha = _commit_uv_project(
        tmp_path,
        "[project\nname = 'broken'\n",
    )
    bootstrap_called = False

    def unexpected_bootstrap() -> str:
        nonlocal bootstrap_called
        bootstrap_called = True
        raise AssertionError("metadata parsing must precede trusted uv bootstrap")

    monkeypatch.setattr(materializer, "_install_trusted_uv", unexpected_bootstrap)

    with pytest.raises(RuntimeError, match=r"could not parse.*pyproject\.toml"):
        materializer.materialize(repo, base_sha, tmp_path / "output")

    assert not bootstrap_called
