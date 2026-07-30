from __future__ import annotations

import runpy
import subprocess
import sys
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
    (repo / "requirements.lock").write_text(
        "locked==1 --hash=sha256:" + ("c" * 64) + "\n",
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
    (repo / "requirements.lock").write_text(
        "changed==2 --hash=sha256:" + ("d" * 64) + "\n",
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
        },
        {"file": "requirements-001.txt", "source": "requirements.lock"},
    ]
    assert (
        (output / "requirements-000.txt")
        .read_text(encoding="utf-8")
        .startswith("demo==1")
    )
    assert "requirements-000.txt\nrequirements-001.txt\n" == (
        output / "manifest.txt"
    ).read_text(encoding="utf-8")
    assert (
        (output / "requirements-001.txt")
        .read_text(encoding="utf-8")
        .startswith("locked==1")
    )
    assert "requirements.txt" not in (output / "manifest.json").read_text(
        encoding="utf-8"
    )


def test_materializes_hash_pinned_locks_named_beyond_the_legacy_whitelist(
    tmp_path: Path,
) -> None:
    """Hash-pinned locks in service subdirs and dev/test files are materialized.

    Discovery is content-based: a hash-pinned ``requirements-dev.txt`` under a
    service directory and a hash-pinned ``requirements-test.txt`` are installed
    for offline coverage, while a non-requirements ``uv.lock`` (excluded by name)
    and an unpinned ``requirements-extra.txt`` (excluded by content) are not.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.invalid")

    service = repo / "services" / "account_unification"
    service.mkdir(parents=True)
    (service / "requirements-dev.txt").write_text(
        "fastapi==1 --hash=sha256:" + ("a" * 64) + "\n",
        encoding="utf-8",
    )
    (repo / "requirements-test.txt").write_text(
        "hypothesis==6 --hash=sha256:" + ("b" * 64) + "\n",
        encoding="utf-8",
    )
    (repo / "uv.lock").write_text(
        "version = 1\n[[package]]\nname = 'x'\n", encoding="utf-8"
    )
    (repo / "requirements-extra.txt").write_text("unpinned==1\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")
    base_sha = git(repo, "rev-parse", "HEAD")

    output = tmp_path / "output"
    manifest = materializer.materialize(repo, base_sha, output)

    assert [entry["source"] for entry in manifest] == [
        "requirements-test.txt",
        "services/account_unification/requirements-dev.txt",
    ]


def test_lock_name_candidates_are_pip_requirements_files() -> None:
    """Requirements files and requirements.lock are candidates; other names are not."""
    assert materializer._is_candidate_lock_name("requirements.lock")
    assert materializer._is_candidate_lock_name("requirements-dev.txt")
    assert materializer._is_candidate_lock_name("requirements.txt")
    assert not materializer._is_candidate_lock_name(
        "requirements-opencode-review-ci-hashes.txt"
    )
    assert not materializer._is_candidate_lock_name("uv.lock")
    assert not materializer._is_candidate_lock_name("pyproject.toml")


def test_hash_pin_detection_includes_pinned_and_excludes_unpinned_or_empty() -> None:
    """Only fully hash-pinned, non-empty lock content is materialized."""
    assert not materializer._is_hash_pinned(b"# comment only\n\n")
    assert materializer._is_hash_pinned(b"--require-hashes\ndemo==1\n")
    assert materializer._is_hash_pinned(b"demo==1 --hash=sha256:" + b"a" * 64 + b"\n")
    assert materializer._is_hash_pinned(b"-r other-hashes.txt\n")
    assert not materializer._is_hash_pinned(b"untrusted==1\n")
    # uv export / pip-compile multi-line continuation format (spec, then --hash= lines).
    assert materializer._is_hash_pinned(
        b"foo==1 \\\n    --hash=sha256:"
        + b"a" * 64
        + b" \\\n    --hash=sha256:"
        + b"b" * 64
        + b"\n"
    )


def test_rejects_invalid_base_sha(tmp_path: Path) -> None:
    """Git options and symbolic refs cannot cross the exact-SHA boundary."""
    with pytest.raises(ValueError, match="40 hexadecimal"):
        materializer.base_hash_locks(tmp_path, "--help")


def test_git_failure_preserves_a_visible_reason(tmp_path: Path) -> None:
    """A failed read-only git command reports its operation and stderr."""
    with pytest.raises(RuntimeError, match=r"git rev-parse failed: fatal"):
        materializer._git(tmp_path, "rev-parse", "HEAD")


@pytest.mark.parametrize(
    ("tree_output", "message"),
    [
        (b"malformed\0", "malformed entry"),
        (b"100644 blob\tfile\0", "malformed metadata"),
    ],
)
def test_rejects_malformed_git_tree_entries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tree_output: bytes,
    message: str,
) -> None:
    """Malformed git output cannot be interpreted as a trusted lock blob."""

    def fake_git(_repo_root: Path, *_args: str) -> bytes:
        return tree_output

    monkeypatch.setattr(materializer, "_git", fake_git)

    with pytest.raises(RuntimeError, match=message):
        materializer.base_hash_locks(tmp_path, "a" * 40)


def test_rejects_symlink_output_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A symlink cannot redirect trusted lock materialization outside its context."""
    target = tmp_path / "target"
    target.mkdir()
    output = tmp_path / "output"
    output.symlink_to(target, target_is_directory=True)
    monkeypatch.setattr(materializer, "base_hash_locks", lambda *_args: [])

    with pytest.raises(ValueError, match="must not be a symlink"):
        materializer.materialize(tmp_path, "a" * 40, output)


def test_main_reports_each_materialized_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The CLI identifies the exact trusted source and generated lock name."""

    def fake_materialize(
        _repo_root: Path, _base_sha: str, _output_dir: Path
    ) -> list[dict[str, str]]:
        return [
            {
                "file": "requirements-000.txt",
                "source": "backend/requirements-hashes.txt",
            }
        ]

    monkeypatch.setattr(materializer, "materialize", fake_materialize)

    assert (
        materializer.main(
            [
                "--repo-root",
                str(tmp_path),
                "--base-sha",
                "a" * 40,
                "--output-dir",
                str(tmp_path / "output"),
            ]
        )
        == 0
    )
    assert (
        "Materialized trusted base Python lock backend/requirements-hashes.txt "
        "as requirements-000.txt." in capsys.readouterr().out
    )


def test_main_reports_when_no_locks_exist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The CLI distinguishes an empty trusted base from a failed extraction."""
    monkeypatch.setattr(materializer, "materialize", lambda *_args: [])

    assert (
        materializer.main(
            [
                "--repo-root",
                str(tmp_path),
                "--base-sha",
                "a" * 40,
                "--output-dir",
                str(tmp_path / "output"),
            ]
        )
        == 0
    )
    assert (
        "No tracked hash-pinned Python requirement locks exist"
        in capsys.readouterr().out
    )


def test_main_fails_with_the_materialization_reason(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A materialization exception fails closed and remains diagnosable in CI."""

    def fail_materialize(_repo_root: Path, _base_sha: str, _output_dir: Path) -> None:
        raise OSError("fixture failure")

    monkeypatch.setattr(materializer, "materialize", fail_materialize)

    assert (
        materializer.main(
            [
                "--repo-root",
                str(tmp_path),
                "--base-sha",
                "a" * 40,
                "--output-dir",
                str(tmp_path / "output"),
            ]
        )
        == 1
    )
    assert (
        "::error::Could not materialize base Python locks: fixture failure"
        in capsys.readouterr().err
    )


def test_script_entrypoint_exits_through_main(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The executable script propagates the fail-closed CLI status."""
    module_path = Path(materializer.__file__)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(module_path),
            "--repo-root",
            str(tmp_path),
            "--base-sha",
            "invalid",
            "--output-dir",
            str(tmp_path / "output"),
        ],
    )

    with pytest.raises(SystemExit) as raised:
        runpy.run_path(str(module_path), run_name="__main__")

    assert raised.value.code == 1
