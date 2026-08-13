"""Regression contracts for trusted locks kept in a requirements directory."""

from __future__ import annotations

import subprocess
from pathlib import Path, PurePosixPath

import pytest

from scripts.ci import materialize_base_python_requirements as materializer


def _git(repo: Path, *args: str) -> str:
    """Run one deterministic Git command in a temporary fixture repository."""
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_requirements_directory_txt_is_a_candidate_lock_path() -> None:
    """A direct ``requirements/*.txt`` lock is discoverable by its safe path."""
    assert materializer._is_candidate_lock_path(PurePosixPath("requirements/ci.txt"))
    assert materializer._is_candidate_lock_path(
        PurePosixPath("services/scoring_service/requirements/package.txt")
    )
    assert not materializer._is_candidate_lock_path(
        PurePosixPath("requirements/nested/ci.txt")
    )
    assert not materializer._is_candidate_lock_path(PurePosixPath("docs/ci.txt"))


def test_materializes_hash_pinned_requirements_directory_lock(
    tmp_path: Path,
) -> None:
    """The exact base ``requirements/ci.txt`` closure reaches offline coverage."""
    repo = tmp_path / "repo"
    requirements_dir = repo / "requirements"
    requirements_dir.mkdir(parents=True)
    _git(repo, "init")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@example.invalid")

    (requirements_dir / "ci.txt").write_text(
        "numpy==2.5.1 --hash=sha256:" + ("a" * 64) + "\n",
        encoding="utf-8",
    )
    (requirements_dir / "ci.in").write_text("numpy>=2\n", encoding="utf-8")
    (requirements_dir / "notes.txt").write_text(
        "human-readable notes only\n", encoding="utf-8"
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "base")
    base_sha = _git(repo, "rev-parse", "HEAD")

    output = tmp_path / "output"
    manifest = materializer.materialize(repo, base_sha, output)

    assert manifest == [
        {"file": "requirements-000.txt", "source": "requirements/ci.txt"}
    ]
    assert (output / "requirements-000.txt").read_text(encoding="utf-8").startswith(
        "numpy==2.5.1"
    )


@pytest.mark.parametrize(
    ("content", "expected"),
    (
        (b"--require-hashes\n", False),
        (b"--require-hashes\ndemo==1\n", False),
        (
            b"--require-hashes\ndemo==1 --hash=sha256:"
            + (b"a" * 64)
            + b"\n",
            True,
        ),
        (
            b"pinned==1 --hash=sha256:"
            + (b"b" * 64)
            + b"\nunpinned==2\n",
            False,
        ),
        (b"--index-url https://packages.example.invalid/simple\n", False),
        (b"--requirement requirements-other.txt\n", True),
        (b"-r requirements/other.txt\n", True),
        (b"--requirement other.txt\n", False),
        (b"-r ./locks/other.txt\n", False),
        (b"-r ./requirements/other.txt\n", False),
        (b"-r requirements/./other.txt\n", False),
        (b"-r requirements//other.txt\n", False),
    ),
)
def test_global_hash_directive_does_not_replace_per_requirement_trust(
    content: bytes,
    expected: bool,
) -> None:
    """Only substantive hashed pins or bounded requirement includes qualify."""
    assert materializer._is_hash_pinned(content) is expected


@pytest.mark.parametrize(
    "unsafe_content",
    (
        b"demo>=1 --hash=sha256:" + (b"a" * 64) + b"\n",
        b"demo==1 --hash=sha256:not-a-complete-digest\n",
        b"--index-url https://packages.example.invalid/simple --hash=sha256:"
        + (b"a" * 64)
        + b"\n",
        b"-r /tmp/absolute.txt\n",
        b"--requirement ../parent.txt\n",
        b"-r nested/../../escape.txt\n",
        b"--requirement other.txt --hash=sha256:" + (b"a" * 64) + b"\n",
        b"--requirement https://packages.example.invalid/lock.txt\n",
        b"--requirement ~/private-lock.txt\n",
        b"--requirement -option-like.txt\n",
        b"--requirement locks\\windows.txt\n",
        b"--requirement other.txt?variant=1\n",
        b"--requirement other.txt#fragment\n",
    ),
)
def test_unsafe_requirement_lines_are_rejected_before_materialization(
    unsafe_content: bytes,
) -> None:
    """Unsafe package and include syntax never gains trusted candidate status."""
    assert not materializer._is_hash_pinned(unsafe_content)


@pytest.mark.parametrize(
    "unsafe_text",
    (
        "demo>=1 --hash=sha256:" + ("a" * 64) + "\n",
        "demo==1 --hash=sha256:not-a-complete-digest\n",
        "--index-url https://packages.example.invalid/simple --hash=sha256:"
        + ("a" * 64)
        + "\n",
        "-r /tmp/absolute.txt\n",
        "--requirement ../parent.txt\n",
        "--requirement https://packages.example.invalid/lock.txt\n",
    ),
)
def test_unsafe_requirements_directory_candidate_is_excluded_from_manifest(
    tmp_path: Path,
    unsafe_text: str,
) -> None:
    """Unsafe direct-child content is excluded before entering the build context."""
    repo = tmp_path / "repo"
    requirements_dir = repo / "requirements"
    requirements_dir.mkdir(parents=True)
    _git(repo, "init")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@example.invalid")
    (requirements_dir / "ci.txt").write_text(unsafe_text, encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "base")
    base_sha = _git(repo, "rev-parse", "HEAD")

    output = tmp_path / "output"
    manifest = materializer.materialize(repo, base_sha, output)

    assert manifest == []
    assert (output / "manifest.json").read_text(encoding="utf-8") == "[]\n"


def test_rejects_global_hash_directive_with_unpinned_requirement(
    tmp_path: Path,
) -> None:
    """A global directive cannot make an unpinned direct-child lock trusted."""
    repo = tmp_path / "repo"
    requirements_dir = repo / "requirements"
    requirements_dir.mkdir(parents=True)
    _git(repo, "init")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@example.invalid")

    (requirements_dir / "ci.txt").write_text(
        "--require-hashes\ndemo==1\n",
        encoding="utf-8",
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "base")
    base_sha = _git(repo, "rev-parse", "HEAD")

    output = tmp_path / "output"
    manifest = materializer.materialize(repo, base_sha, output)

    assert manifest == []
    assert not materializer._is_hash_pinned(b"--require-hashes\ndemo==1\n")
    assert (output / "manifest.json").read_text(encoding="utf-8") == "[]\n"
