#!/usr/bin/env python3
"""Rewrite the Strix hashed lock so pip-audit --disable-pip can read it.

The install lock pins the METADATA-patched ``strix-agent==1.5.3`` wheel by
direct URL so current ``main``'s resolver-based ``pip install --require-hashes``
does not fetch the official PyPI artifact. ``pip-audit --disable-pip`` rejects
URL requirements (``URL requirements cannot be pinned to a specific package
version``). This helper keeps every hash line and turns only the URL pin into
``name==version`` taken from the wheel filename.

The unhashed compile input is not rewritten here. The Python Security
workflow skips that file when the hashed sibling exists.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


URL_REQUIREMENT_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9_.-]+) @ (?P<url>\S+)(?P<tail> \\)?\s*$"
)
WHEEL_VERSION_RE = re.compile(
    r"(?P<dist>[A-Za-z0-9_]+)-(?P<version>\d+(?:\.\d+)*)-.*\.whl(?:\?.*)?$"
)


def version_from_wheel_url(url: str) -> str:
    """Return the wheel version encoded in a URL or vendor-relative path."""

    if ".." in url or "\n" in url or " " in url:
        raise ValueError("wheel URL must be a single path without traversal")
    filename = url.rsplit("/", 1)[-1]
    match = WHEEL_VERSION_RE.search(filename)
    if match is None:
        raise ValueError(f"wheel URL does not encode a package version: {url}")
    return match.group("version")


def normalize_lock_for_disable_pip(lock_text: str) -> str:
    """Replace URL pins with ``name==version`` and leave every other line intact."""

    rewritten: list[str] = []
    for line in lock_text.splitlines(keepends=True):
        stripped = line.rstrip("\n")
        newline = "\n" if line.endswith("\n") else ""
        match = URL_REQUIREMENT_RE.match(stripped)
        if match is None:
            rewritten.append(line)
            continue
        version = version_from_wheel_url(match.group("url"))
        tail = match.group("tail") or ""
        rewritten.append(f"{match.group('name')}=={version}{tail}{newline}")
    return "".join(rewritten)


def build_parser() -> argparse.ArgumentParser:
    """Return the command-line parser for lock normalization."""

    parser = argparse.ArgumentParser(
        description="Rewrite Strix URL pins so pip-audit --disable-pip can read them."
    )
    parser.add_argument("--input", type=Path, required=True, help="Hashed lock path")
    parser.add_argument("--output", type=Path, required=True, help="Normalized lock path")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Normalize one hashed lock for pip-audit --disable-pip."""

    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if not args.input.is_file() or args.input.is_symlink():
            raise ValueError(f"lock must be a regular file: {args.input}")
        normalized = normalize_lock_for_disable_pip(args.input.read_text(encoding="utf-8"))
        if "strix-agent==1.5.3" not in normalized:
            raise ValueError("normalized lock lost the strix-agent==1.5.3 pin")
        if "strix-agent @" in normalized:
            raise ValueError("normalized lock still contains a URL requirement")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(normalized, encoding="utf-8")
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
