#!/usr/bin/env python3
"""Recheck pinned maturin release assets and native links before licence verdicts."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import tarfile
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen

try:
    from scripts.ci.release_dependency_gate import classify_platform_link
    from scripts.ci.scan_release_native_links import _links, _reader
except ImportError:  # pragma: no cover - trusted direct `python3 -I` invocation
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from release_dependency_gate import classify_platform_link
    from scan_release_native_links import _links, _reader


ASSET_KEYS = {
    "aarch64-unknown-linux-gnu", "x86_64-unknown-linux-gnu",
    "universal2-apple-darwin/ARM64", "universal2-apple-darwin/X64",
    "x86_64-pc-windows-msvc",
}
MAX_ASSET_BYTES = 16 * 1024 * 1024
MAX_BINARY_BYTES = 32 * 1024 * 1024


def _download(filename: str) -> bytes:
    url = f"https://github.com/PyO3/maturin/releases/download/v1.15.0/{filename}"
    if not url.startswith("https://"):
        raise ValueError("Invalid URL scheme")  # pragma: no cover
    with urlopen(Request(url, headers={"User-Agent": "cwl-release-gate"}), timeout=60) as response:
        raw = response.read(MAX_ASSET_BYTES + 1)
    if len(raw) > MAX_ASSET_BYTES:
        raise ValueError("maturin release asset exceeds inspection limit")
    return raw


def _binary(raw: bytes, filename: str) -> bytes:
    if filename.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members = archive.infolist()
            if len(members) != 1 or members[0].filename != "maturin.exe" or members[0].file_size > MAX_BINARY_BYTES:
                raise ValueError("maturin asset has an unexpected member")
            binary = archive.read(members[0])
    else:
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
            members = archive.getmembers()
            if (len(members) != 1 or members[0].name != "maturin"
                    or not members[0].isfile() or members[0].size > MAX_BINARY_BYTES):
                raise ValueError("maturin asset has an unexpected member")
            with archive.extractfile(members[0]) as stream:
                binary = stream.read(MAX_BINARY_BYTES + 1)
    if len(binary) > MAX_BINARY_BYTES:
        raise ValueError("maturin executable exceeds inspection limit")
    return binary


def verify_assets(evidence: dict, reader: str, fetch=_download) -> None:
    """Require exact official asset bytes and the reviewed dynamic link set."""
    if (evidence.get("schema") != "cwl.release-maturin-tool/1"
            or evidence.get("tag") != "v1.15.0"
            or set(evidence.get("assets", {})) != ASSET_KEYS):
        raise ValueError("maturin asset evidence is incomplete")
    for key, asset in sorted(evidence["assets"].items()):
        filename = asset["asset_filename"]
        if filename not in {
            "maturin-aarch64-unknown-linux-musl.tar.gz",
            "maturin-x86_64-unknown-linux-musl.tar.gz",
            "maturin-aarch64-apple-darwin.tar.gz",
            "maturin-x86_64-apple-darwin.tar.gz",
            "maturin-x86_64-pc-windows-msvc.zip",
        }:
            raise ValueError(f"{key}: maturin asset name is unexpected")
        raw = fetch(filename)
        if len(raw) > MAX_ASSET_BYTES or hashlib.sha256(raw).hexdigest() != asset["asset_sha256"]:
            raise ValueError(f"{key}: maturin asset bytes differ")
        binary = _binary(raw, filename)
        if hashlib.sha256(binary).hexdigest() != asset["binary_sha256"]:
            raise ValueError(f"{key}: maturin executable bytes differ")
        target = key.split("/")[0]
        links = _links(binary, target, reader, allow_subset=True)
        expected_arch = "aarch64" if ("aarch64" in key or key.endswith("/ARM64")) else "x86_64"
        if (len(links) != 1 or links[0]["arch"] != expected_arch
                or [{"arch": row["arch"], "needed": row["needed"]} for row in links]
                != asset.get("native_links")):
            raise ValueError(f"{key}: maturin native links differ")
        for name in links[0]["needed"]:
            if classify_platform_link(name, target, f"{target}-py3.12", "maturin") is None:
                raise ValueError(f"{key}: unreviewed maturin native link {name!r}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--asset-root", type=Path)
    args = parser.parse_args()
    evidence = json.loads(Path(__file__).with_name("release_maturin_tool_evidence.json").read_text())
    fetch = (lambda filename: (args.asset_root / filename).read_bytes()) if args.asset_root else _download
    verify_assets(evidence, _reader()["path"], fetch)


if __name__ == "__main__":
    main()
