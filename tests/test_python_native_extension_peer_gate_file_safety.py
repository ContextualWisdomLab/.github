"""Filesystem-race regressions for the native-extension peer-evidence gate."""

from __future__ import annotations

import os
from pathlib import Path

from scripts.ci import python_native_extension_peer_gate as gate


def test_bounded_reader_rejects_a_symlinked_ancestor(tmp_path: Path) -> None:
    """Never trust a regular file reached through a symlinked parent directory."""

    real_root = tmp_path / "real-root"
    real_root.mkdir()
    payload = real_root / "payload.txt"
    payload.write_bytes(b"trusted-looking")
    alias_root = tmp_path / "alias-root"
    alias_root.symlink_to(real_root, target_is_directory=True)

    assert gate._read_bounded_regular(alias_root / payload.name, 64) is None


def test_bounded_reader_rejects_a_read_larger_than_the_declared_limit(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Fail closed when a file grows between metadata validation and reading."""

    payload = tmp_path / "payload.txt"
    payload.write_bytes(b"x")
    maximum = 16
    original_read = os.read
    injected = False

    def oversized_read(file_descriptor: int, count: int) -> bytes:
        nonlocal injected
        if not injected:
            injected = True
            return b"z" * (maximum + 1)
        return original_read(file_descriptor, count)

    monkeypatch.setattr(os, "read", oversized_read)
    assert gate._read_bounded_regular(payload, maximum) is None


def test_bounded_reader_accepts_one_stable_regular_file(tmp_path: Path) -> None:
    """Keep the ordinary bounded regular-file path available after hardening."""

    payload = tmp_path / "payload.txt"
    payload.write_bytes(b"stable")

    assert gate._read_bounded_regular(payload, 16) == b"stable"


def test_bounded_reader_rejects_a_negative_limit(tmp_path: Path) -> None:
    """A negative byte budget is invalid before any filesystem access."""
    payload = tmp_path / "payload.txt"
    payload.write_bytes(b"stable")

    assert gate._read_bounded_regular(payload, -1) is None
