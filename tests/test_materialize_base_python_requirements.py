from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.ci import materialize_base_python_requirements as materializer


def git(repo: Path, *args: str) -> str:
    """Run git in a temporary fixture repository."""
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_materializes_only_regular_hash_locks_from_exact_base(tmp_path: Path) -> None:
    """A PR-modified lock cannot enter the networked coverage image build context."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.invalid")

    backend = repo / "backend"
    backend.mkdir()
    (backend / "requirements-hashes.txt").write_text(
        "demo==1 --hash=sha256:" + ("a" * 64) + "\n",
        encoding="utf-8",
    )
    (backend / "requirements.txt").write_text("untrusted==1\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")
    base_sha = git(repo, "rev-parse", "HEAD")

    (backend / "requirements-hashes.txt").write_text(
        "changed==2 --hash=sha256:" + ("b" * 64) + "\n",
        encoding="utf-8",
    )
    git(repo, "add", ".")
    git(repo, "commit", "-m", "head")

    output = tmp_path / "output"
    manifest = materializer.materialize(repo, base_sha, output)

    assert manifest == [
        {
            "file": "requirements-000.txt",
            "source": "backend/requirements-hashes.txt",
        }
    ]
    assert (
        (output / "requirements-000.txt")
        .read_text(encoding="utf-8")
        .startswith("demo==1")
    )
    assert "requirements-000.txt\n" == (output / "manifest.txt").read_text(
        encoding="utf-8"
    )
    assert "requirements.txt" not in (output / "manifest.json").read_text(
        encoding="utf-8"
    )


def test_rejects_invalid_base_sha(tmp_path: Path) -> None:
    """Git options and symbolic refs cannot cross the exact-SHA boundary."""
    with pytest.raises(ValueError, match="40 hexadecimal"):
        materializer.base_hash_locks(tmp_path, "--help")
