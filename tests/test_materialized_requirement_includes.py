from __future__ import annotations

import importlib.metadata
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.ci import materialize_base_python_requirements as materializer


def _git(repo: Path, *args: str) -> str:
    """Run git in one isolated fixture repository and return stdout."""
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_materialized_relative_include_resolves_after_flattening(tmp_path: Path) -> None:
    """A bounded include must point at the generated child lock that pip can open."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@example.invalid")

    service = repo / "service"
    requirements = service / "requirements"
    requirements.mkdir(parents=True)
    pip_version = importlib.metadata.version("pip")
    (requirements / "ci.txt").write_text(
        f"pip=={pip_version} --hash=sha256:{'a' * 64}\n",
        encoding="utf-8",
    )
    (service / "requirements.txt").write_text(
        "-r requirements/ci.txt\n",
        encoding="utf-8",
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "base")
    base_sha = _git(repo, "rev-parse", "HEAD")

    output = tmp_path / "materialized"
    manifest = materializer.materialize(repo, base_sha, output)
    by_source = {entry["source"]: entry["file"] for entry in manifest}

    parent_name = by_source["service/requirements.txt"]
    child_name = by_source["service/requirements/ci.txt"]
    parent = output / parent_name
    child = output / child_name
    assert parent.read_text(encoding="utf-8") == f"-r {child_name}\n"
    assert child.is_file()

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--dry-run",
            "--no-index",
            "--disable-pip-version-check",
            "--require-hashes",
            "-r",
            str(parent),
        ],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "TERM": "dumb"},
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_materialized_include_rewrite_rejects_missing_target() -> None:
    """An accepted include cannot survive when its exact base target was not selected."""
    with pytest.raises(RuntimeError, match="could not be materialized"):
        materializer._rewrite_materialized_requirement_includes(
            "service/requirements.txt",
            b"-r requirements-missing.txt\n",
            {"service/requirements.txt": "requirements-000.txt"},
        )


def test_materialized_include_rewrite_rejects_non_utf8_lock() -> None:
    """Byte sequences that cannot be faithfully rewritten fail closed."""
    with pytest.raises(RuntimeError, match="not valid UTF-8"):
        materializer._rewrite_materialized_requirement_includes(
            "requirements.txt",
            b"\xff",
            {"requirements.txt": "requirements-000.txt"},
        )
