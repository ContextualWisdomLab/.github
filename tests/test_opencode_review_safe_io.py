"""Tests for fail-closed exclusive atomic review-evidence writes."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts/ci/opencode_review_safe_io.py"


def load_module() -> ModuleType:
    """Load the exact safe-I/O module without package import side effects."""
    spec = importlib.util.spec_from_file_location("opencode_review_safe_io", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


safe_io = load_module()


def reject(message: str) -> None:
    """Raise the same class of validation error the review CLIs wrap."""
    raise ValueError(message)


def test_atomic_write_replaces_destination_and_removes_temporary(tmp_path: Path) -> None:
    """A successful write must publish UTF-8 content and leave no temp sibling."""
    destination = tmp_path / "nested" / "gold.json"
    safe_io.atomic_write_text(destination, '{"ok":true}\n', reject)
    assert destination.read_text(encoding="utf-8") == '{"ok":true}\n'
    assert not destination.with_name(f".{destination.name}.tmp").exists()


def test_atomic_write_refuses_symlink_parent(tmp_path: Path) -> None:
    """A swapped parent directory must not redirect the published file."""
    real_parent = tmp_path / "real"
    real_parent.mkdir()
    link_parent = tmp_path / "link"
    link_parent.symlink_to(real_parent)
    with pytest.raises(ValueError, match="parent directory must not be a symbolic link"):
        safe_io.atomic_write_text(link_parent / "gold.json", "stolen\n", reject)
    assert not (real_parent / "gold.json").exists()


def test_atomic_write_refuses_preplanted_temporary_symlink(tmp_path: Path) -> None:
    """A planted temporary symlink must not be followed or replaced."""
    destination = tmp_path / "gold.json"
    outside = tmp_path / "outside.txt"
    outside.write_text("secret\n", encoding="utf-8")
    temporary = destination.with_name(f".{destination.name}.tmp")
    temporary.symlink_to(outside)
    with pytest.raises(ValueError, match="temporary output path must not be a symbolic link"):
        safe_io.atomic_write_text(destination, "overwrite\n", reject)
    assert outside.read_text(encoding="utf-8") == "secret\n"
    assert not destination.exists()


def test_atomic_write_unlinks_stale_regular_temporary(tmp_path: Path) -> None:
    """A leftover regular temporary file from a crashed write may be replaced."""
    destination = tmp_path / "gold.json"
    temporary = destination.with_name(f".{destination.name}.tmp")
    temporary.write_text("stale\n", encoding="utf-8")
    safe_io.atomic_write_text(destination, "fresh\n", reject)
    assert destination.read_text(encoding="utf-8") == "fresh\n"
    assert not temporary.exists()


def test_atomic_write_refuses_temporary_directory(tmp_path: Path) -> None:
    """A directory occupying the temporary name must fail closed."""
    destination = tmp_path / "gold.json"
    temporary = destination.with_name(f".{destination.name}.tmp")
    temporary.mkdir()
    with pytest.raises(ValueError, match="temporary output path must not be a directory"):
        safe_io.atomic_write_text(destination, "fresh\n", reject)


def test_atomic_write_wraps_exclusive_create_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Operating-system create failures must become stable validation errors."""

    def boom(*_args: object, **_kwargs: object) -> int:
        raise OSError("exclusive create blocked")

    monkeypatch.setattr(safe_io.os, "open", boom)
    with pytest.raises(ValueError, match="cannot create exclusive temporary output"):
        safe_io.atomic_write_text(tmp_path / "gold.json", "fresh\n", reject)


def test_atomic_write_cleans_temporary_after_write_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A mid-write exception must not leave a durable temporary sibling."""
    original_fdopen = safe_io.os.fdopen

    class ExplodingHandle:
        """Stand-in file object that fails after exclusive create succeeds."""

        def __init__(self, file_descriptor: int) -> None:
            self.file_descriptor = file_descriptor

        def write(self, _content: str) -> int:
            raise RuntimeError("disk full")

        def flush(self) -> None:
            return None

        def fileno(self) -> int:
            return self.file_descriptor

        def close(self) -> None:
            safe_io.os.close(self.file_descriptor)

        def __enter__(self) -> ExplodingHandle:
            return self

        def __exit__(self, *_args: object) -> None:
            self.close()
            return None

    def exploding_fdopen(file_descriptor: int, *_args: object, **_kwargs: object) -> ExplodingHandle:
        return ExplodingHandle(file_descriptor)

    monkeypatch.setattr(safe_io.os, "fdopen", exploding_fdopen)
    destination = tmp_path / "gold.json"
    with pytest.raises(RuntimeError, match="disk full"):
        safe_io.atomic_write_text(destination, "fresh\n", reject)
    assert not destination.with_name(f".{destination.name}.tmp").exists()
    assert not destination.exists()
    monkeypatch.setattr(safe_io.os, "fdopen", original_fdopen)


def test_atomic_write_ignores_cleanup_unlink_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed replace must still re-raise after a busy temporary unlink."""

    def fail_replace(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("replace failed")

    original_unlink = Path.unlink

    def busy_unlink(self: Path, missing_ok: bool = False) -> None:
        if self.name.endswith(".tmp"):
            raise OSError("temporary path busy")
        original_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(safe_io.os, "replace", fail_replace)
    monkeypatch.setattr(Path, "unlink", busy_unlink)
    with pytest.raises(RuntimeError, match="replace failed"):
        safe_io.atomic_write_text(tmp_path / "gold.json", "fresh\n", reject)


def test_public_safe_io_callables_have_docstrings() -> None:
    """Every production callable must remain beginner-readable."""
    missing = [
        name
        for name, value in vars(safe_io).items()
        if not name.startswith("_")
        and callable(value)
        and getattr(value, "__module__", None) == safe_io.__name__
        and not getattr(value, "__doc__", None)
    ]
    assert missing == []
