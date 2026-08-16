#!/usr/bin/env python3
"""Verify Figma REST personal-access-token auth for Cloud Agents.

Cursor Cloud Agents cannot complete Figma MCP OAuth. The supported Cloud
fallback is a Figma personal access token in ``FIGMA_ACCESS_TOKEN``, sent as
``X-Figma-Token`` to ``https://api.figma.com/v1/me``. This helper never prints
the token.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any, TextIO

TOKEN_ENV_NAME = "FIGMA_ACCESS_TOKEN"
TOKEN_HEADER = "X-Figma-Token"
WHOAMI_URL = "https://api.figma.com/v1/me"
EXIT_OK = 0
EXIT_MISSING_TOKEN = 2
EXIT_REJECTED = 3
EXIT_TRANSPORT = 4
Opener = Callable[[str, Mapping[str, str]], tuple[int, bytes]]


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
    return token


def default_opener(url: str, headers: Mapping[str, str]) -> tuple[int, bytes]:
    """GET ``url`` with ``headers`` and return ``(status, body)``."""
    request = urllib.request.Request(url, headers=dict(headers), method="GET")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return int(response.status), response.read()
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read()
    except urllib.error.URLError as exc:
        raise FigmaAuthError(
            f"Figma REST transport failed: {exc.reason}",
            EXIT_TRANSPORT,
        ) from exc


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


def identity_summary(payload: Mapping[str, Any]) -> str:
    """Return a token-free identity line from a ``/v1/me`` object."""
    handle = payload.get("handle")
    account_id = payload.get("id")
    email = payload.get("email")
    parts: list[str] = []
    if isinstance(handle, str) and handle.strip():
        parts.append(f"handle={handle.strip()}")
    if isinstance(account_id, str) and account_id.strip():
        parts.append(f"id={account_id.strip()}")
    if isinstance(email, str) and email.strip():
        parts.append(f"email={email.strip()}")
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
