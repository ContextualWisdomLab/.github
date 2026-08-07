"""Adversarial creation and rollback contracts for JavaScript lock materialization."""

from __future__ import annotations

import os
from pathlib import Path
import pathlib

import pytest

from scripts.ci import materialize_base_javascript_packages as materializer


_BASE_SHA = "a" * 40
_LOCK_BLOB_SHA = "b" * 40


def _stub_projects(
    monkeypatch: pytest.MonkeyPatch,
    inputs: dict[str, bytes] | None = None,
) -> None:
    """Replace Git discovery with one bounded npm project or an empty queue."""
    projects = []
    if inputs is not None:
        projects = [("package-lock.json", "npm", inputs)]
    monkeypatch.setattr(
        materializer,
        "base_npm_projects",
        lambda *_args: projects,
    )
    monkeypatch.setattr(materializer, "base_pnpm_projects", lambda *_args: [])
    monkeypatch.setattr(materializer, "_lock_blob_sha", lambda *_args: _LOCK_BLOB_SHA)


def test_forwarding_open_instrumentation_does_not_change_platform_capability(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Capability checks use immutable CPython callables, not test wrappers."""
    output_directory = tmp_path / "generated_locks"
    _stub_projects(monkeypatch)
    real_open = os.open

    def forwarding_open(
        path: object,
        flags: int,
        *args: object,
        **kwargs: object,
    ) -> int:
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", forwarding_open)

    manifest = materializer.materialize(tmp_path, _BASE_SHA, output_directory)

    assert manifest == []
    assert (output_directory / "manifest.json").read_text(encoding="utf-8") == "[]\n"


def test_materializer_rejects_missing_follow_symlink_capability_before_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No-follow stat support is mandatory before any output path is created."""
    output_directory = tmp_path / "generated_locks"
    _stub_projects(monkeypatch)
    monkeypatch.setattr(os, "supports_follow_symlinks", set())

    with pytest.raises(ValueError, match="descriptor-relative.*unavailable"):
        materializer.materialize(tmp_path, _BASE_SHA, output_directory)

    assert not output_directory.exists()


def test_missing_ancestor_swap_never_creates_output_through_attacker_symlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pathname creation cannot be redirected while an ancestor is replaced."""
    trusted_root = tmp_path / "trusted_root"
    trusted_root.mkdir()
    pinned_root = tmp_path / "pinned_root"
    attacker_root = tmp_path / "attacker_root"
    attacker_parent = attacker_root / "missing_parent"
    attacker_parent.mkdir(parents=True)
    output_directory = trusted_root / "missing_parent" / "generated_locks"
    attacker_output = attacker_parent / "generated_locks"
    _stub_projects(monkeypatch)

    real_mkdir = pathlib.Path.mkdir
    swapped = False

    def swap_after_parent_creation(
        path: pathlib.Path,
        *args: object,
        **kwargs: object,
    ) -> None:
        nonlocal swapped
        real_mkdir(path, *args, **kwargs)
        if not swapped and path == output_directory.parent.absolute():
            trusted_root.rename(pinned_root)
            trusted_root.symlink_to(attacker_root, target_is_directory=True)
            swapped = True

    monkeypatch.setattr(pathlib.Path, "mkdir", swap_after_parent_creation)

    with pytest.raises(ValueError, match="ancestor|symlink|changed"):
        materializer.materialize(tmp_path, _BASE_SHA, output_directory)

    assert swapped is True
    assert not attacker_output.exists()


def test_late_write_failure_rolls_back_every_owned_file_and_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rollback removes all earlier generated entries while preserving operator data."""
    output_directory = tmp_path / "generated_locks"
    output_directory.mkdir()
    operator_note = output_directory / "operator-note.txt"
    operator_note.write_text("preserve\n", encoding="utf-8")
    _stub_projects(
        monkeypatch,
        {
            "a-first.json": b"first\n",
            "b-second.json": b"second\n",
        },
    )
    real_write = os.write
    write_calls = 0

    def fail_second_file_write(file_descriptor: int, content: object) -> int:
        nonlocal write_calls
        write_calls += 1
        if write_calls == 2:
            return 0
        return real_write(file_descriptor, content)

    monkeypatch.setattr(os, "write", fail_second_file_write)

    with pytest.raises(OSError, match="made no progress"):
        materializer.materialize(tmp_path, _BASE_SHA, output_directory)

    assert write_calls == 2
    assert operator_note.read_text(encoding="utf-8") == "preserve\n"
    assert sorted(path.name for path in output_directory.iterdir()) == [
        "operator-note.txt"
    ]
