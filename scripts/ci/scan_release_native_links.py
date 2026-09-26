#!/usr/bin/env python3
"""Inventory dynamic links in the exact, already verified release wheels."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from pathlib import PurePosixPath
import re
import shutil
import stat
import subprocess
import tempfile
import zipfile


LINK_BLOCK = re.compile(
    r"^File: [^\n]+\nFormat: ([^\n]+)\nArch: ([^\n]+)\n.*?^NeededLibraries \[\n(.*?)^\]$",
    re.MULTILINE | re.DOTALL,
)
TARGET_ARCHES = {
    "x86_64-unknown-linux-gnu": {"x86_64"},
    "aarch64-unknown-linux-gnu": {"aarch64"},
    "universal2-apple-darwin": {"x86_64", "aarch64"},
    "x86_64-pc-windows-msvc": {"x86_64"},
}
NATIVE_MAGIC = (b"\x7fELF", b"MZ", b"\x00asm", b"!<arch>\n",
                b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf",
                b"\xce\xfa\xed\xfe", b"\xcf\xfa\xed\xfe",
                b"\xca\xfe\xba\xbe", b"\xca\xfe\xba\xbf",
                b"\xbe\xba\xfe\xca", b"\xbf\xba\xfe\xca")


def _reader() -> str:
    for name in ("llvm-readobj", "llvm-readobj-19", "llvm-readobj-18", "llvm-readobj-17", "llvm-readobj-16"):
        found = shutil.which(name)
        if found:
            return found
    raise ValueError("llvm-readobj is required to inspect every release platform")


def _links(binary: bytes, target: str, reader: str) -> list[dict]:
    if len(binary) > 128 * 1024 * 1024:
        raise ValueError("release native extension exceeds inspection limit")
    with tempfile.NamedTemporaryFile() as temporary:
        temporary.write(binary)
        temporary.flush()
        result = subprocess.run([reader, "--needed-libs", temporary.name],
                                capture_output=True, text=True, timeout=60, check=True)
    if len(result.stdout) > 2 * 1024 * 1024:
        raise ValueError("native link output exceeds inspection limit")
    blocks = LINK_BLOCK.findall(result.stdout)
    if (len(blocks) != len(result.stdout.split("NeededLibraries [")) - 1
            or len(blocks) != len(result.stdout.split("File: ")) - 1):
        raise ValueError("native link output is incomplete")
    arches = {arch for _, arch, _ in blocks}
    if arches != TARGET_ARCHES[target] or len(blocks) != len(arches):
        raise ValueError("native extension architecture differs from release target")
    expected_format = ("elf" if "linux" in target else
                       "Mach-O" if "darwin" in target else "COFF")
    if any(expected_format.lower() not in fmt.lower() for fmt, _, _ in blocks):
        raise ValueError("native extension format differs from release target")
    result_rows = []
    for fmt, arch, body in blocks:
        needed = [line.strip() for line in body.splitlines()]
        if any(not line or re.search(r"[\x00-\x1f]", line) for line in needed):
            raise ValueError("native link name is malformed")
        result_rows.append({"format": fmt, "arch": arch, "needed": needed})
    return sorted(result_rows, key=lambda row: row["arch"])


def scan(verified: dict, root: Path, source_sha: str, reader: str) -> dict:
    rows = verified.get("verified_distributions") if isinstance(verified, dict) else None
    if (not re.fullmatch(r"[0-9a-f]{40}", source_sha)
            or not isinstance(rows, list) or len(rows) != 13
            or len({row.get("leg") for row in rows if isinstance(row, dict)}) != 13
            or sum(row.get("leg") == "sdist" for row in rows if isinstance(row, dict)) != 1):
        raise ValueError("verified distribution set is incomplete")
    wheels = []
    for row in rows:
        leg, filename, sha = row["leg"], row["file"], row["sha256"]
        if (not isinstance(leg, str) or not isinstance(filename, str)
                or not re.fullmatch(r"[A-Za-z0-9_.+-]+", filename)
                or not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha)):
            raise ValueError("invalid verified distribution identity")
        path = root / filename
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"{leg}: verified distribution bytes changed")
        with path.open("rb") as stream:
            actual_sha = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual_sha != sha:
            raise ValueError(f"{leg}: verified distribution bytes changed")
        if leg == "sdist":
            if not filename.endswith(".tar.gz"):
                raise ValueError("verified sdist identity differs")
            continue
        target = leg.rsplit("-py", 1)[0]
        if target not in TARGET_ARCHES or not filename.endswith(".whl"):
            raise ValueError("unexpected release wheel target")
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            names = [entry.filename for entry in entries]
            if len(names) != len(set(names)):
                raise ValueError(f"{leg}: duplicate wheel member")
            native = set()
            for entry in entries:
                member = PurePosixPath(entry.filename)
                mode = entry.external_attr >> 16
                if (not entry.filename or entry.filename.startswith("/") or "\\" in entry.filename
                        or str(member) != entry.filename or ".." in member.parts or entry.is_dir()
                        or stat.S_ISLNK(mode) or stat.S_IFMT(mode) not in (0, stat.S_IFREG)):
                    raise ValueError(f"{leg}: unsafe wheel member")
                with archive.open(entry) as stream:
                    magic = stream.read(8)
                if (magic.startswith(NATIVE_MAGIC)
                        or entry.filename.lower().endswith(
                            (".so", ".pyd", ".dll", ".dylib", ".a", ".lib", ".exe", ".wasm"))):
                    native.add(entry.filename)
            members = [entry for entry in entries if entry.filename.startswith("fast_mlsirm/_core.")
                       and entry.filename.endswith((".so", ".pyd"))]
            if len(members) != 1 or members[0].file_size > 128 * 1024 * 1024:
                raise ValueError(f"{leg}: native extension is missing or ambiguous")
            if native != {members[0].filename}:
                raise ValueError(f"{leg}: unaccounted bundled native member")
            binary = archive.read(members[0])
        wheels.append({"leg": leg, "file": filename, "sha256": sha,
                       "member": members[0].filename,
                       "member_sha256": hashlib.sha256(binary).hexdigest(),
                       "links": _links(binary, target, reader)})
    if len(wheels) != 12:
        raise ValueError("release native wheel set is incomplete")
    return {"schema": "cwl.release-native-links/1", "source_sha": source_sha,
            "wheels": sorted(wheels, key=lambda row: row["leg"])}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verified-distributions", required=True)
    parser.add_argument("--distribution-root", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists() or output.is_symlink():
        raise ValueError("native link report already exists")
    report = scan(json.loads(Path(args.verified_distributions).read_text()),
                  Path(args.distribution_root), args.source_sha, _reader())
    output.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")


if __name__ == "__main__":
    main()
