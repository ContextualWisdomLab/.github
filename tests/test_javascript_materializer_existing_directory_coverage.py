"""Existing-directory branch coverage for the JavaScript lock materializer."""

from __future__ import annotations

import os
from pathlib import Path

from scripts.ci import materialize_base_javascript_packages as materializer


def test_relative_directory_reuses_existing_directory(tmp_path: Path) -> None:
    """A pre-existing nested directory is opened without the creation-only sync path."""

    nested_directory = tmp_path / "nested_directory"
    nested_directory.mkdir()
    root_fd = os.open(tmp_path, materializer._DIRECTORY_OPEN_FLAGS)
    nested_fd = materializer._open_relative_directory(root_fd, (nested_directory.name,))
    try:
        assert os.path.samestat(
            os.fstat(nested_fd),
            os.stat(nested_directory, follow_symlinks=False),
        )
    finally:
        os.close(nested_fd)
        os.close(root_fd)
