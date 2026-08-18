"""Regression tests for generated flat Python lock publication."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.ci import materialize_base_python_requirements as materializer


def _exact_pin(package_name: str, digest_character: str) -> bytes:
    """Return one standalone exact SHA-256 requirement fixture."""
    return (
        f"{package_name}==1 --hash=sha256:{digest_character * 64}\n".encode()
    )


@pytest.mark.parametrize("directive", ["-r", "--requirement"])
def test_flat_publication_excludes_relative_include_referrers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    directive: str,
) -> None:
    """A generated flat name cannot preserve a source-relative include edge."""
    tree = (
        b"100644 blob "
        + (b"0" * 40)
        + b"\trequirements-other.txt\0"
        + b"100644 blob "
        + (b"1" * 40)
        + b"\trequirements.txt\0"
    )
    target_lock = _exact_pin("target-package", "a")

    def fake_git(_repo_root: Path, *args: str) -> bytes:
        if args[0] == "ls-tree":
            return tree
        if args[0] == "show" and args[-1].endswith(":requirements-other.txt"):
            return target_lock
        if args[0] == "show" and args[-1].endswith(":requirements.txt"):
            return f"{directive} requirements-other.txt\n".encode()
        raise AssertionError(args)

    monkeypatch.setattr(materializer, "_git", fake_git)

    assert materializer.base_hash_locks(tmp_path, "a" * 40) == [
        ("requirements-other.txt", target_lock)
    ]


def test_flat_publication_discovers_standalone_requirements_directory_locks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Path-aware discovery keeps complete direct requirements-directory locks."""
    tree = (
        b"100644 blob "
        + (b"0" * 40)
        + b"\trequirements/ci.txt\0"
        + b"100644 blob "
        + (b"1" * 40)
        + b"\tservice/requirements/package.txt\0"
        + b"100644 blob "
        + (b"2" * 40)
        + b"\trequirements.txt\0"
    )
    ci_lock = _exact_pin("ci-package", "a")
    service_lock = _exact_pin("service-package", "b")

    def fake_git(_repo_root: Path, *args: str) -> bytes:
        if args[0] == "ls-tree":
            return tree
        if args[0] == "show" and args[-1].endswith(":requirements/ci.txt"):
            return ci_lock
        if args[0] == "show" and args[-1].endswith(
            ":service/requirements/package.txt"
        ):
            return service_lock
        if args[0] == "show" and args[-1].endswith(":requirements.txt"):
            return b"-r requirements/ci.txt\n"
        raise AssertionError(args)

    monkeypatch.setattr(materializer, "_git", fake_git)

    assert materializer.base_hash_locks(tmp_path, "a" * 40) == [
        ("requirements/ci.txt", ci_lock),
        ("service/requirements/package.txt", service_lock),
    ]
