#!/usr/bin/env python3
"""Verify Figma REST personal-access-token auth for Cloud Agents.

Cursor Cloud Agents cannot complete Figma MCP OAuth. The supported Cloud
fallback is a Figma personal access token in ``FIGMA_ACCESS_TOKEN``, sent as
``X-Figma-Token`` to ``https://api.figma.com/v1/me``. This helper never prints
the token.
"""

from __future__ import annotations

import http.client
import json
import os
import sys
from collections.abc import Callable, Mapping
from typing import Any, TextIO

TOKEN_ENV_NAME = "FIGMA_ACCESS_TOKEN"
TOKEN_HEADER = "X-Figma-Token"
WHOAMI_URL = "https://api.figma.com/v1/me"
REQUEST_TIMEOUT_SECONDS = 20
MAX_WHOAMI_BODY_BYTES = 65_536
EXIT_OK = 0
EXIT_MISSING_TOKEN = 2
EXIT_REJECTED = 3
EXIT_TRANSPORT = 4
Opener = Callable[[str, Mapping[str, str]], tuple[int, bytes]]
BoundedReader = Callable[[int], bytes]


class FigmaAuthError(Exception):
    """Raised when Figma REST authentication cannot be completed."""

    def __init__(self, message: str, exit_code: int) -> None:
        """Record a user-visible failure and the process exit code."""
        super().__init__(message)
        self.exit_code = exit_code


def read_access_token(environ: Mapping[str, str]) -> str:
    """Return the trimmed personal access token or raise ``FigmaAuthError``."""
    raw = environ.get(TOKEN_ENV_NAME)
    if raw is None:
        raise FigmaAuthError(
            f"{TOKEN_ENV_NAME} is unset. Cloud Agents cannot complete Figma "
            "MCP OAuth; add a Figma personal access token as this secret.",
            EXIT_MISSING_TOKEN,
        )
    token = raw.strip()
    if not token:
        raise FigmaAuthError(
            f"{TOKEN_ENV_NAME} is empty. Generate a Figma personal access "
            "token and store it as this secret; do not commit it.",
            EXIT_MISSING_TOKEN,
        )
    if any(ord(character) < 32 for character in token):
        raise FigmaAuthError(
            f"{TOKEN_ENV_NAME} contains control characters. Store a "
            "single-line token; do not paste a multiline secret.",
            EXIT_MISSING_TOKEN,
        )
    return token


def sanitize_request_headers(headers: Mapping[str, str]) -> dict[str, str]:
    """Allow only ``X-Figma-Token`` so a ``Host`` header never reaches request."""
    sanitized: dict[str, str] = {}
    for name, value in headers.items():
        if name.lower() != TOKEN_HEADER.lower():
            raise FigmaAuthError(
                f"Figma REST opener refuses header {name!s} other than "
                f"{TOKEN_HEADER}.",
                EXIT_TRANSPORT,
            )
        if not value.strip():
            raise FigmaAuthError(
                "Figma REST token header is empty.",
                EXIT_TRANSPORT,
            )
        if any(ord(character) < 32 for character in value):
            raise FigmaAuthError(
                "Figma REST token header contains control characters.",
                EXIT_TRANSPORT,
            )
        sanitized[TOKEN_HEADER] = value
    return sanitized


def read_bounded_body(read: BoundedReader, limit: int) -> bytes:
    """Read at most ``limit`` bytes or raise ``FigmaAuthError``."""
    if limit < 1:
        raise FigmaAuthError(
            "Figma REST body limit must be a positive byte count.",
            EXIT_TRANSPORT,
        )
    payload = read(limit + 1)
    if len(payload) > limit:
        raise FigmaAuthError(
            f"Figma REST response exceeded {limit} bytes.",
            EXIT_TRANSPORT,
        )
    return payload


def default_opener(url: str, headers: Mapping[str, str]) -> tuple[int, bytes]:
    """GET the fixed Figma whoami origin and return ``(status, body)``.

    Host and path are string literals at the TLS sink. Caller ``url`` is
    accepted only when it equals ``WHOAMI_URL``, so ``file://`` and other
    schemes never reach the network helper. This path does not call
    ``urllib.request.urlopen``.
    """
    if url != WHOAMI_URL:
        raise FigmaAuthError(
            "Figma REST opener refuses URLs other than the fixed HTTPS "
            "/v1/me endpoint.",
            EXIT_TRANSPORT,
        )
    connection = http.client.HTTPSConnection(  # nosemgrep: python.lang.security.audit.httpsconnection-detected.httpsconnection-detected
        "api.figma.com",
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    try:
        connection.request("GET", "/v1/me", headers=sanitize_request_headers(headers))
        response = connection.getresponse()
        return int(response.status), read_bounded_body(response.read, MAX_WHOAMI_BODY_BYTES)
    except OSError as exc:
        raise FigmaAuthError(
            f"Figma REST transport failed: {exc}",
            EXIT_TRANSPORT,
        ) from exc
    finally:
        connection.close()


def parse_whoami_payload(body: bytes) -> dict[str, Any]:
    """Parse a Figma ``/v1/me`` JSON object or raise ``FigmaAuthError``."""
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FigmaAuthError(
            "Figma REST /v1/me returned a non-JSON body.",
            EXIT_TRANSPORT,
        ) from exc
    if not isinstance(payload, dict):
        raise FigmaAuthError(
            "Figma REST /v1/me returned a JSON value that is not an object.",
            EXIT_TRANSPORT,
        )
    return payload


def identity_field(value: object) -> str | None:
    """Return a single-line identity token, including numeric Figma ids."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        value = str(value)
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split())
    if not cleaned:
        return None
    return cleaned


def identity_summary(payload: Mapping[str, Any]) -> str:
    """Return a token-free identity line from a ``/v1/me`` object."""
    parts: list[str] = []
    handle = identity_field(payload.get("handle"))
    account_id = identity_field(payload.get("id"))
    email = identity_field(payload.get("email"))
    if handle is not None:
        parts.append(f"handle={handle}")
    if account_id is not None:
        parts.append(f"id={account_id}")
    if email is not None:
        parts.append(f"email={email}")
    if not parts:
        return "Figma REST authentication succeeded."
    return "Figma REST authentication succeeded (" + ", ".join(parts) + ")."


def verify_rest_auth(
    environ: Mapping[str, str],
    opener: Opener = default_opener,
) -> str:
    """Authenticate against Figma REST ``/v1/me`` and return an identity line."""
    token = read_access_token(environ)
    status, body = opener(WHOAMI_URL, {TOKEN_HEADER: token})
    if status in {401, 403}:
        raise FigmaAuthError(
            f"Figma REST rejected {TOKEN_ENV_NAME} with HTTP {status}. "
            "Regenerate the personal access token and update the secret.",
            EXIT_REJECTED,
        )
    if status != 200:
        raise FigmaAuthError(
            f"Figma REST /v1/me returned HTTP {status}.",
            EXIT_TRANSPORT,
        )
    return identity_summary(parse_whoami_payload(body))


def main(
    argv: list[str] | None = None,
    environ: Mapping[str, str] | None = None,
    opener: Opener = default_opener,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Verify ``FIGMA_ACCESS_TOKEN`` and print a token-free identity line."""
    del argv
    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr
    env = environ if environ is not None else os.environ
    try:
        out.write(verify_rest_auth(env, opener) + "\n")
    except FigmaAuthError as exc:
        err.write(str(exc) + "\n")
        return exc.exit_code
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    raise SystemExit(main())
