"""Fail-closed hash validation for trusted ``uv export`` output."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.ci import materialize_base_python_requirements as materializer


def test_uv_export_requires_a_hash_on_each_requirement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A global require-hashes directive cannot replace per-requirement hashes."""

    def fake_git(_repo_root: Path, *args: str) -> bytes:
        assert args[0] == "show"
        return b"version = 1\n" if args[1].endswith(":uv.lock") else b"[project]\n"

    malformed_export = b"--require-hashes\ndemo==1\n"
    monkeypatch.setattr(materializer, "_git", fake_git)
    monkeypatch.setattr(materializer, "_install_trusted_uv", lambda: "/trusted/uv")
    monkeypatch.setattr(
        materializer,
        "_run_uv_export",
        lambda _work_dir, _uv_path: subprocess.CompletedProcess(
            ["uv", "export"],
            0,
            malformed_export,
            b"",
        ),
    )

    with pytest.raises(RuntimeError, match="not fully hash-pinned"):
        materializer._export_uv_lock(tmp_path, "a" * 40, "uv.lock")
