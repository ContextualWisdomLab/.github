"""The native scanner must retain each architecture and fail on partial output."""

import hashlib
import json
import runpy
import subprocess
import sys
import warnings
import zipfile
from pathlib import Path

import pytest

SCAN = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/ci/scan_release_native_links.py"))


def _reader_fixture(path: Path, version: str) -> None:
    path.write_text(f"#!/bin/sh\nprintf 'Ubuntu LLVM version {version}\\n'\n")
    path.chmod(0o755)


def _distribution_case(root: Path) -> tuple[dict, list[dict]]:
    rows = []
    for target in SCAN["TARGET_ARCHES"]:
        for version in ("3.12", "3.13", "3.14"):
            leg = f"{target}-py{version}"
            path = root / f"{leg}.whl"
            suffix = "pyd" if "windows" in target else "so"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr(f"fast_mlsirm/_core.fixture.{suffix}", b"\x7fELFfixture")
            rows.append({"leg": leg, "file": path.name,
                         "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    sdist = root / "source.tar.gz"
    sdist.write_bytes(b"source")
    rows.append({"leg": "sdist", "file": sdist.name,
                 "sha256": hashlib.sha256(sdist.read_bytes()).hexdigest()})
    return {"verified_distributions": rows}, rows


def _replace_wheel(root: Path, row: dict, members: list[tuple[str, bytes]]) -> None:
    path = root / row["file"]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(path, "w") as archive:
            for name, data in members:
                archive.writestr(name, data)
    row["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()


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


def test_reader_refuses_missing_relative_and_ambiguous_identity(tmp_path, monkeypatch):
    reader_globals = SCAN["_reader"].__globals__
    monkeypatch.setitem(reader_globals, "LLVM_READER_PATH", tmp_path / "missing")
    with pytest.raises(ValueError, match="unavailable"):
        SCAN["_reader"]()

    monkeypatch.chdir(tmp_path)
    relative = Path("llvm-readobj-18")
    _reader_fixture(relative, "18.1.3")
    monkeypatch.setitem(reader_globals, "LLVM_READER_PATH", relative)
    with pytest.raises(ValueError, match="unavailable"):
        SCAN["_reader"]()

    absolute = relative.resolve()
    monkeypatch.setitem(reader_globals, "LLVM_READER_PATH", absolute)
    _reader_fixture(absolute, "18.1.3\nUbuntu LLVM version 18.1.3")
    with pytest.raises(ValueError, match="version differs"):
        SCAN["_reader"]()

    _reader_fixture(absolute, "18.1.3" + " " * 4097)
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
    assert [row["arch"] for row in SCAN["_links"](
        b"binary", "universal2-apple-darwin", "llvm-readobj", allow_subset=True
    )] == ["x86_64"]


def test_release_link_review_accepts_only_named_external_runtimes():
    review = SCAN["_review_link"]
    member = "fast_mlsirm/_core.cpython-314-darwin.so"
    assert review("libc.so.6", "x86_64-unknown-linux-gnu",
                  "x86_64-unknown-linux-gnu-py3.14", member)["kind"] == "system-runtime"
    assert review("/System/Library/Frameworks/Foundation.framework/Versions/C/Foundation",
                  "universal2-apple-darwin", "universal2-apple-darwin-py3.14",
                  member)["kind"] == "system-runtime"
    assert review("@rpath/fast_mlsirm._core.cpython-314-darwin.so",
                  "universal2-apple-darwin", "universal2-apple-darwin-py3.14",
                  member)["kind"] == "self-install-name"
    assert review("python314.dll", "x86_64-pc-windows-msvc",
                  "x86_64-pc-windows-msvc-py3.14", member)["kind"] == "interpreter-runtime"
    assert review("api-ms-win-core-synch-l1-2-0.dll", "x86_64-pc-windows-msvc",
                  "x86_64-pc-windows-msvc-py3.14", member)["kind"] == "system-runtime"
    assert review("VCRUNTIME140_1.dll", "x86_64-pc-windows-msvc",
                  "x86_64-pc-windows-msvc-py3.14", member)["kind"] == "external-runtime"
    with pytest.raises(ValueError, match="unreviewed native link"):
        review("libc.so.6", "unsupported-target", "unsupported-py3.14", member)
    for target, name in (("x86_64-unknown-linux-gnu", "libmystery.so"),
                         ("universal2-apple-darwin", "@rpath/foreign.dylib"),
                         ("x86_64-pc-windows-msvc", "foreign.dll")):
        with pytest.raises(ValueError, match="unreviewed native link"):
            review(name, target, f"{target}-py3.14", member)


def test_link_parser_refuses_oversized_partial_wrong_format_and_malformed_output(monkeypatch):
    with pytest.raises(ValueError, match="extension exceeds"):
        SCAN["_links"](b"x" * (128 * 1024 * 1024 + 1),
                       "x86_64-unknown-linux-gnu", "llvm-readobj")

    def completed(output: str):
        return subprocess.CompletedProcess([], 0, output, "")

    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: completed("x" * (2 * 1024 * 1024 + 1)))
    with pytest.raises(ValueError, match="output exceeds"):
        SCAN["_links"](b"binary", "x86_64-unknown-linux-gnu", "llvm-readobj")

    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: completed("File: binary\nNeededLibraries [\n"))
    with pytest.raises(ValueError, match="output is incomplete"):
        SCAN["_links"](b"binary", "x86_64-unknown-linux-gnu", "llvm-readobj")

    wrong_format = "File: binary\nFormat: COFF\nArch: x86_64\nNeededLibraries [\nlibc.so.6\n]\n"
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: completed(wrong_format))
    with pytest.raises(ValueError, match="format differs"):
        SCAN["_links"](b"binary", "x86_64-unknown-linux-gnu", "llvm-readobj")

    for needed in ("  ", "bad\x01name"):
        malformed = f"File: binary\nFormat: ELF64\nArch: x86_64\nNeededLibraries [\n{needed}\n]\n"
        monkeypatch.setattr(subprocess, "run", lambda *args, output=malformed, **kwargs: completed(output))
        with pytest.raises(ValueError, match="name is malformed"):
            SCAN["_links"](b"binary", "x86_64-unknown-linux-gnu", "llvm-readobj")


def test_scan_rebinds_all_thirteen_distribution_bytes(tmp_path, monkeypatch):
    monkeypatch.setitem(SCAN["scan"].__globals__, "_links", lambda binary, target, reader: [])
    analyzer = {"path": "/usr/lib/llvm-18/bin/llvm-readobj", "version": "18.1.3",
                "sha256": "b" * 64}
    verified, rows = _distribution_case(tmp_path)
    report = SCAN["scan"](verified, tmp_path, "a" * 40, analyzer)
    assert len(report["wheels"]) == 12
    assert report["analyzer"] == analyzer
    (tmp_path / "source.tar.gz").write_bytes(b"changed")
    with pytest.raises(ValueError, match="bytes changed"):
        SCAN["scan"](verified, tmp_path, "a" * 40, analyzer)


def test_scan_records_review_for_each_link_and_refuses_unknown(tmp_path, monkeypatch):
    names = {"x86_64-unknown-linux-gnu": "libc.so.6",
             "aarch64-unknown-linux-gnu": "libc.so.6",
             "universal2-apple-darwin": "/usr/lib/libSystem.B.dylib",
             "x86_64-pc-windows-msvc": "KERNEL32.dll"}
    def links(binary, target, reader):
        return [{"arch": arch, "format": "native", "needed": [names[target]]}
                for arch in sorted(SCAN["TARGET_ARCHES"][target])]
    monkeypatch.setitem(SCAN["scan"].__globals__, "_links", links)
    verified, _ = _distribution_case(tmp_path)
    analyzer = {"path": "/reader", "version": "18.1.3", "sha256": "b" * 64}
    report = SCAN["scan"](verified, tmp_path, "a" * 40, analyzer)
    assert report["schema"] == "cwl.release-native-links/2"
    assert all(len(link["reviews"]) == len(link["needed"]) == 1
               for wheel in report["wheels"] for link in wheel["links"])
    names["x86_64-pc-windows-msvc"] = "foreign.dll"
    with pytest.raises(ValueError, match="unreviewed native link"):
        SCAN["scan"](verified, tmp_path, "a" * 40, analyzer)


def test_scan_refuses_malformed_sets_and_distribution_identities(tmp_path, monkeypatch):
    monkeypatch.setitem(SCAN["scan"].__globals__, "_links", lambda binary, target, reader: [])
    analyzer = {"path": "/reader", "version": "18.1.3", "sha256": "b" * 64}

    for name, mutate in (
        ("source", lambda verified, rows: (verified, "x" * 40)),
        ("row-count", lambda verified, rows: ({"verified_distributions": rows[:-1]}, "a" * 40)),
        ("duplicate-leg", lambda verified, rows: (verified | {"verified_distributions": rows[:-1] + [{**rows[-1], "leg": rows[0]["leg"]}]}, "a" * 40)),
        ("no-sdist", lambda verified, rows: (verified | {"verified_distributions": rows[:-1] + [{**rows[-1], "leg": "extra-py3.12"}]}, "a" * 40)),
    ):
        root = tmp_path / name
        root.mkdir()
        verified, rows = _distribution_case(root)
        candidate, source_sha = mutate(verified, rows)
        with pytest.raises(ValueError, match="set is incomplete"):
            SCAN["scan"](candidate, root, source_sha, analyzer)

    for name, change in (
        ("bad-leg", {"leg": 1}),
        ("bad-file", {"file": "../escape.whl"}),
        ("bad-sha", {"sha256": "0"}),
    ):
        root = tmp_path / name
        root.mkdir()
        verified, rows = _distribution_case(root)
        rows[0].update(change)
        with pytest.raises(ValueError, match="invalid verified distribution identity"):
            SCAN["scan"](verified, root, "a" * 40, analyzer)


def test_scan_refuses_wrong_paths_targets_and_wheel_members(tmp_path, monkeypatch):
    monkeypatch.setitem(SCAN["scan"].__globals__, "_links", lambda binary, target, reader: [])
    analyzer = {"path": "/reader", "version": "18.1.3", "sha256": "b" * 64}

    root = tmp_path / "missing"
    root.mkdir()
    verified, rows = _distribution_case(root)
    (root / rows[0]["file"]).unlink()
    with pytest.raises(ValueError, match="bytes changed"):
        SCAN["scan"](verified, root, "a" * 40, analyzer)

    root = tmp_path / "symlink"
    root.mkdir()
    verified, rows = _distribution_case(root)
    path = root / rows[0]["file"]
    target = root / "target.whl"
    path.rename(target)
    path.symlink_to(target)
    with pytest.raises(ValueError, match="bytes changed"):
        SCAN["scan"](verified, root, "a" * 40, analyzer)

    root = tmp_path / "sdist"
    root.mkdir()
    verified, rows = _distribution_case(root)
    old = root / rows[-1]["file"]
    new = root / "source.zip"
    old.rename(new)
    rows[-1]["file"] = new.name
    with pytest.raises(ValueError, match="sdist identity"):
        SCAN["scan"](verified, root, "a" * 40, analyzer)

    root = tmp_path / "target"
    root.mkdir()
    verified, rows = _distribution_case(root)
    rows[0]["leg"] = "unknown-py3.12"
    with pytest.raises(ValueError, match="unexpected release wheel target"):
        SCAN["scan"](verified, root, "a" * 40, analyzer)

    variants = (
        ("duplicate", [("fast_mlsirm/_core.fixture.so", b"\x7fELF"),
                       ("fast_mlsirm/_core.fixture.so", b"\x7fELF")], "duplicate wheel member"),
        ("unsafe", [("../fast_mlsirm/_core.fixture.so", b"\x7fELF")], "unsafe wheel member"),
        ("missing-native", [("fast_mlsirm/readme.txt", b"text")], "missing or ambiguous"),
        ("ambiguous-native", [("fast_mlsirm/_core.one.so", b"\x7fELF"),
                              ("fast_mlsirm/_core.two.so", b"\x7fELF")], "missing or ambiguous"),
        ("extra-native", [("fast_mlsirm/_core.fixture.so", b"\x7fELF"),
                          ("fast_mlsirm/helper.dll", b"MZhelper")], "unaccounted bundled native member"),
    )
    for name, members, message in variants:
        root = tmp_path / name
        root.mkdir()
        verified, rows = _distribution_case(root)
        _replace_wheel(root, rows[0], members)
        with pytest.raises(ValueError, match=message):
            SCAN["scan"](verified, root, "a" * 40, analyzer)


def test_main_writes_once_to_a_new_report(tmp_path, monkeypatch):
    verified = tmp_path / "verified.json"
    verified.write_text(json.dumps({"verified_distributions": []}))
    output = tmp_path / "native.json"
    report = {"schema": "cwl.release-native-links/2", "wheels": []}
    monkeypatch.setitem(SCAN["main"].__globals__, "_reader", lambda: {"path": "/reader"})
    monkeypatch.setitem(SCAN["main"].__globals__, "scan", lambda *args: report)
    monkeypatch.setattr(sys, "argv", ["scan_release_native_links.py",
                                      "--verified-distributions", str(verified),
                                      "--distribution-root", str(tmp_path),
                                      "--source-sha", "a" * 40,
                                      "--output", str(output)])
    SCAN["main"]()
    assert json.loads(output.read_text()) == report
    with pytest.raises(ValueError, match="already exists"):
        SCAN["main"]()
