"""Check the real post-Docker workspace repair without changing file owners."""

import os
from pathlib import Path
import stat
import sys
import textwrap

import pytest


WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/fast-mlsirm-cflite_pr.yml"


def test_cleanup_is_always_run_and_scoped_to_root_owned_workspace_entries(tmp_path, monkeypatch):
    workflow = WORKFLOW.read_text()
    step = workflow.split("      - name: Restore runner access to ClusterFuzzLite workspace\n", 1)[1]
    assert step.startswith("        if: ${{ always() }}\n")
    script = textwrap.dedent(step.split("<<'PY'\n", 1)[1].split("          PY\n", 1)[0])

    root = tmp_path / "workspace"
    root.mkdir()
    owned = root / "storage" / "fast-mlsirm"
    owned.mkdir(parents=True)
    regular = owned / "corpus"
    regular.write_text("retain evidence")
    outside = tmp_path / "outside"
    outside.mkdir()
    (owned / "link").symlink_to(outside, target_is_directory=True)
    hardlink = owned / "shared"
    hardlink.hardlink_to(regular)
    foreign = root / "foreign"
    foreign.mkdir()
    raced = root / "raced"
    raced.mkdir()
    (raced / "nested").mkdir()
    root_dev = os.stat(root).st_dev
    original_stat, original_fstat = os.stat, os.fstat
    changed = set()

    def fake_stat(path, *args, **kwargs):
        result = original_stat(path, *args, **kwargs)
        name = str(path)
        return type("Stat", (), {"st_dev": root_dev + (name == "foreign"),
                                    "st_ino": result.st_ino + (name == "raced"),
                                    "st_mode": result.st_mode,
                                    "st_uid": 1234 if name == str(root) else 0,
                                    "st_nlink": result.st_nlink})()

    def fake_fstat(fd):
        result = original_fstat(fd)
        return type("Stat", (), {"st_dev": root_dev, "st_ino": result.st_ino,
                                    "st_mode": result.st_mode,
                                    "st_uid": 1234 if result.st_ino == original_stat(root).st_ino else 0,
                                    "st_nlink": result.st_nlink})()

    monkeypatch.setattr(os, "stat", fake_stat)
    monkeypatch.setattr(os, "fstat", fake_fstat)
    monkeypatch.setattr(os, "fchown", lambda fd, uid, gid: changed.add(original_fstat(fd).st_ino))
    monkeypatch.setattr(sys, "argv", ["cleanup", str(root), "1234", "1234"])
    exec(compile(script, str(WORKFLOW), "exec"), {})
    assert changed == {original_stat(owned).st_ino, original_stat(owned.parent).st_ino}
    assert regular.read_text() == "retain evidence"
    assert (owned / "link").is_symlink()
    assert stat.S_ISDIR(original_stat(foreign).st_mode)


@pytest.mark.parametrize("case", ["root_user", "filesystem_root", "symlink_workspace"])
def test_cleanup_rejects_unsafe_workspace_identity(tmp_path, monkeypatch, case):
    workflow = WORKFLOW.read_text()
    step = workflow.split("      - name: Restore runner access to ClusterFuzzLite workspace\n", 1)[1]
    script = textwrap.dedent(step.split("<<'PY'\n", 1)[1].split("          PY\n", 1)[0])
    root = tmp_path / "workspace"
    root.mkdir()
    uid = "1234"
    if case == "root_user":
        uid = "0"
    elif case == "filesystem_root":
        root = Path("/")
    else:
        link = tmp_path / "borrowed"
        link.symlink_to(root, target_is_directory=True)
        root = link
    monkeypatch.setattr(sys, "argv", ["cleanup", str(root), uid, "1234"])
    monkeypatch.setattr(os, "fchown", lambda *args: pytest.fail("unsafe ownership mutation"))
    with pytest.raises(SystemExit, match="Unsafe ClusterFuzzLite workspace identity"):
        exec(compile(script, str(WORKFLOW), "exec"), {})
