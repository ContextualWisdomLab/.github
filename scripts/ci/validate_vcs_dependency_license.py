#!/usr/bin/env python3
"""Fail closed unless one exact organization VCS revision has a permitted license."""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from typing import Any


ORGANIZATION = "ContextualWisdomLab"
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
MAX_METADATA_BYTES = 1024 * 1024
REQUEST_TIMEOUT_SECONDS = 30
PERMITTED_SPDX_IDS = frozenset(
    {
        "MIT",
        "Apache-2.0",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "ISC",
        "MPL-2.0",
        "PostgreSQL",
    }
)


class RejectRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Reject redirects before urllib can contact their destination."""

    def redirect_request(
        self,
        req: Any,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        del req, fp, code, msg, headers, newurl
        raise RuntimeError("VCS dependency license metadata redirect is forbidden")


def _license_url(repository: str, commit: str) -> str:
    """Return the fixed-origin GitHub license URL for one exact revision."""
    if REPOSITORY_RE.fullmatch(repository) is None:
        raise ValueError("VCS dependency repository is malformed")
    if COMMIT_RE.fullmatch(commit) is None:
        raise ValueError("VCS dependency commit is not an exact lowercase SHA")
    return (
        f"https://api.github.com/repos/{ORGANIZATION}/{repository}/"
        f"license?ref={commit}"
    )


def _default_opener() -> urllib.request.OpenerDirector:
    """Build a no-proxy opener for the fixed public GitHub API request."""
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        RejectRedirectHandler(),
    )


def validate_license(
    repository: str,
    commit: str,
    *,
    opener: Any | None = None,
) -> str:
    """Return the permitted SPDX ID or fail closed on any metadata ambiguity."""
    url = _license_url(repository, commit)
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "ContextualWisdomLab-opencode-vcs-license-gate",
        },
    )
    client = opener if opener is not None else _default_opener()
    with client.open(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        if response.geturl() != url:
            raise RuntimeError("VCS dependency license metadata left the fixed GitHub origin")
        payload_bytes = response.read(MAX_METADATA_BYTES + 1)
    if len(payload_bytes) > MAX_METADATA_BYTES:
        raise RuntimeError("VCS dependency license metadata exceeded the size limit")
    try:
        payload = json.loads(payload_bytes.decode("utf-8", errors="strict"))
        spdx_id = payload["license"]["spdx_id"]
    except (KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("VCS dependency license metadata is malformed") from exc
    if not isinstance(spdx_id, str) or spdx_id not in PERMITTED_SPDX_IDS:
        raise ValueError(
            f"VCS dependency SPDX license {spdx_id!r} is not permitted"
        )
    return spdx_id


def main(argv: list[str] | None = None) -> int:
    """Validate CLI arguments and print only the authoritative SPDX identifier."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--commit", required=True)
    args = parser.parse_args(argv)
    try:
        spdx_id = validate_license(args.repository, args.commit)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"VCS dependency license validation failed: {exc}", file=sys.stderr)
        return 1
    print(spdx_id)
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised by the CLI boundary.
    raise SystemExit(main())
