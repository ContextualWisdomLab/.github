"""Security regressions for descriptor-pinned JavaScript lock materialization."""

from __future__ import annotations

import errno
import os
from pathlib import Path

import pytest

from scripts.ci import materialize_base_javascript_packages as materializer


def _one_project(relative_path: str = "package-lock.json") -> list[tuple[str, str, dict[str, bytes]]]:
    """Return one deterministic trusted npm project fixture."""

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
    """Replace Git-backed discovery with one bounded in-memory project."""

    monkeypatch.setattr(
        materializer,
        "base_npm_projects",
        lambda *_args: _one_project() if projects is None else projects,
    )
    monkeypatch.setattr(materializer, "base_pnpm_projects", lambda *_args: [])
    monkeypatch.setattr(materializer, "_lock_blob_sha", lambda *_args: "b" * 40)


def test_materializer_rejects_symlinked_output_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No intermediate symlink may redirect descriptor-relative output creation."""

    target_directory = tmp_path / "target_directory"
    target_directory.mkdir()
    linked_parent = tmp_path / "linked_parent"
    linked_parent.symlink_to(target_directory, target_is_directory=True)
    _stub_project_discovery(monkeypatch, [])

    with pytest.raises(ValueError, match="must not contain symlinks"):
        materializer.materialize(
            tmp_path,
            "a" * 40,
            linked_parent / "generated_locks",
        )

    assert list(target_directory.iterdir()) == []


def test_materializer_fails_closed_when_output_binding_is_replaced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Replacing the published pathname cannot receive trusted lock inputs."""

    output_directory = tmp_path / "generated_locks"
    pinned_directory = tmp_path / "pinned_locks"
    replacement_directory = tmp_path / "replacement_locks"

    def replace_output_before_return(
        *_args: object,
    ) -> list[tuple[str, str, dict[str, bytes]]]:
        output_directory.rename(pinned_directory)
        replacement_directory.mkdir()
        replacement_directory.rename(output_directory)
        return _one_project()

    monkeypatch.setattr(
        materializer,
        "base_npm_projects",
        replace_output_before_return,
    )
    monkeypatch.setattr(materializer, "base_pnpm_projects", lambda *_args: [])
    monkeypatch.setattr(materializer, "_lock_blob_sha", lambda *_args: "b" * 40)

    with pytest.raises(ValueError, match="changed during secure materialization"):
        materializer.materialize(tmp_path, "a" * 40, output_directory)

    assert (pinned_directory / "project-000" / "package-lock.json").is_file()
    assert list(output_directory.iterdir()) == []


def test_materializer_anchors_writes_when_output_path_becomes_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A post-open output symlink cannot redirect the first generated file."""

    output_directory = tmp_path / "generated_locks"
    pinned_directory = tmp_path / "pinned_locks"
    attacker_directory = tmp_path / "attacker_directory"
    attacker_directory.mkdir()
    _stub_project_discovery(monkeypatch)
    real_open = os.open
    attacked = False

    def swap_before_first_file_open(
        path: object,
        flags: int,
        *args: object,
        **kwargs: object,
    ) -> int:
        nonlocal attacked
        if not attacked and path == "package-lock.json" and flags & os.O_CREAT:
            attacked = True
            output_directory.rename(pinned_directory)
            output_directory.symlink_to(attacker_directory, target_is_directory=True)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", swap_before_first_file_open)

    with pytest.raises(ValueError, match="changed during secure materialization"):
        materializer.materialize(tmp_path, "a" * 40, output_directory)

    assert attacked is True
    assert (
        pinned_directory / "project-000" / "package-lock.json"
    ).read_bytes() == _one_project()[0][2]["package-lock.json"]
    assert list(attacker_directory.iterdir()) == []


@pytest.mark.parametrize("relative_path", ["../escape", "/absolute", "nested\\escape"])
def test_materializer_rejects_unsafe_relative_input_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    relative_path: str,
) -> None:
    """Trusted inputs still require one lexical relative POSIX output path."""

    _stub_project_discovery(monkeypatch, _one_project(relative_path))

    with pytest.raises(ValueError, match="unsafe relative output path"):
        materializer.materialize(
            tmp_path,
            "a" * 40,
            tmp_path / "generated_locks",
        )

    assert not (tmp_path / "escape").exists()


def test_materializer_rejects_preexisting_generated_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pre-existing generated name cannot be truncated or reinterpreted."""

    output_directory = tmp_path / "generated_locks"
    project_directory = output_directory / "project-000"
    project_directory.mkdir(parents=True)
    destination = project_directory / "package-lock.json"
    destination.write_bytes(b"unchanged")
    _stub_project_discovery(monkeypatch)

    with pytest.raises(ValueError, match="must not pre-exist"):
        materializer.materialize(tmp_path, "a" * 40, output_directory)

    assert destination.read_bytes() == b"unchanged"


def test_materializer_detects_hard_link_added_during_pinned_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A hard link added after file creation must fail before success evidence."""

    output_directory = tmp_path / "generated_locks"
    outside_link = tmp_path / "captured_output"
    _stub_project_discovery(monkeypatch)
    real_fsync = os.fsync
    linked = False

    def link_after_file_sync(file_descriptor: int) -> None:
        nonlocal linked
        real_fsync(file_descriptor)
        destination = output_directory / "project-000" / "package-lock.json"
        if linked or not destination.exists():
            return
        descriptor_metadata = os.fstat(file_descriptor)
        path_metadata = os.stat(destination, follow_symlinks=False)
        if (descriptor_metadata.st_dev, descriptor_metadata.st_ino) != (
            path_metadata.st_dev,
            path_metadata.st_ino,
        ):
            return
        os.link(destination, outside_link)
        linked = True

    monkeypatch.setattr(os, "fsync", link_after_file_sync)

    with pytest.raises(ValueError, match="singly linked regular files"):
        materializer.materialize(tmp_path, "a" * 40, output_directory)

    assert linked is True
    assert outside_link.read_bytes() == _one_project()[0][2]["package-lock.json"]


def test_materializer_detects_destination_swap_after_pinned_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A generated name swapped after open cannot become accepted evidence."""

    output_directory = tmp_path / "generated_locks"
    outside_file = tmp_path / "outside_file"
    outside_file.write_bytes(b"unchanged")
    _stub_project_discovery(monkeypatch)
    real_fsync = os.fsync
    swapped = False

    def swap_after_file_sync(file_descriptor: int) -> None:
        nonlocal swapped
        real_fsync(file_descriptor)
        destination = output_directory / "project-000" / "package-lock.json"
        if swapped or not destination.exists():
            return
        swapped = True
        destination.unlink()
        destination.symlink_to(outside_file)

    monkeypatch.setattr(os, "fsync", swap_after_file_sync)

    with pytest.raises(ValueError, match="output file changed"):
        materializer.materialize(tmp_path, "a" * 40, output_directory)

    assert outside_file.read_bytes() == b"unchanged"


def test_materializer_fails_when_descriptor_write_makes_no_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A zero-length descriptor write is an error, not truncated success."""

    _stub_project_discovery(monkeypatch)
    monkeypatch.setattr(os, "write", lambda *_args: 0)

    with pytest.raises(OSError, match="made no progress"):
        materializer.materialize(
            tmp_path,
            "a" * 40,
            tmp_path / "generated_locks",
        )


def test_materializer_rejects_filesystem_root_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The filesystem root is never a generated-lock output directory."""

    _stub_project_discovery(monkeypatch, [])

    with pytest.raises(ValueError, match="must not be the filesystem root"):
        materializer.materialize(tmp_path, "a" * 40, Path("/"))


def test_materializer_normalizes_directory_open_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No-follow directory failures remain bounded and operator-readable."""

    _stub_project_discovery(monkeypatch, [])
    real_open = os.open

    def fail_output_open(
        path: object,
        flags: int,
        *args: object,
        **kwargs: object,
    ) -> int:
        if path == "generated_locks":
            raise OSError(errno.ENOTDIR, "synthetic")
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", fail_output_open)

    with pytest.raises(ValueError, match="must not contain symlinks"):
        materializer.materialize(
            tmp_path,
            "a" * 40,
            tmp_path / "generated_locks",
        )
