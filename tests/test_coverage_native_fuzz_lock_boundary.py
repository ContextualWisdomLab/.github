from __future__ import annotations

import subprocess
from pathlib import Path

from scripts.ci import materialize_base_python_requirements as materializer


def _git(repo: Path, *args: str) -> str:
    """Run one deterministic Git command inside a temporary fixture repository."""

    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _hashed_requirement(package_name: str, digest_character: str) -> str:
    """Create one syntactically hash-pinned requirement fixture line."""

    return (
        f"{package_name}==1.0.0 --hash=sha256:"
        f"{digest_character * 64}\n"
    )


def test_generic_coverage_excludes_only_the_exact_native_atheris_lock(
    tmp_path: Path,
) -> None:
    """Coverage retains test dependencies but never installs the Atheris toolchain."""

    repo = tmp_path / "repository"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "Coverage Boundary Test")
    _git(repo, "config", "user.email", "coverage-boundary@example.invalid")

    fuzz_directory = repo / "fuzz"
    fuzz_directory.mkdir()
    (fuzz_directory / "requirements-atheris.txt").write_text(
        _hashed_requirement("atheris", "a"),
        encoding="utf-8",
    )
    (fuzz_directory / "requirements-property.txt").write_text(
        _hashed_requirement("hypothesis", "b"),
        encoding="utf-8",
    )

    service_directory = repo / "services" / "example_service"
    service_directory.mkdir(parents=True)
    (service_directory / "requirements-fuzz-regression.txt").write_text(
        _hashed_requirement("pytest", "c"),
        encoding="utf-8",
    )

    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "base dependency roles")
    base_sha = _git(repo, "rev-parse", "HEAD")

    output_directory = tmp_path / "materialized"
    manifest = materializer.materialize(repo, base_sha, output_directory)

    assert [entry["source"] for entry in manifest] == [
        "fuzz/requirements-property.txt",
        "services/example_service/requirements-fuzz-regression.txt",
    ]
    assert "requirements-atheris.txt" not in (
        output_directory / "manifest.json"
    ).read_text(encoding="utf-8")


def test_native_fuzz_engine_classifier_uses_exact_file_names() -> None:
    """Role classification cannot expand through substrings or directory names."""

    assert materializer._is_native_fuzz_engine_lock_name(
        "requirements-atheris.txt"
    )
    assert not materializer._is_native_fuzz_engine_lock_name(
        "requirements-atheris-regression.txt"
    )
    assert not materializer._is_native_fuzz_engine_lock_name(
        "requirements-property.txt"
    )
