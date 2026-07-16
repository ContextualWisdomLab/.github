"""Tests for inert pull-request source materialization."""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import subprocess

from scripts.ci import materialize_pr_review_source as materializer


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "ci" / "materialize_pr_review_source.py"


def git(repo: Path, *args: str) -> str:
    """Run Git in a test repository and return stdout."""
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def build_repository(tmp_path: Path) -> tuple[Path, Path, str, str]:
    """Create a work repository and an isolated bare clone."""
    work = tmp_path / "work"
    work.mkdir()
    git(work, "init", "--quiet")
    git(work, "config", "user.name", "test")
    git(work, "config", "user.email", "test@example.com")
    (work / "README.md").write_text("base\n", encoding="utf-8")
    git(work, "add", "README.md")
    git(work, "commit", "--quiet", "-m", "base fixture")
    base_sha = git(work, "rev-parse", "HEAD")
    (work / "src").mkdir()
    (work / "src" / "app.py").write_text("print('review data')\n", encoding="utf-8")
    executable = work / "run.sh"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o755)
    os.symlink("src/app.py", work / "app-link")
    (work / ".codegraph").mkdir()
    (work / ".codegraph" / "config.json").write_text(
        '{"untrusted": true}\n', encoding="utf-8"
    )
    git(work, "add", ".")
    git(work, "commit", "--quiet", "-m", "fixture")
    head_sha = git(work, "rev-parse", "HEAD")
    bare = tmp_path / "objects.git"
    subprocess.run(
        ["git", "clone", "--quiet", "--bare", str(work), str(bare)],
        check=True,
    )
    return work, bare, base_sha, head_sha


def test_materializes_only_inert_validated_blobs(tmp_path: Path) -> None:
    """Executable, symlink, and CodeGraph-controlled paths stay inert."""
    _work, bare, base_sha, head_sha = build_repository(tmp_path)
    source = tmp_path / "source"
    manifest = tmp_path / "manifest.json"

    completed = subprocess.run(
        [
            "python3",
            str(SCRIPT),
            "--git-dir",
            str(bare),
            "--head-sha",
            head_sha,
            "--output-dir",
            str(source),
            "--manifest",
            str(manifest),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert (source / "src" / "app.py").read_text(
        encoding="utf-8"
    ) == "print('review data')\n"
    assert stat.S_IMODE((source / "run.sh").stat().st_mode) == 0o444
    assert not (source / "app-link").is_symlink()
    assert (source / "app-link").read_text(encoding="utf-8") == "src/app.py"
    assert not (source / ".codegraph").exists()
    assert (source / ".git").is_file()
    assert git(source, "rev-parse", "HEAD") == head_sha
    assert git(source, "merge-base", base_sha, head_sha) == base_sha
    assert set(git(source, "diff", "--name-only", base_sha, head_sha).splitlines()) == {
        ".codegraph/config.json",
        "app-link",
        "run.sh",
        "src/app.py",
    }

    evidence = json.loads(manifest.read_text(encoding="utf-8"))
    assert evidence["head_sha"] == head_sha
    assert evidence["written_files"] == 4
    assert {entry["path"] for entry in evidence["skipped"]} == {
        ".codegraph/config.json"
    }
    representations = {
        entry["path"]: entry["representation"]
        for entry in evidence["special_representations"]
    }
    assert representations == {
        "app-link": "inert-regular-file",
        "run.sh": "non-executable-regular-file",
    }


def test_rejects_non_bare_git_directory(tmp_path: Path) -> None:
    """A normal work repository cannot be confused with the object store."""
    work, _bare, _base_sha, head_sha = build_repository(tmp_path)
    args = materializer.parse_args(
        [
            "--git-dir",
            str(work / ".git"),
            "--head-sha",
            head_sha,
            "--output-dir",
            str(tmp_path / "source"),
            "--manifest",
            str(tmp_path / "manifest.json"),
        ]
    )

    try:
        materializer.materialize(args)
    except ValueError as exc:
        assert "isolated bare repository" in str(exc)
    else:
        raise AssertionError("non-bare repository was accepted")


def test_rejects_unsafe_tree_paths() -> None:
    """Traversal and absolute paths fail closed before filesystem writes."""
    for unsafe in (b"../escape", b"/absolute", b"a/../escape"):
        try:
            materializer.safe_relative_path(unsafe)
        except ValueError:
            continue
        raise AssertionError(f"unsafe path was accepted: {unsafe!r}")
