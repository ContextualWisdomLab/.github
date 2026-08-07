"""Branch-complete edge contracts for JavaScript materializer output hardening."""

from __future__ import annotations

import errno
import os
from pathlib import Path

import pytest

from scripts.ci import materialize_base_javascript_packages as materializer


def _different_inode(metadata: os.stat_result) -> os.stat_result:
    """Return metadata with the inode changed while retaining all other fields."""

    values = list(metadata)
    values[1] = metadata.st_ino + 1
    return os.stat_result(values)


def test_capability_gate_rejects_missing_no_follow_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Secure output publication fails when a required open flag is unavailable."""

    monkeypatch.delattr(materializer.os, "O_NOFOLLOW")

    with pytest.raises(ValueError, match="descriptor-relative output operations"):
        materializer._require_descriptor_relative_capabilities()


def test_component_scan_rejects_existing_regular_file(tmp_path: Path) -> None:
    """A regular file cannot become an intermediate output-directory component."""

    blocking_file = tmp_path / "blocking_file"
    blocking_file.write_bytes(b"not a directory")

    with pytest.raises(ValueError, match="path component must be a directory"):
        materializer._reject_symlinked_output_components(
            blocking_file / "generated_locks"
        )


def test_directory_identity_rejects_non_directory_metadata(tmp_path: Path) -> None:
    """Directory identities reject regular-file metadata before inode comparison."""

    regular_file = tmp_path / "regular_file"
    regular_file.write_bytes(b"content")

    with pytest.raises(ValueError, match="binding changed"):
        materializer._directory_identity(regular_file.stat())


def test_output_open_detects_parent_descriptor_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The opened parent descriptor must retain the pre-open parent identity."""

    output_directory = tmp_path / "generated_locks"
    expected_parent = os.fspath(output_directory.parent)
    real_open = materializer.os.open
    real_fstat = materializer.os.fstat
    parent_descriptors: list[int] = []

    def capture_parent_open(
        path: object,
        flags: int,
        *args: object,
        **kwargs: object,
    ) -> int:
        descriptor = real_open(path, flags, *args, **kwargs)
        if os.fspath(path) == expected_parent and kwargs.get("dir_fd") is None:
            parent_descriptors.append(descriptor)
        return descriptor

    def replace_parent_identity(descriptor: int) -> os.stat_result:
        metadata = real_fstat(descriptor)
        if descriptor in parent_descriptors:
            return _different_inode(metadata)
        return metadata

    monkeypatch.setattr(materializer.os, "open", capture_parent_open)
    monkeypatch.setattr(materializer.os, "fstat", replace_parent_identity)

    with pytest.raises(ValueError, match="ancestor changed"):
        materializer._open_output_directory(output_directory)

    assert len(parent_descriptors) == 1
    with pytest.raises(OSError) as raised:
        os.fstat(parent_descriptors[0])
    assert raised.value.errno == errno.EBADF


def test_output_open_detects_output_descriptor_replacement_and_closes_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The opened output descriptor is closed when its inode mismatches the path."""

    output_directory = tmp_path / "generated_locks"
    real_open = materializer.os.open
    real_fstat = materializer.os.fstat
    output_descriptors: list[int] = []

    def capture_output_open(
        path: object,
        flags: int,
        *args: object,
        **kwargs: object,
    ) -> int:
        descriptor = real_open(path, flags, *args, **kwargs)
        if path == output_directory.name and kwargs.get("dir_fd") is not None:
            output_descriptors.append(descriptor)
        return descriptor

    def replace_output_identity(descriptor: int) -> os.stat_result:
        metadata = real_fstat(descriptor)
        if descriptor in output_descriptors:
            return _different_inode(metadata)
        return metadata

    monkeypatch.setattr(materializer.os, "open", capture_output_open)
    monkeypatch.setattr(materializer.os, "fstat", replace_output_identity)

    with pytest.raises(ValueError, match="output directory changed"):
        materializer._open_output_directory(output_directory)

    assert len(output_descriptors) == 1
    with pytest.raises(OSError) as raised:
        os.fstat(output_descriptors[0])
    assert raised.value.errno == errno.EBADF


def test_relative_directory_creation_synchronizes_new_directory(tmp_path: Path) -> None:
    """A newly created nested directory returns a live pinned descriptor."""

    root_fd = os.open(tmp_path, materializer._DIRECTORY_OPEN_FLAGS)
    nested_fd = materializer._open_relative_directory(root_fd, ("nested_directory",))
    try:
        assert (tmp_path / "nested_directory").is_dir()
        assert os.path.samestat(
            os.fstat(nested_fd),
            os.stat(tmp_path / "nested_directory", follow_symlinks=False),
        )
    finally:
        os.close(nested_fd)
        os.close(root_fd)


def test_relative_directory_detects_descriptor_replacement_and_closes_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A child descriptor is closed when it differs from the pre-open child inode."""

    root_fd = os.open(tmp_path, materializer._DIRECTORY_OPEN_FLAGS)
    real_open = materializer.os.open
    real_fstat = materializer.os.fstat
    child_descriptors: list[int] = []

    def capture_child_open(
        path: object,
        flags: int,
        *args: object,
        **kwargs: object,
    ) -> int:
        descriptor = real_open(path, flags, *args, **kwargs)
        if path == "nested_directory" and kwargs.get("dir_fd") is not None:
            child_descriptors.append(descriptor)
        return descriptor

    def replace_child_identity(descriptor: int) -> os.stat_result:
        metadata = real_fstat(descriptor)
        if descriptor in child_descriptors:
            return _different_inode(metadata)
        return metadata

    monkeypatch.setattr(materializer.os, "open", capture_child_open)
    monkeypatch.setattr(materializer.os, "fstat", replace_child_identity)
    try:
        with pytest.raises(ValueError, match="binding changed"):
            materializer._open_relative_directory(root_fd, ("nested_directory",))
    finally:
        os.close(root_fd)

    assert len(child_descriptors) == 1
    with pytest.raises(OSError) as raised:
        os.fstat(child_descriptors[0])
    assert raised.value.errno == errno.EBADF


def test_project_directory_detects_descriptor_replacement_and_closes_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fresh project descriptor is closed when its inode fails revalidation."""

    output_fd = os.open(tmp_path, materializer._DIRECTORY_OPEN_FLAGS)
    real_open = materializer.os.open
    real_fstat = materializer.os.fstat
    project_descriptors: list[int] = []

    def capture_project_open(
        path: object,
        flags: int,
        *args: object,
        **kwargs: object,
    ) -> int:
        descriptor = real_open(path, flags, *args, **kwargs)
        if path == "project-000" and kwargs.get("dir_fd") == output_fd:
            project_descriptors.append(descriptor)
        return descriptor

    def replace_project_identity(descriptor: int) -> os.stat_result:
        metadata = real_fstat(descriptor)
        if descriptor in project_descriptors:
            return _different_inode(metadata)
        return metadata

    monkeypatch.setattr(materializer.os, "open", capture_project_open)
    monkeypatch.setattr(materializer.os, "fstat", replace_project_identity)
    try:
        with pytest.raises(ValueError, match="binding changed"):
            materializer._create_project_directory(output_fd, "project-000")
    finally:
        os.close(output_fd)

    assert len(project_descriptors) == 1
    with pytest.raises(OSError) as raised:
        os.fstat(project_descriptors[0])
    assert raised.value.errno == errno.EBADF


def test_unlink_owned_file_ignores_missing_name(tmp_path: Path) -> None:
    """Cleanup is a no-op when the generated filename no longer exists."""

    parent_fd = os.open(tmp_path, materializer._DIRECTORY_OPEN_FLAGS)
    try:
        materializer._unlink_owned_file(parent_fd, "missing_file", (1, 1))
    finally:
        os.close(parent_fd)


def test_unlink_owned_file_ignores_replaced_identity(tmp_path: Path) -> None:
    """Cleanup never unlinks a path that no longer names the generated inode."""

    destination = tmp_path / "generated_file"
    destination.write_bytes(b"replacement")
    parent_fd = os.open(tmp_path, materializer._DIRECTORY_OPEN_FLAGS)
    try:
        materializer._unlink_owned_file(parent_fd, destination.name, (1, 1))
    finally:
        os.close(parent_fd)
    assert destination.read_bytes() == b"replacement"


def test_unlink_owned_file_ignores_unlink_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cleanup remains fail-safe when the owned filename cannot be unlinked."""

    destination = tmp_path / "generated_file"
    destination.write_bytes(b"content")
    metadata = destination.stat()
    parent_fd = os.open(tmp_path, materializer._DIRECTORY_OPEN_FLAGS)

    def deny_unlink(*_args: object, **_kwargs: object) -> None:
        raise PermissionError(errno.EACCES, "synthetic")

    monkeypatch.setattr(materializer.os, "unlink", deny_unlink)
    try:
        materializer._unlink_owned_file(
            parent_fd,
            destination.name,
            (metadata.st_dev, metadata.st_ino),
        )
    finally:
        os.close(parent_fd)
    assert destination.read_bytes() == b"content"


def test_remove_owned_directory_ignores_missing_name(tmp_path: Path) -> None:
    """Directory cleanup is a no-op when the generated directory disappeared."""

    parent_fd = os.open(tmp_path, materializer._DIRECTORY_OPEN_FLAGS)
    try:
        materializer._remove_owned_empty_directory(
            parent_fd,
            "missing_directory",
            (1, 1),
        )
    finally:
        os.close(parent_fd)


def test_remove_owned_directory_ignores_regular_file(tmp_path: Path) -> None:
    """Directory cleanup never removes a regular file at the generated name."""

    destination = tmp_path / "project-000"
    destination.write_bytes(b"content")
    metadata = destination.stat()
    parent_fd = os.open(tmp_path, materializer._DIRECTORY_OPEN_FLAGS)
    try:
        materializer._remove_owned_empty_directory(
            parent_fd,
            destination.name,
            (metadata.st_dev, metadata.st_ino),
        )
    finally:
        os.close(parent_fd)
    assert destination.read_bytes() == b"content"


def test_remove_owned_directory_ignores_replaced_identity(tmp_path: Path) -> None:
    """Directory cleanup preserves a directory whose inode no longer matches."""

    destination = tmp_path / "project-000"
    destination.mkdir()
    parent_fd = os.open(tmp_path, materializer._DIRECTORY_OPEN_FLAGS)
    try:
        materializer._remove_owned_empty_directory(
            parent_fd,
            destination.name,
            (1, 1),
        )
    finally:
        os.close(parent_fd)
    assert destination.is_dir()


def test_remove_owned_directory_ignores_rmdir_failure(tmp_path: Path) -> None:
    """Nonempty owned directories remain available for forensic inspection."""

    destination = tmp_path / "project-000"
    destination.mkdir()
    (destination / "retained_file").write_bytes(b"content")
    metadata = destination.stat()
    parent_fd = os.open(tmp_path, materializer._DIRECTORY_OPEN_FLAGS)
    try:
        materializer._remove_owned_empty_directory(
            parent_fd,
            destination.name,
            (metadata.st_dev, metadata.st_ino),
        )
    finally:
        os.close(parent_fd)
    assert (destination / "retained_file").read_bytes() == b"content"
