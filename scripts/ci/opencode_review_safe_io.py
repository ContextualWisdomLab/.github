"""Fail-closed exclusive atomic UTF-8 writes for review-evidence CLIs."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

Reject = Callable[[str], None]


def refuse_symlink_parent(path: Path, reject: Reject) -> None:
    """Reject an output whose immediate parent directory is a symbolic link."""
    if path.parent.is_symlink():
        reject("output parent directory must not be a symbolic link")


def atomic_write_text(path: Path, content: str, reject: Reject) -> None:
    """Replace one UTF-8 file through an exclusive, non-following temporary sibling.

    The immediate parent must not be a symbolic link (CWE-367). A pre-planted
    temporary symlink is refused. The temporary file is created with
    ``O_CREAT|O_EXCL|O_NOFOLLOW``, flushed with ``fsync``, then replaced onto
    the destination.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    refuse_symlink_parent(path, reject)
    temporary = path.with_name(f".{path.name}.tmp")
    if temporary.is_symlink():
        reject("temporary output path must not be a symbolic link")
    if temporary.exists():
        if temporary.is_dir():
            reject("temporary output path must not be a directory")
        temporary.unlink()
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    try:
        file_descriptor = os.open(temporary, flags, 0o600)
    except OSError as error:
        reject(f"cannot create exclusive temporary output: {error}")
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise
