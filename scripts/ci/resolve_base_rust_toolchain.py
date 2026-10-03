#!/usr/bin/env python3
"""Print the exact Rust release the trusted coverage image must install.

The pin is read only from the live-validated BASE commit, never from the pull
request head. An empty result keeps the image's Debian toolchain unchanged; a
base pin that is not an exact stable release (``stable``, ``nightly-*``, a
custom ``path``, or unparsable TOML) falls back to ``CENTRAL_RUST_TOOLCHAIN``.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import subprocess
import sys
import tomllib

SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
EXACT_RELEASE_RE = re.compile(r"1\.[0-9]{1,3}\.[0-9]{1,3}")
CENTRAL_RUST_TOOLCHAIN = "1.97.1"
PIN_FILES = ("rust-toolchain.toml", "rust-toolchain")


def _base_blob(repo_root: pathlib.Path, base_sha: str, path: str) -> str | None:
    """Read a candidate toolchain declaration from the exact base commit."""
    completed = subprocess.run(
        ["git", "-C", str(repo_root), "show", f"{base_sha}:{path}"],
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        return None
    return completed.stdout.decode("utf-8", errors="replace")


def _channel(content: str) -> str | None:
    """Extract a TOML or legacy channel without accepting custom toolchains."""
    try:
        toolchain = tomllib.loads(content).get("toolchain")
    except tomllib.TOMLDecodeError:
        # The legacy `rust-toolchain` file may be a bare channel line.
        lines = content.split()
        return lines[0] if len(lines) == 1 else None
    if not isinstance(toolchain, dict) or "path" in toolchain:
        return None
    channel = toolchain.get("channel")
    return channel if isinstance(channel, str) else None


def resolve(repo_root: pathlib.Path, base_sha: str) -> str:
    """Select an exact base release or the documented central fallback."""
    if not SHA_RE.fullmatch(base_sha):
        raise ValueError("base SHA must be a full 40-character commit id")
    for path in PIN_FILES:
        content = _base_blob(repo_root, base_sha, path)
        if content is None:
            continue
        channel = _channel(content)
        if channel and EXACT_RELEASE_RE.fullmatch(channel):
            return channel
        print(
            f"::warning::{path} at the base SHA does not pin an exact stable Rust release; "
            f"using the central {CENTRAL_RUST_TOOLCHAIN} toolchain.",
            file=sys.stderr,
        )
        return CENTRAL_RUST_TOOLCHAIN
    return ""


def main(argv: list[str] | None = None) -> int:
    """Print the base-bound toolchain and fail on invalid source identity."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", required=True, type=pathlib.Path)
    parser.add_argument("--base-sha", required=True)
    args = parser.parse_args(argv)
    try:
        print(resolve(args.repo_root, args.base_sha))
    except ValueError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
