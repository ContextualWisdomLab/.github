"""The native scanner must retain each architecture and fail on partial output."""

from pathlib import Path
import runpy
import subprocess

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
