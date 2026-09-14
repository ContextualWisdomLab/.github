"""Regression coverage for non-blocking rejection of special output files."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from scripts.ci import materialize_base_python_requirements as materializer


@pytest.fixture(autouse=True)
def _empty_base_tree(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep FIFO rejection independent of Git repository materialization."""

    monkeypatch.setattr(materializer, "_git", lambda *_args: b"")


def _one_lock() -> list[tuple[str, bytes]]:
    """Return one deterministic trusted lock fixture."""

    return [("requirements.lock", b"demo==1 --hash=sha256:" + b"a" * 64 + b"\n")]


def test_materializer_rejects_existing_fifo_without_blocking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An existing FIFO is opened non-blocking and rejected before trusted writes."""

    output_directory = tmp_path / "generated_locks"
    output_directory.mkdir()
    fifo_path = output_directory / "requirements-000.txt"
    os.mkfifo(fifo_path)
    monkeypatch.setattr(
        materializer,
        "_base_python_inputs",
        lambda *_args: (_one_lock(), []),
    )

    real_open = materializer.os.open
    existing_open_flags: list[int] = []

    def require_nonblocking_existing(
        path: object, flags: int, *args: object, **kwargs: object
    ) -> int:
        if path == "requirements-000.txt" and not flags & os.O_CREAT:
            existing_open_flags.append(flags)
            if not flags & os.O_NONBLOCK:
                raise AssertionError("existing output must be opened non-blocking")
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(materializer.os, "open", require_nonblocking_existing)

    with pytest.raises(ValueError, match="singly linked regular files"):
        materializer.materialize(tmp_path, "a" * 40, output_directory)

    assert len(existing_open_flags) == 1
    assert existing_open_flags[0] & os.O_NONBLOCK
    assert fifo_path.exists()
