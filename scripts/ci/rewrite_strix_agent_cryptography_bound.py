#!/usr/bin/env python3
"""Relax strix-agent wheel metadata so pip can install cryptography 50.0.0.

``strix-agent==1.5.3`` still declares ``cryptography<49,>=48.0.1``. Required
Strix is ``pull_request_target``, so protected ``main`` installs the
same-repository PR-head lock with ``pip install --require-hashes`` and no
``--no-deps``. That resolver re-applies the stale bound and fails
``ResolutionImpossible`` even though the compiled lock already pins
``cryptography==50.0.0`` (CVE-2026-69247 / CVE-2026-39892).

This helper rewrites only that ``Requires-Dist`` line inside an official
Apache-2.0 wheel, updates ``RECORD``, and rewrites the hashed lock to prefer
the patched wheel through ``--find-links``. Hashes remain required. The
missing-artifact Strix gate is unchanged.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import re
import sys
import zipfile
from pathlib import Path


STALE_CRYPTOGRAPHY_BOUND = "cryptography<49,>=48.0.1"
RELAXED_CRYPTOGRAPHY_BOUND = "cryptography>=48.0.1"
STRIX_AGENT_LOCK_RE = re.compile(
    r"^strix-agent(?:==1\.5\.3| @ \S+) \\(?:\n    --hash=sha256:[0-9a-f]{64}(?: \\)?)+",
    re.MULTILINE,
)
FIND_LINKS_RE = re.compile(r"^--find-links[ \t]+\S+[ \t]*$", re.MULTILINE)


def sha256_hex(data: bytes) -> str:
    """Return the lowercase SHA-256 hex digest of ``data``."""

    return hashlib.sha256(data).hexdigest()


def record_digest(data: bytes) -> str:
    """Return a PEP 376 ``sha256=`` digest for one RECORD member."""

    return "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode(
        "ascii"
    ).rstrip("=")


def zip_name_is_unsafe(name: str) -> bool:
    """Return whether a zip member path can escape the extraction root."""

    if not name or name.startswith("/") or "\x00" in name:
        return True
    parts = name.split("/")
    return any(part in {"", ".", ".."} for part in parts)


def relax_cryptography_requires_dist(metadata: str) -> str:
    """Replace the stale cryptography upper bound or accept an already-relaxed file."""

    if STALE_CRYPTOGRAPHY_BOUND in metadata:
        return metadata.replace(STALE_CRYPTOGRAPHY_BOUND, RELAXED_CRYPTOGRAPHY_BOUND, 1)
    if RELAXED_CRYPTOGRAPHY_BOUND in metadata:
        return metadata
    raise ValueError(
        "wheel METADATA does not declare the expected strix-agent cryptography bound"
    )


def update_record_entry(record: str, member: str, data: bytes) -> str:
    """Rewrite one RECORD line to match ``data`` and fail if the member is missing."""

    prefix = member + ","
    replacement = f"{member},{record_digest(data)},{len(data)}"
    updated: list[str] = []
    found = False
    for line in record.splitlines():
        if line.startswith(prefix):
            updated.append(replacement)
            found = True
            continue
        updated.append(line)
    if not found:
        raise ValueError(f"wheel RECORD does not list {member}")
    trailing = "\n" if record.endswith("\n") else ""
    return "\n".join(updated) + trailing


def patch_wheel(source: Path, destination: Path) -> str:
    """Write a METADATA-patched wheel and return its SHA-256 hex digest."""

    if not source.is_file() or source.is_symlink():
        raise ValueError(f"official wheel must be a regular file: {source}")

    metadata_name = ""
    record_name = ""
    metadata_bytes = b""
    members: list[tuple[zipfile.ZipInfo, bytes]] = []
    with zipfile.ZipFile(source) as archive:
        for info in archive.infolist():
            if zip_name_is_unsafe(info.filename):
                raise ValueError(f"refusing unsafe wheel member {info.filename!r}")
            payload = archive.read(info.filename)
            if info.filename.endswith(".dist-info/METADATA"):
                metadata_name = info.filename
                metadata_bytes = relax_cryptography_requires_dist(
                    payload.decode("utf-8")
                ).encode("utf-8")
                payload = metadata_bytes
            elif info.filename.endswith(".dist-info/RECORD"):
                record_name = info.filename
            members.append((info, payload))

    if not metadata_name or not record_name:
        raise ValueError("wheel is missing METADATA or RECORD")

    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w") as output:
        for info, payload in members:
            if info.filename == record_name:
                payload = update_record_entry(
                    payload.decode("utf-8"), metadata_name, metadata_bytes
                ).encode("utf-8")
            output.writestr(info, payload)
    return sha256_hex(destination.read_bytes())


def rewrite_lock_find_links(lock_text: str, find_links: list[str]) -> str:
    """Insert or replace leading ``--find-links`` lines after the uv header."""

    if not find_links:
        raise ValueError("at least one --find-links location is required")
    body = FIND_LINKS_RE.sub("", lock_text)
    body = re.sub(r"\n{3,}", "\n\n", body)
    header_end = 0
    lines = body.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if line.startswith("#"):
            header_end = index + 1
            continue
        break
    directive = "".join(f"--find-links {item}\n" for item in find_links) + "\n"
    return "".join(lines[:header_end]) + directive + "".join(lines[header_end:])


def rewrite_lock_strix_agent_hashes(
    lock_text: str, wheel_hash: str, wheel_url: str
) -> str:
    """Pin ``strix-agent`` to the patched wheel URL so pip cannot fetch PyPI."""

    if not re.fullmatch(r"[0-9a-f]{64}", wheel_hash):
        raise ValueError("patched wheel hash must be a 64-character SHA-256 hex digest")
    if ".." in wheel_url or "\n" in wheel_url or " " in wheel_url:
        raise ValueError("wheel URL must be a single path without traversal")
    if not (
        wheel_url.startswith("https://raw.githubusercontent.com/ContextualWisdomLab/.github/")
        or wheel_url.startswith("vendor/strix/")
    ):
        raise ValueError("wheel URL must be the published GitHub raw path or vendor/strix/")
    if "strix_agent-1.5.3-py3-none-manylinux_2_17_x86_64.whl" not in wheel_url:
        raise ValueError("wheel URL must name the 1.5.3 manylinux x86_64 wheel")
    replacement = f"strix-agent @ {wheel_url} \\\n    --hash=sha256:{wheel_hash}"
    updated, count = STRIX_AGENT_LOCK_RE.subn(replacement, lock_text, count=1)
    if count != 1:
        raise ValueError("lock does not contain exactly one strix-agent==1.5.3 hash block")
    return updated


def build_parser() -> argparse.ArgumentParser:
    """Return the command-line parser for wheel and lock rewriting."""

    parser = argparse.ArgumentParser(
        description="Patch strix-agent 1.5.3 cryptography metadata and lock hashes."
    )
    parser.add_argument("--input", type=Path, required=True, help="Official wheel path")
    parser.add_argument("--output", type=Path, required=True, help="Patched wheel path")
    parser.add_argument("--lock", type=Path, help="Hashed lock to rewrite")
    parser.add_argument(
        "--wheel-url",
        help="Direct patched-wheel URL or vendor/strix/ relative path",
    )
    parser.add_argument(
        "--find-links",
        action="append",
        default=[],
        help="optional pip --find-links location; repeatable",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Patch one official wheel and optionally rewrite the hashed lock."""

    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        digest = patch_wheel(args.input, args.output)
        if args.lock is not None:
            if not args.wheel_url:
                raise ValueError("rewriting the lock requires --wheel-url")
            if not args.lock.is_file() or args.lock.is_symlink():
                raise ValueError(f"lock must be a regular file: {args.lock}")
            lock_text = args.lock.read_text(encoding="utf-8")
            if args.find_links:
                lock_text = rewrite_lock_find_links(lock_text, args.find_links)
            rewritten = rewrite_lock_strix_agent_hashes(
                lock_text, digest, args.wheel_url
            )
            args.lock.write_text(rewritten, encoding="utf-8")
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(digest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
