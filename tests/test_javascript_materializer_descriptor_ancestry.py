"""Adversarial contracts for descriptor-anchored materializer ancestry and cleanup."""

from __future__ import annotations

import os
from pathlib import Path
import stat

import pytest

from scripts.ci import materialize_base_javascript_packages as materializer


_BASE_SHA = "a" * 40
_LOCK_BLOB_SHA = "b" * 40


def _projects(relative_path: str = "package-lock.json") -> list[tuple[str, str, dict[str, bytes]]]:
    """Return one deterministic npm project with one optionally nested lock input."""
    return [
        (
            "package-lock.json",
            "npm",
            {
                "package.json": b'{"name":"fixture"}\n',
                relative_path: b'{"lockfileVersion":3,"packages":{}}\n',
            },
        )
    ]


def _stub_project_discovery(
    monkeypatch: pytest.MonkeyPatch,
    projects: list[tuple[str, str, dict[str, bytes]]] | None = None,
) -> None:
    """Replace Git-backed project discovery with bounded in-memory fixtures."""
    monkeypatch.setattr(
        materializer,
        "base_npm_projects",
        lambda *_args: _projects() if projects is None else projects,
    )
    monkeypatch.setattr(materializer, "base_pnpm_projects", lambda *_args: [])
    monkeypatch.setattr(materializer, "_lock_blob_sha", lambda *_args: _LOCK_BLOB_SHA)


def test_materializer_rejects_intermediate_ancestor_swap_before_parent_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An intermediate ancestor swap cannot redirect the initially opened output tree."""
    trusted_root = tmp_path / "trusted_root"
    trusted_parent = trusted_root / "nested_parent"
    output_directory = trusted_parent / "generated_locks"
    trusted_parent.mkdir(parents=True)

    pinned_root = tmp_path / "pinned_root"
    attacker_root = tmp_path / "attacker_root"
    attacker_output = attacker_root / "nested_parent" / "generated_locks"
    attacker_output.mkdir(parents=True)
    _stub_project_discovery(monkeypatch)

    real_open = os.open
    swapped = False

    def swap_intermediate_ancestor(
        path: object,
        flags: int,
        *args: object,
        **kwargs: object,
    ) -> int:
        nonlocal swapped
        if (
            not swapped
            and Path(path) == trusted_parent.absolute()
            and kwargs.get("dir_fd") is None
        ):
            trusted_root.rename(pinned_root)
            trusted_root.symlink_to(attacker_root, target_is_directory=True)
            swapped = True
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", swap_intermediate_ancestor)

    with pytest.raises(ValueError, match="ancestor|symlink|changed"):
        materializer.materialize(tmp_path, _BASE_SHA, output_directory)

    assert swapped is True
    assert list(attacker_output.iterdir()) == []
    assert list((pinned_root / "nested_parent" / "generated_locks").iterdir()) == []


def test_materializer_rejects_new_nested_directory_replacement_before_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A directory created beneath a held descriptor must retain its original inode."""
    output_directory = tmp_path / "generated_locks"
    saved_directory = tmp_path / "saved_nested_directory"
    _stub_project_discovery(monkeypatch, _projects("nested_directory/package-lock.json"))

    real_open = os.open
    swapped = False

    def swap_nested_directory(
        path: object,
        flags: int,
        *args: object,
        **kwargs: object,
    ) -> int:
        nonlocal swapped
        if (
            not swapped
            and path == "nested_directory"
            and kwargs.get("dir_fd") is not None
        ):
            nested_directory = output_directory / "project-000" / "nested_directory"
            nested_directory.rename(saved_directory)
            nested_directory.mkdir()
            swapped = True
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", swap_nested_directory)

    with pytest.raises(ValueError, match="directory.*changed|binding|inode"):
        materializer.materialize(tmp_path, _BASE_SHA, output_directory)

    assert swapped is True
    assert list(saved_directory.iterdir()) == []
    replacement = output_directory / "project-000" / "nested_directory"
    assert not (replacement / "package-lock.json").exists()


def test_materializer_fsyncs_files_and_every_published_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Durable evidence requires file bytes and directory entries to be synchronized."""
    output_directory = tmp_path / "generated_locks"
    _stub_project_discovery(monkeypatch, _projects("nested_directory/package-lock.json"))
    real_fsync = os.fsync
    synchronized_modes: list[int] = []

    def track_fsync(file_descriptor: int) -> None:
        synchronized_modes.append(stat.S_IFMT(os.fstat(file_descriptor).st_mode))
        real_fsync(file_descriptor)

    monkeypatch.setattr(os, "fsync", track_fsync)

    materializer.materialize(tmp_path, _BASE_SHA, output_directory)

    assert stat.S_IFREG in synchronized_modes
    assert stat.S_IFDIR in synchronized_modes
    assert synchronized_modes.count(stat.S_IFDIR) >= 3


def test_materializer_fails_closed_without_descriptor_relative_capabilities(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unsupported runtimes must fail before creating any output path."""
    output_directory = tmp_path / "generated_locks"
    _stub_project_discovery(monkeypatch, [])
    monkeypatch.setattr(os, "supports_dir_fd", set())

    with pytest.raises(ValueError, match="descriptor-relative.*unavailable"):
        materializer.materialize(tmp_path, _BASE_SHA, output_directory)

    assert not output_directory.exists()


def test_failed_write_removes_only_owned_outputs_and_preserves_existing_entries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failure cleanup removes partial generated evidence without deleting prior content."""
    output_directory = tmp_path / "generated_locks"
    output_directory.mkdir()
    existing_file = output_directory / "operator-note.txt"
    existing_file.write_text("preserve\n", encoding="utf-8")
    _stub_project_discovery(monkeypatch)
    monkeypatch.setattr(os, "write", lambda *_args: 0)

    with pytest.raises(OSError, match="made no progress"):
        materializer.materialize(tmp_path, _BASE_SHA, output_directory)

    assert existing_file.read_text(encoding="utf-8") == "preserve\n"
    assert sorted(path.name for path in output_directory.iterdir()) == [
        "operator-note.txt"
    ]
