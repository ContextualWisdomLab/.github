"""The native scanner must retain each architecture and fail on partial output."""

from pathlib import Path
import hashlib
import runpy
import subprocess
import zipfile

import pytest


SCAN = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/ci/scan_release_native_links.py"))


def _reader_fixture(path: Path, version: str) -> None:
    path.write_text(f"#!/bin/sh\nprintf 'Ubuntu LLVM version {version}\\n'\n")
    path.chmod(0o755)


def test_reader_ignores_path_and_binds_exact_executable(tmp_path, monkeypatch):
    trusted = tmp_path / "llvm-readobj-18"
    _reader_fixture(trusted, "18.1.3")
    attacker_root = tmp_path / "attacker"
    attacker_root.mkdir()
    _reader_fixture(attacker_root / "llvm-readobj", "18.1.3")
    monkeypatch.setitem(SCAN["_reader"].__globals__, "LLVM_READER_PATH", trusted)
    monkeypatch.setenv("PATH", str(attacker_root))

    assert SCAN["_reader"]() == {
        "path": str(trusted.resolve()),
        "version": "18.1.3",
        "sha256": hashlib.sha256(trusted.read_bytes()).hexdigest(),
    }


def test_reader_refuses_wrong_pinned_version(tmp_path, monkeypatch):
    reader = tmp_path / "llvm-readobj-18"
    _reader_fixture(reader, "19.1.0")
    monkeypatch.setitem(SCAN["_reader"].__globals__, "LLVM_READER_PATH", reader)
    monkeypatch.setenv("PATH", str(tmp_path))

    with pytest.raises(ValueError, match="version differs"):
        SCAN["_reader"]()


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
    analyzer = {"path": "/usr/lib/llvm-18/bin/llvm-readobj", "version": "18.1.3",
                "sha256": "b" * 64}
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
    report = SCAN["scan"](verified, tmp_path, "a" * 40, analyzer)
    assert len(report["wheels"]) == 12
    assert report["analyzer"] == analyzer
    sdist.write_bytes(b"changed")
    with pytest.raises(ValueError, match="bytes changed"):
        SCAN["scan"](verified, tmp_path, "a" * 40, analyzer)
