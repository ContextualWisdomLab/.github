"""The native scanner must retain each architecture and fail on partial output."""

from pathlib import Path
import hashlib
import runpy
import subprocess
import zipfile

import pytest


SCAN = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/ci/scan_release_native_links.py"))


def test_universal_binary_requires_both_complete_architectures(monkeypatch):
    output = """File: binary
Format: Mach-O 64-bit x86-64
Arch: x86_64
AddressSize: 64bit
NeededLibraries [
  /usr/lib/libSystem.B.dylib
]
File: binary
Format: Mach-O arm64
Arch: aarch64
AddressSize: 64bit
NeededLibraries [
  /usr/lib/libSystem.B.dylib
]
"""
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, output, ""))
    links = SCAN["_links"](b"binary", "universal2-apple-darwin", "llvm-readobj")
    assert [row["arch"] for row in links] == ["aarch64", "x86_64"]
    assert all(row["needed"] == ["/usr/lib/libSystem.B.dylib"] for row in links)

    truncated = output[:output.index("File: binary", 1)]
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, truncated, ""))
    with pytest.raises(ValueError, match="architecture differs"):
        SCAN["_links"](b"binary", "universal2-apple-darwin", "llvm-readobj")


def test_scan_rebinds_all_thirteen_distribution_bytes(tmp_path, monkeypatch):
    monkeypatch.setitem(SCAN["scan"].__globals__, "_links", lambda binary, target, reader: [])
    rows = []
    for target in SCAN["TARGET_ARCHES"]:
        for version in ("3.12", "3.13", "3.14"):
            leg = f"{target}-py{version}"
            path = tmp_path / f"{leg}.whl"
            suffix = "pyd" if "windows" in target else "so"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr(f"fast_mlsirm/_core.fixture.{suffix}", b"\x7fELFfixture")
            rows.append({"leg": leg, "file": path.name,
                         "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    sdist = tmp_path / "source.tar.gz"
    sdist.write_bytes(b"source")
    rows.append({"leg": "sdist", "file": sdist.name,
                 "sha256": hashlib.sha256(sdist.read_bytes()).hexdigest()})
    verified = {"verified_distributions": rows}
    assert len(SCAN["scan"](verified, tmp_path, "a" * 40, "reader")["wheels"]) == 12
    sdist.write_bytes(b"changed")
    with pytest.raises(ValueError, match="bytes changed"):
        SCAN["scan"](verified, tmp_path, "a" * 40, "reader")
