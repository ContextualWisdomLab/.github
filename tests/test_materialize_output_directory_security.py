"""Security regressions for descriptor-pinned materializer output writes."""

from __future__ import annotations

import errno
import os
from pathlib import Path

import pytest

from scripts.ci import materialize_base_python_requirements as materializer


def _one_lock() -> list[tuple[str, bytes]]:
    """Return one deterministic trusted lock fixture."""

    return [("requirements.lock", b"demo==1 --hash=sha256:" + b"a" * 64 + b"\n")]


def test_materializer_rejects_symlinked_output_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No intermediate symlink may redirect descriptor-relative output creation."""

    target_directory = tmp_path / "target_directory"
    target_directory.mkdir()
    linked_parent = tmp_path / "linked_parent"
    linked_parent.symlink_to(target_directory, target_is_directory=True)
    monkeypatch.setattr(materializer, "base_hash_locks", lambda *_args: [])

    with pytest.raises(ValueError, match="must not contain symlinks"):
        materializer.materialize(
            tmp_path,
            "a" * 40,
            linked_parent / "generated_locks",
        )

    assert list(target_directory.iterdir()) == []


def test_materializer_fails_closed_when_output_binding_disappears(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Removing the published path cannot turn pinned writes into success evidence."""

    output_directory = tmp_path / "generated_locks"
    moved_directory = tmp_path / "moved_locks"

    def move_output_before_return(*_args: object) -> list[tuple[str, bytes]]:
        output_directory.rename(moved_directory)
        return _one_lock()

    monkeypatch.setattr(materializer, "base_hash_locks", move_output_before_return)

    with pytest.raises(ValueError, match="changed during secure materialization"):
        materializer.materialize(tmp_path, "a" * 40, output_directory)

    assert (moved_directory / "requirements-000.txt").read_bytes() == _one_lock()[0][1]
    assert not output_directory.exists()


def test_materializer_fails_closed_when_output_binding_is_replaced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Replacing the pathname with another directory cannot receive trusted writes."""

    output_directory = tmp_path / "generated_locks"
    pinned_directory = tmp_path / "pinned_locks"
    replacement_directory = tmp_path / "replacement_locks"

    def replace_output_before_return(*_args: object) -> list[tuple[str, bytes]]:
        output_directory.rename(pinned_directory)
        replacement_directory.mkdir()
        replacement_directory.rename(output_directory)
        return _one_lock()

    monkeypatch.setattr(materializer, "base_hash_locks", replace_output_before_return)

    with pytest.raises(ValueError, match="changed during secure materialization"):
        materializer.materialize(tmp_path, "a" * 40, output_directory)

    assert (pinned_directory / "requirements-000.txt").read_bytes() == _one_lock()[0][1]
    assert list(output_directory.iterdir()) == []


def test_materializer_rejects_symlinked_destination_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An existing generated-name symlink cannot redirect a trusted lock write."""

    output_directory = tmp_path / "generated_locks"
    output_directory.mkdir()
    outside_file = tmp_path / "outside_file"
    outside_file.write_bytes(b"unchanged")
    (output_directory / "requirements-000.txt").symlink_to(outside_file)
    monkeypatch.setattr(materializer, "base_hash_locks", lambda *_args: _one_lock())

    with pytest.raises(ValueError, match="must not be symlinks"):
        materializer.materialize(tmp_path, "a" * 40, output_directory)

    assert outside_file.read_bytes() == b"unchanged"


def test_materializer_rejects_multiply_linked_destination_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A hard-linked generated name is rejected before truncation or mutation."""

    output_directory = tmp_path / "generated_locks"
    output_directory.mkdir()
    outside_file = tmp_path / "outside_file"
    outside_file.write_bytes(b"unchanged")
    os.link(outside_file, output_directory / "requirements-000.txt")
    monkeypatch.setattr(materializer, "base_hash_locks", lambda *_args: _one_lock())

    with pytest.raises(ValueError, match="singly linked regular files"):
        materializer.materialize(tmp_path, "a" * 40, output_directory)

    assert outside_file.read_bytes() == b"unchanged"


def test_materializer_safely_replaces_single_link_regular_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A rerun may truncate only the pinned, singly linked regular destination."""

    output_directory = tmp_path / "generated_locks"
    output_directory.mkdir()
    destination = output_directory / "requirements-000.txt"
    destination.write_bytes(b"stale")
    monkeypatch.setattr(materializer, "base_hash_locks", lambda *_args: _one_lock())

    manifest = materializer.materialize(tmp_path, "a" * 40, output_directory)

    assert manifest == [
        {"file": "requirements-000.txt", "source": "requirements.lock"}
    ]
    assert destination.read_bytes() == _one_lock()[0][1]


def test_materializer_detects_destination_swap_after_pinned_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A generated pathname swapped after open cannot become accepted evidence."""

    output_directory = tmp_path / "generated_locks"
    outside_file = tmp_path / "outside_file"
    outside_file.write_bytes(b"unchanged")
    monkeypatch.setattr(materializer, "base_hash_locks", lambda *_args: _one_lock())
    real_fsync = materializer.os.fsync
    swapped = False

    def swap_after_file_sync(file_descriptor: int) -> None:
        nonlocal swapped
        real_fsync(file_descriptor)
        if swapped or not (output_directory / "requirements-000.txt").exists():
            return
        swapped = True
        (output_directory / "requirements-000.txt").unlink()
        (output_directory / "requirements-000.txt").symlink_to(outside_file)

    monkeypatch.setattr(materializer.os, "fsync", swap_after_file_sync)

    with pytest.raises(ValueError, match="output file changed"):
        materializer.materialize(tmp_path, "a" * 40, output_directory)

    assert outside_file.read_bytes() == b"unchanged"


def test_materializer_fails_when_descriptor_write_makes_no_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A zero-length descriptor write is an error rather than a truncated success."""

    monkeypatch.setattr(materializer, "base_hash_locks", lambda *_args: _one_lock())
    monkeypatch.setattr(materializer.os, "write", lambda *_args: 0)

    with pytest.raises(OSError, match="made no progress"):
        materializer.materialize(
            tmp_path,
            "a" * 40,
            tmp_path / "generated_locks",
        )


def test_materializer_rejects_filesystem_root_output(tmp_path: Path) -> None:
    """The filesystem root is never a valid generated-lock output directory."""

    with pytest.raises(ValueError, match="must not be the filesystem root"):
        materializer.materialize(tmp_path, "a" * 40, Path("/"))


def test_materializer_normalizes_directory_open_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Platform no-follow failures remain bounded and operator-readable."""

    real_open = materializer.os.open

    def fail_output_open(path: object, flags: int, *args: object, **kwargs: object) -> int:
        if path == "generated_locks":
            raise OSError(errno.ENOTDIR, "synthetic")
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(materializer.os, "open", fail_output_open)

    with pytest.raises(ValueError, match="must not contain symlinks"):
        materializer.materialize(
            tmp_path,
            "a" * 40,
            tmp_path / "generated_locks",
        )
