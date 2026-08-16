"""Regression tests for standalone flat requirements publication."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.ci import materialize_base_python_requirements as materializer


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        (b"", False),
        (b"--require-hashes\n", False),
        (b"-r requirements-other.txt\n", False),
        (b"--requirement requirements-other.txt\n", False),
        (b"demo==1 --hash=sha256:" + (b"a" * 64) + b"\n", True),
    ],
)
def test_flat_lock_policy_requires_a_standalone_exact_hash_closure(
    content: bytes,
    expected: bool,
) -> None:
    """Generated flat lock names cannot preserve source-relative includes."""
    assert materializer._is_flat_materializable_lock(content) is expected


def test_base_lock_discovery_excludes_relative_include_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A relative include never crosses from the exact base into flat output."""
    tree = (
        b"100644 blob "
        + (b"0" * 40)
        + b"\trequirements-other.txt\0"
        + b"100644 blob "
        + (b"1" * 40)
        + b"\trequirements.txt\0"
    )
    pinned = b"demo==1 --hash=sha256:" + (b"a" * 64) + b"\n"

    def fake_git(_repo_root: Path, *args: str) -> bytes:
        if args[0] == "ls-tree":
            return tree
        if args[0] == "show" and args[-1].endswith(":requirements-other.txt"):
            return pinned
        if args[0] == "show" and args[-1].endswith(":requirements.txt"):
            return b"-r requirements-other.txt\n"
        raise AssertionError(args)

    monkeypatch.setattr(materializer, "_git", fake_git)

    assert materializer.base_hash_locks(tmp_path, "a" * 40) == [
        ("requirements-other.txt", pinned)
    ]