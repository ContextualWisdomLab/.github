#!/usr/bin/env python3
"""Resolve Strix target-repository visibility with fail-closed retries.

The required Strix job used a single ``gh api`` call. A transient GitHub API
flake (timeout, 5xx, 429, empty/non-boolean body, or authenticated HTTP 403
rate-limit) aborted the scan before it started. Generic flakes retry a few
times with short backoff. Authenticated HTTP 403 rate-limits use a shorter
attempt budget and a longer bounded wait, honoring Retry-After /
X-RateLimit-Reset from ``gh`` output when present and capping the sleep so
the job cannot stall. A real 401/403/404 on a missing or unauthorized
repository stays fail-closed and is never treated as success or as a source
finding.
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
RETRY_AFTER_RE = re.compile(r"(?i)\bretry-after\s*[:=]\s*(\d+)\b")
RATE_LIMIT_RESET_RE = re.compile(r"(?i)\bx-ratelimit-reset\s*[:=]\s*(\d+)\b")
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
RATE_LIMIT_MAX_ATTEMPTS = 3
DEFAULT_TIMEOUT_SECONDS = 20.0
MAX_BACKOFF_SECONDS = 4.0
RATE_LIMIT_BASE_BACKOFF_SECONDS = 30.0
RATE_LIMIT_MIN_BACKOFF_SECONDS = 5.0
RATE_LIMIT_MAX_BACKOFF_SECONDS = 60.0


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


def parse_rate_limit_wait_seconds(
    message: str, *, now: float | None = None
) -> float | None:
    """Return a wait from Retry-After or X-RateLimit-Reset when present."""
    text = message or ""
    retry_after = RETRY_AFTER_RE.search(text)
    if retry_after is not None:
        return float(retry_after.group(1))
    reset = RATE_LIMIT_RESET_RE.search(text)
    if reset is None:
        return None
    current = time.time() if now is None else now
    delay = float(reset.group(1)) - current
    if delay <= 0:
        return None
    return delay


def rate_limit_backoff_seconds(
    attempt: int, message: str = "", *, now: float | None = None
) -> float:
    """Return a bounded rate-limit wait, honoring headers when present."""
    parsed = parse_rate_limit_wait_seconds(message, now=now)
    if parsed is None:
        parsed = min(
            RATE_LIMIT_BASE_BACKOFF_SECONDS * float(2 ** (attempt - 1)),
            RATE_LIMIT_MAX_BACKOFF_SECONDS,
        )
    parsed = max(parsed, RATE_LIMIT_MIN_BACKOFF_SECONDS)
    if parsed > RATE_LIMIT_MAX_BACKOFF_SECONDS:
        print(
            "GitHub visibility rate-limit retry sleep capped from "
            f"{parsed:g} to {RATE_LIMIT_MAX_BACKOFF_SECONDS:g} seconds.",
            file=sys.stderr,
        )
        return RATE_LIMIT_MAX_BACKOFF_SECONDS
    return parsed


def fetch_repository_visibility(
    repository: str,
    *,
    run_gh: Callable[[str], str] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.time,
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
    rate_limit_attempts = 0
    for attempt in range(1, max_attempts + 1):  # pragma: no branch - last failure raises
        kind = "transient"
        rate_limited = False
        try:
            parsed = parse_private_flag(runner(target))
        except subprocess.TimeoutExpired as exc:
            last_error = scrub_sensitive_data(
                f"GitHub visibility lookup timed out: {exc}"
            )
        except VisibilityCommandError as exc:
            last_error = str(exc)
            kind = classify_gh_failure(last_error)
            rate_limited = is_github_rate_limit_failure(last_error)
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
        if rate_limited:
            rate_limit_attempts += 1
            if rate_limit_attempts >= RATE_LIMIT_MAX_ATTEMPTS:
                break
        if attempt >= max_attempts or kind != "transient":
            break
        if rate_limited:
            delay = rate_limit_backoff_seconds(attempt, last_error, now=now())
            label = "rate-limit"
        else:
            delay = backoff_seconds(attempt)
            label = "transient"
        print(
            f"{label.capitalize()} GitHub visibility lookup failure on attempt "
            f"{attempt}/{RATE_LIMIT_MAX_ATTEMPTS if rate_limited else max_attempts}; "
            f"retrying in {delay:g}s.",
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
