#!/usr/bin/env python3
"""Resolve Strix target-repository visibility with fail-closed retries.

The required Strix job used a single ``gh api`` call. A transient GitHub API
flake (timeout, 5xx, 429, empty/non-boolean body, or authenticated HTTP 403
rate-limit) aborted the scan before it started. This helper retries those
transient failures a few times with short backoff. A real 401/403/404 on a
missing or unauthorized repository stays fail-closed and is never treated as
success or as a source finding.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

TARGET_REPOSITORY_RE = re.compile(r"^ContextualWisdomLab/[A-Za-z0-9_.-]+$")
HTTP_STATUS_RE = re.compile(r"\bHTTP[ /](\d{3})\b", re.IGNORECASE)
TOKEN_RE = re.compile(r"(gh[pousr]_[A-Za-z0-9]+|github_pat_[A-Za-z0-9_]+)")
PERMANENT_HTTP_STATUSES = frozenset({401, 403, 404})
TRANSIENT_HTTP_STATUSES = frozenset({429, 500, 502, 503, 504})
RATE_LIMIT_MARKERS = (
    "api rate limit exceeded",
    "secondary rate limit",
)
TRANSIENT_MARKERS = (
    "timeout",
    "timed out",
    "connection reset",
    "connection refused",
    "connection timed out",
    "context deadline exceeded",
    "gateway timeout",
    "i/o timeout",
    "unexpected end of json",
    "unexpected eof",
    "temporary failure",
    "server error",
    "service unavailable",
)
DEFAULT_MAX_ATTEMPTS = 4
DEFAULT_TIMEOUT_SECONDS = 20.0
MAX_BACKOFF_SECONDS = 4.0


class VisibilityResolutionError(RuntimeError):
    """Fail-closed visibility lookup that must stop the Strix job."""


class VisibilityCommandError(RuntimeError):
    """A ``gh api`` invocation failed before a boolean visibility was parsed."""


def scrub_sensitive_data(text: str) -> str:
    """Redact GitHub token prefixes before they can reach job logs."""
    return TOKEN_RE.sub("<redacted>", text)


def validate_target_repository(repository: str) -> str:
    """Return a ContextualWisdomLab repository name or fail closed."""
    candidate = (repository or "").strip()
    if not TARGET_REPOSITORY_RE.fullmatch(candidate):
        raise VisibilityResolutionError(
            "Strix target repository must belong to ContextualWisdomLab."
        )
    return candidate


def parse_private_flag(raw: str | None) -> str | None:
    """Return ``true`` or ``false`` when visibility is an exact boolean."""
    value = (raw or "").strip()
    if value in {"true", "false"}:
        return value
    return None


def is_github_rate_limit_failure(message: str) -> bool:
    """Return whether a GitHub error is authenticated quota exhaustion."""
    folded = (message or "").lower()
    return any(marker in folded for marker in RATE_LIMIT_MARKERS)


def classify_gh_failure(message: str) -> str:
    """Classify a ``gh api`` failure as permanent, transient, or unknown."""
    if is_github_rate_limit_failure(message):
        return "transient"
    status_match = HTTP_STATUS_RE.search(message or "")
    if status_match is not None:
        status = int(status_match.group(1))
        if status in PERMANENT_HTTP_STATUSES:
            return "permanent"
        if status in TRANSIENT_HTTP_STATUSES:
            return "transient"
        return "unknown"
    folded = (message or "").lower()
    if any(marker in folded for marker in TRANSIENT_MARKERS):
        return "transient"
    return "unknown"


def run_gh_visibility(
    repository: str, timeout: float = DEFAULT_TIMEOUT_SECONDS
) -> str:
    """Return ``gh api`` stdout for ``repos/<repository>.private``."""
    argv = ["gh", "api", f"repos/{repository}", "--jq", ".private"]
    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            shell=False,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise
    except OSError as exc:
        raise VisibilityCommandError(
            scrub_sensitive_data(f"gh api could not start: {exc}")
        ) from exc
    if completed.returncode != 0:
        detail = scrub_sensitive_data(
            (completed.stderr or completed.stdout or "").strip()
        )
        raise VisibilityCommandError(
            detail or f"gh api exited {completed.returncode}"
        )
    return completed.stdout


def backoff_seconds(attempt: int) -> float:
    """Return a short exponential backoff capped for queue health."""
    return min(float(2 ** (attempt - 1)), MAX_BACKOFF_SECONDS)


def fetch_repository_visibility(
    repository: str,
    *,
    run_gh: Callable[[str], str] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> str:
    """Return exact ``true``/``false`` visibility after bounded retries."""
    target = validate_target_repository(repository)
    if max_attempts < 1:
        raise VisibilityResolutionError(
            "Visibility lookup requires at least one attempt."
        )
    runner = run_gh or run_gh_visibility
    last_error = "Target repository visibility did not resolve to true or false."
    for attempt in range(1, max_attempts + 1):  # pragma: no branch - last failure raises
        kind = "transient"
        try:
            parsed = parse_private_flag(runner(target))
        except subprocess.TimeoutExpired as exc:
            last_error = scrub_sensitive_data(
                f"GitHub visibility lookup timed out: {exc}"
            )
        except VisibilityCommandError as exc:
            last_error = str(exc)
            kind = classify_gh_failure(last_error)
            if kind == "permanent":
                raise VisibilityResolutionError(
                    "Target repository visibility lookup was denied or missing: "
                    f"{last_error}"
                ) from exc
        else:
            if parsed is not None:
                return parsed
            last_error = (
                "Target repository visibility did not resolve to true or false."
            )
        if attempt >= max_attempts or kind != "transient":
            break
        delay = backoff_seconds(attempt)
        print(
            "Transient GitHub visibility lookup failure on attempt "
            f"{attempt}/{max_attempts}; retrying in {delay:g}s.",
            file=sys.stderr,
        )
        sleep(delay)
    if is_github_rate_limit_failure(last_error):
        raise VisibilityResolutionError(
            "Target repository visibility lookup hit a GitHub API rate-limit; "
            "this is infrastructure, not a source finding: "
            f"{last_error}"
        )
    raise VisibilityResolutionError(last_error)


def write_is_private_output(path: Path, is_private: str) -> None:
    """Append the exact visibility boolean to ``GITHUB_OUTPUT``."""
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"is_private={is_private}\n")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse repository and GitHub-output destinations."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repository",
        default=os.environ.get("TARGET_REPOSITORY", ""),
        help="ContextualWisdomLab owner/name target repository",
    )
    parser.add_argument(
        "--github-output",
        default=os.environ.get("GITHUB_OUTPUT", ""),
        help="Path to the GitHub Actions GITHUB_OUTPUT file",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Resolve visibility and write ``is_private`` or fail closed."""
    args = parse_args(argv)
    try:
        if not str(args.github_output or "").strip():
            raise VisibilityResolutionError("GITHUB_OUTPUT is unset.")
        is_private = fetch_repository_visibility(str(args.repository))
        write_is_private_output(Path(args.github_output), is_private)
    except VisibilityResolutionError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
