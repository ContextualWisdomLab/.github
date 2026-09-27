"""Stdlib-only Noema continuation helpers for startup and model failures."""

from __future__ import annotations

import hashlib
import os
import re

MAX_TRANSPORT_REDISPATCH_ATTEMPTS = 2
TRANSPORT_REDISPATCH_JITTER_MIN_SECONDS = 60
TRANSPORT_REDISPATCH_JITTER_MAX_SECONDS = 180
TRANSPORT_REDISPATCH_RETRY_AFTER_MAX_SECONDS = 300


def transport_redispatch_delay_seconds(
    *,
    transport_retry_attempt: int,
    head_sha: str,
    retry_after_seconds: int | None = None,
) -> int | None:
    """Return the post-failure scheduling delay, or None when the re-dispatch bound is spent.

    ``transport_retry_attempt`` is the number of automatic capacity re-dispatches
    already performed for this head (0 on the first failure). Prefer a capped
    gateway ``Retry-After`` when present; otherwise use deterministic jitter in
    ``[TRANSPORT_REDISPATCH_JITTER_MIN_SECONDS, TRANSPORT_REDISPATCH_JITTER_MAX_SECONDS]``
    keyed by head SHA and attempt so concurrent failures do not stampede.
    """
    if transport_retry_attempt < 0 or transport_retry_attempt >= MAX_TRANSPORT_REDISPATCH_ATTEMPTS:
        return None
    if retry_after_seconds is not None:
        if (
            type(retry_after_seconds) is int
            and 1 <= retry_after_seconds <= TRANSPORT_REDISPATCH_RETRY_AFTER_MAX_SECONDS
        ):
            return retry_after_seconds
        return None
    digest = hashlib.sha256(
        f"{head_sha.strip().lower()}:{transport_retry_attempt}".encode("utf-8")
    ).digest()
    span = (
        TRANSPORT_REDISPATCH_JITTER_MAX_SECONDS - TRANSPORT_REDISPATCH_JITTER_MIN_SECONDS + 1
    )
    offset = int.from_bytes(digest[:4], "big") % span
    return TRANSPORT_REDISPATCH_JITTER_MIN_SECONDS + offset


def current_transport_retry_attempt() -> int:
    """Parse the retry counter; invalid values exhaust the automatic budget."""
    raw = os.environ.get("NOEMA_TRANSPORT_RETRY_ATTEMPT")
    if raw is None or raw == "null":
        return 0
    if not re.fullmatch(r"[0-9]{1,2}", raw):
        return MAX_TRANSPORT_REDISPATCH_ATTEMPTS
    value = int(raw)
    return min(value, MAX_TRANSPORT_REDISPATCH_ATTEMPTS)


def append_github_output(values: dict[str, str]) -> None:
    """Append allowlisted step outputs when running under GitHub Actions."""
    path = (os.environ.get("GITHUB_OUTPUT") or "").strip()
    if not path or not values:
        return
    with open(path, "a", encoding="utf-8") as handle:
        for key, value in values.items():
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
                continue
            if any(ch in value for ch in ("\n", "\r", "\0")):
                continue
            handle.write(f"{key}={value}\n")
