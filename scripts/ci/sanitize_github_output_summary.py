#!/usr/bin/env python3
"""Redact secret-like values before writing multiline GitHub job outputs."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

SECRET_KEY_RE = re.compile(
    r"(?i)(?P<key>\b[A-Z0-9_.-]*(?:"
    r"AUTH[_-]?SESSION[_-]?HMAC[_-]?SECRET|"
    r"DATABASE[_-]?URL|DB[_-]?URL|CONNECTION[_-]?STRING|"
    r"SECRET|TOKEN|PASSWORD|PASSWD|"
    r"API[_-]?KEY|PRIVATE[_-]?KEY|ACCESS[_-]?KEY|ENCRYPTION[_-]?KEY"
    r")[A-Z0-9_.-]*\b)(?P<sep>\s*[:=]\s*)[^\n]*"
)
URL_CREDENTIAL_RE = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)([^/\s:@]+):([^@\s/]+)@")
AUTH_HEADER_RE = re.compile(r"(?i)\b(Authorization\s*[:=]\s*)(Bearer|Basic)\s+[^\s,;]+")


def sanitize_text(text: str) -> str:
    """Return a GitHub-output-safe version of a coverage evidence summary."""

    sanitized = SECRET_KEY_RE.sub(r"\g<key>\g<sep><redacted>", text)
    sanitized = URL_CREDENTIAL_RE.sub(r"\1<redacted>@", sanitized)
    return AUTH_HEADER_RE.sub(r"\1\2 <redacted>", sanitized)


def main() -> int:
    """Sanitize one coverage summary file into a GitHub-output-safe file."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()

    args.destination.write_text(
        sanitize_text(args.source.read_text(encoding="utf-8")),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
