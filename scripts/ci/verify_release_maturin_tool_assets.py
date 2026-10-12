#!/usr/bin/env python3
"""Recheck pinned maturin release assets and native links before licence verdicts."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import tarfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

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
ASSET_FILENAMES = frozenset({
    "maturin-aarch64-unknown-linux-musl.tar.gz",
    "maturin-x86_64-unknown-linux-musl.tar.gz",
    "maturin-aarch64-apple-darwin.tar.gz",
    "maturin-x86_64-apple-darwin.tar.gz",
    "maturin-x86_64-pc-windows-msvc.zip",
})
GITHUB_RELEASE_HOST = "github.com"
GITHUB_RELEASE_CDN_HOST = "release-assets.githubusercontent.com"
GITHUB_RELEASE_PATH = "/PyO3/maturin/releases/download/v1.15.0/"


class _ExactReleaseRedirect(urllib.request.HTTPRedirectHandler):
    """Admit one credential-free redirect to the exact GitHub release CDN."""

    def http_error_302(self, request, response, code, message, headers):
        """Validate and follow one exact release redirect, closing its response."""
        try:
            location = headers.get("Location", "")
            try:
                redirect = urlsplit(location)
                redirect_port = redirect.port
            except ValueError as error:
                raise ValueError("maturin release redirect is not trusted") from error
            source = urlsplit(request.full_url)
            if (
                getattr(request, "_cwl_release_redirected", False)
                or source.scheme != "https"
                or source.hostname != GITHUB_RELEASE_HOST
                or redirect.scheme != "https"
                or redirect.hostname != GITHUB_RELEASE_CDN_HOST
                or redirect_port not in {None, 443}
                or redirect.username is not None
                or redirect.password is not None
                or not redirect.path.startswith("/")
                or redirect.fragment
            ):
                raise ValueError("maturin release redirect is not trusted")
            redirected = urllib.request.Request(
                location,
                headers={"User-Agent": "cwl-release-gate"},
                method="GET",
            )
            redirected._cwl_release_redirected = True
        finally:
            response.close()
        return self.parent.open(redirected, timeout=request.timeout)

    http_error_301 = http_error_302
    http_error_303 = http_error_302
    http_error_307 = http_error_302
    http_error_308 = http_error_302


def _download(filename: str) -> bytes:
    """Download one admitted release asset through the fixed GitHub CDN hop."""
    if filename not in ASSET_FILENAMES:
        raise ValueError("maturin asset name is unexpected")
    request = urllib.request.Request(
        f"https://{GITHUB_RELEASE_HOST}{GITHUB_RELEASE_PATH}{filename}",
        headers={"User-Agent": "cwl-release-gate"},
        method="GET",
    )
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), _ExactReleaseRedirect()
    )
    try:
        response = opener.open(request, timeout=60)
        try:
            if response.status != 200:
                raise ValueError(
                    f"maturin release download returned HTTP {response.status}"
                )
            raw = response.read(MAX_ASSET_BYTES + 1)
        finally:
            response.close()
    except urllib.error.HTTPError as error:
        try:
            raise ValueError(
                f"maturin release download returned HTTP {error.code}"
            ) from error
        finally:
            error.close()
    if len(raw) > MAX_ASSET_BYTES:
        raise ValueError("maturin release asset exceeds inspection limit")
    return raw


def _binary(raw: bytes, filename: str) -> bytes:
    """Extract the single bounded executable from an approved asset archive."""
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
        if filename not in ASSET_FILENAMES:
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
    """Verify fixed Maturin release assets from command-line inputs."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--asset-root", type=Path)
    args = parser.parse_args()
    evidence = json.loads(Path(__file__).with_name("release_maturin_tool_evidence.json").read_text())
    fetch = (lambda filename: (args.asset_root / filename).read_bytes()) if args.asset_root else _download
    verify_assets(evidence, _reader()["path"], fetch)


if __name__ == "__main__":
    main()
