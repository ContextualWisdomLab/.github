from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.ci import materialize_base_python_locks as locks


VALID_LOCK = b"""\
# Generated lock
fastapi==0.139.0 \\
    --hash=sha256:cf15e1e9e667ddb0ad63811e60bd11390d1aac838ca4a7a23f421807b2308189
pytest==9.1.1 \\
    --hash=sha256:37a86b45efb9a47a61a36449063e8e18d0cab3161329fc099eb21783169c4f0c
"""


def git(repo: Path, *args: str) -> str:
    """Run a test-only Git command."""
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()


def committed_repo(tmp_path: Path) -> tuple[Path, str]:
    """Create a repository containing one base-controlled hashed lock."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.com")
    backend = repo / "backend"
    backend.mkdir()
    (backend / "requirements-hashes.txt").write_bytes(VALID_LOCK)
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base lock")
    return repo, git(repo, "rev-parse", "HEAD")


def test_materializes_only_exact_base_lock_with_provenance(tmp_path: Path):
    """The current worktree cannot replace dependency evidence from the base SHA."""
    repo, base_sha = committed_repo(tmp_path)
    (repo / "backend" / "requirements-hashes.txt").write_text(
        "malware @ https://example.invalid/malware.whl\n",
        encoding="utf-8",
    )

    output = tmp_path / "locks"
    metadata = locks.materialize(repo, base_sha, output)

    assert metadata["base_sha"] == base_sha
    assert (output / "lock-000.txt").read_bytes() == VALID_LOCK
    assert (output / "manifest.tsv").read_text() == (
        "backend\tlock-000\tlock-000.txt\n"
    )
    assert metadata["locks"][0]["path"] == "backend/requirements-hashes.txt"


@pytest.mark.parametrize(
    "content",
    [
        b"fastapi>=0.139.0 --hash=sha256:" + b"a" * 64 + b"\n",
        b"fastapi==0.139.0\n",
        b"--index-url https://example.invalid/simple\n",
        b"pkg @ https://example.invalid/pkg.whl --hash=sha256:" + b"a" * 64 + b"\n",
        b"-r nested.txt\n",
    ],
)
def test_rejects_mutable_or_redirecting_requirement_records(content: bytes):
    """Only exact pins with hashes may enter the networked image build."""
    with pytest.raises(ValueError, match="only pinned package records"):
        locks.validate_lock_content(content)


def test_rejects_symlink_lock_entry():
    """A base-tree symlink cannot redirect dependency materialization."""
    tree = (
        b"120000 blob 0123456789012345678901234567890123456789 9\t"
        b"backend/requirements-hashes.txt\0"
    )
    with pytest.raises(ValueError, match="must be a regular file"):
        locks.parse_lock_entries(tree)
