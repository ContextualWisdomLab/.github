from __future__ import annotations

import json
import os
import runpy
import subprocess
import sys
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


def test_parse_args_accepts_exact_sha_and_rejects_malformed_sha(tmp_path: Path):
    """CLI parsing binds materialization to one exact hexadecimal commit."""
    sha = "a" * 40
    args = locks.parse_args(
        [
            "--repo-root",
            str(tmp_path),
            "--base-sha",
            sha,
            "--output-dir",
            str(tmp_path / "output"),
        ]
    )
    assert args.base_sha == sha

    with pytest.raises(SystemExit):
        locks.parse_args(
            [
                "--repo-root",
                str(tmp_path),
                "--base-sha",
                "main",
                "--output-dir",
                str(tmp_path / "output"),
            ]
        )


def test_git_bytes_reports_failures_and_bounds_output(monkeypatch, tmp_path: Path):
    """Git reads expose stderr and refuse unexpectedly large output."""
    monkeypatch.setattr(
        locks.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 1, stdout=b"", stderr=b"missing commit"
        ),
    )
    with pytest.raises(RuntimeError, match="missing commit"):
        locks.git_bytes(tmp_path, "rev-parse", "HEAD")

    monkeypatch.setattr(locks, "MAX_TREE_OUTPUT_BYTES", 1)
    monkeypatch.setattr(
        locks.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 0, stdout=b"ab", stderr=b""
        ),
    )
    with pytest.raises(ValueError, match="bounded materialization"):
        locks.git_bytes(tmp_path, "ls-tree", "HEAD")


def test_git_bytes_requires_an_absolute_verified_executable(monkeypatch, tmp_path: Path):
    """Dependency materialization cannot resolve Git through a mutable relative PATH."""
    monkeypatch.setattr(locks, "GIT_EXECUTABLE", "git")
    with pytest.raises(RuntimeError, match="absolute Git executable"):
        locks.git_bytes(tmp_path, "rev-parse", "HEAD")


def test_write_exclusive_closes_descriptor_when_fdopen_fails(
    monkeypatch,
    tmp_path: Path,
):
    """A failed stream wrapper cannot leak the exclusive output descriptor."""
    closed: list[int] = []
    real_close = os.close

    def recording_close(descriptor: int) -> None:
        closed.append(descriptor)
        real_close(descriptor)

    monkeypatch.setattr(locks.os, "close", recording_close)
    monkeypatch.setattr(
        locks.os,
        "fdopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("fdopen failed")),
    )

    with pytest.raises(OSError, match="fdopen failed"):
        locks.write_exclusive(tmp_path / "lock.txt", b"data")
    assert len(closed) == 1


def test_repository_and_output_paths_fail_closed(monkeypatch, tmp_path: Path):
    """Repository identity, existing outputs, and symlink ancestors are rejected."""
    not_directory = tmp_path / "repo-file"
    not_directory.write_text("not a repository", encoding="utf-8")
    with pytest.raises(ValueError, match="resolve to a directory"):
        locks.validate_repo_root(not_directory, "a" * 40)

    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(locks, "git_bytes", lambda *args: ("b" * 40).encode())
    with pytest.raises(ValueError, match="exact requested commit"):
        locks.validate_repo_root(repo, "a" * 40)

    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(ValueError, match="must not already exist"):
        locks.safe_output_dir(existing)

    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError, match="symbolic-link component"):
        locks.safe_output_dir(link / "locks")


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (b"pkg==1.0 \\\n", "incomplete continuation"),
        (b"\xff", "must be UTF-8"),
        (b"pkg==1.0\x00 --hash=sha256:" + b"a" * 64, "contains a NUL"),
        (b"# comments only\n", "no package records"),
    ],
)
def test_lock_content_rejects_encoding_and_record_boundaries(
    content: bytes, message: str
):
    """Malformed, empty, and unterminated lock records cannot reach pip."""
    with pytest.raises(ValueError, match=message):
        locks.validate_lock_content(content)


def test_lock_content_rejects_per_file_size_limit(monkeypatch):
    """A single base lock cannot exceed its explicit byte budget."""
    monkeypatch.setattr(locks, "MAX_LOCK_BYTES", 1)
    with pytest.raises(ValueError, match="per-lock size limit"):
        locks.validate_lock_content(b"ab")


def tree_record(path: str, *, size: str = "1", mode: str = "100644") -> bytes:
    """Build one NUL-delimited ls-tree fixture record."""
    oid = "1" * 40
    return f"{mode} blob {oid} {size}\t{path}\0".encode()


def test_tree_parser_rejects_malformed_and_unsafe_entries(monkeypatch):
    """Only bounded regular requirement locks at safe paths are selected."""
    with pytest.raises(ValueError, match="could not parse"):
        locks.parse_lock_entries(b"malformed\0")
    assert locks.parse_lock_entries(tree_record("README.md")) == []

    with pytest.raises(ValueError, match="path or size is unsafe"):
        locks.parse_lock_entries(tree_record("../requirements-hashes.txt"))
    with pytest.raises(ValueError, match="path or size is unsafe"):
        locks.parse_lock_entries(tree_record("requirements-hashes.txt", size="nan"))

    monkeypatch.setattr(locks, "MAX_LOCK_BYTES", 0)
    with pytest.raises(ValueError, match="file is too large"):
        locks.parse_lock_entries(tree_record("requirements-hashes.txt"))


def test_tree_parser_enforces_aggregate_and_count_limits(monkeypatch):
    """Multiple individually valid locks remain bounded as one materialization."""
    tree = tree_record("a/requirements-hashes.txt", size="2") + tree_record(
        "b/requirements-hashes.txt", size="2"
    )
    monkeypatch.setattr(locks, "MAX_TOTAL_BYTES", 3)
    with pytest.raises(ValueError, match="aggregate size limit"):
        locks.parse_lock_entries(tree)

    monkeypatch.setattr(locks, "MAX_TOTAL_BYTES", 100)
    monkeypatch.setattr(locks, "MAX_LOCKS", 0)
    with pytest.raises(ValueError, match="too many"):
        locks.parse_lock_entries(tree_record("requirements-hashes.txt"))


def test_materialize_rejects_blob_size_change(monkeypatch, tmp_path: Path):
    """A blob differing from its validated tree size fails before any install."""
    output = tmp_path / "output"
    monkeypatch.setattr(locks, "validate_repo_root", lambda repo, sha: tmp_path)
    monkeypatch.setattr(locks, "safe_output_dir", lambda path: output)

    def fake_git_bytes(repo, *args):
        if args[0] == "ls-tree":
            return tree_record("requirements-hashes.txt", size="2")
        return b"x"

    monkeypatch.setattr(locks, "git_bytes", fake_git_bytes)
    with pytest.raises(RuntimeError, match="blob size changed"):
        locks.materialize(tmp_path, "a" * 40, output)


def test_materializes_repository_root_lock(tmp_path: Path):
    """A lock at repository root is represented by the manifest dot project."""
    repo, _ = committed_repo(tmp_path)
    (repo / "backend" / "requirements-hashes.txt").unlink()
    (repo / "requirements-hashes.txt").write_bytes(VALID_LOCK)
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "move lock to root")
    base_sha = git(repo, "rev-parse", "HEAD")
    output = tmp_path / "root-locks"

    locks.materialize(repo, base_sha, output)

    assert (output / "manifest.tsv").read_text() == ".\tlock-000\tlock-000.txt\n"


def test_main_reports_success_and_materialization_failure(
    monkeypatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    """The CLI emits machine-readable metadata and a visible failure reason."""
    sha = "a" * 40
    argv = [
        "--repo-root",
        str(tmp_path),
        "--base-sha",
        sha,
        "--output-dir",
        str(tmp_path / "output"),
    ]
    monkeypatch.setattr(locks, "materialize", lambda *args: {"schema": 1})
    assert locks.main(argv) == 0
    assert json.loads(capsys.readouterr().out) == {"schema": 1}

    monkeypatch.setattr(
        locks,
        "materialize",
        lambda *args: (_ for _ in ()).throw(ValueError("unsafe lock")),
    )
    assert locks.main(argv) == 1
    assert "unsafe lock" in capsys.readouterr().err

    monkeypatch.setattr(sys, "argv", ["materialize_base_python_locks.py", *argv])
    assert locks.main() == 1


def test_materializer_dunder_entrypoint(tmp_path: Path, monkeypatch):
    """Executing the helper as a script exits with the main return code."""
    repo, base_sha = committed_repo(tmp_path)
    output = tmp_path / "script-locks"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "materialize_base_python_locks.py",
            "--repo-root",
            str(repo),
            "--base-sha",
            base_sha,
            "--output-dir",
            str(output),
        ],
    )
    with pytest.raises(SystemExit) as exc:
        runpy.run_path("scripts/ci/materialize_base_python_locks.py", run_name="__main__")
    assert exc.value.code == 0
