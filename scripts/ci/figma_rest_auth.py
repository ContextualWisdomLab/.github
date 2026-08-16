#!/usr/bin/env python3
"""Verify Figma REST auth and load page-level file metadata for Cloud Agents.

Cursor Cloud Agents cannot complete Figma MCP OAuth. The supported Cloud
fallback is a Figma personal or plan access token in ``FIGMA_ACCESS_TOKEN``,
sent only as ``X-Figma-Token`` to ``https://api.figma.com``. This helper never
prints the token. ``GET /v1/me`` proves the secret. ``GET /v1/files/:key`` at
``depth=1`` lists pages so the next action is a specific node or image request.
"""

from __future__ import annotations

import http.client
import json
import os
import re
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, TextIO

TOKEN_ENV_NAME = "FIGMA_ACCESS_TOKEN"
TOKEN_HEADER = "X-Figma-Token"
FIGMA_API_HOST = "api.figma.com"
WHOAMI_PATH = "/v1/me"
WHOAMI_URL = f"https://{FIGMA_API_HOST}{WHOAMI_PATH}"
REQUEST_TIMEOUT_SECONDS = 20
MAX_WHOAMI_BODY_BYTES = 65_536
MAX_FILE_BODY_BYTES = 8_388_608
EXIT_OK = 0
EXIT_MISSING_TOKEN = 2
EXIT_REJECTED = 3
EXIT_TRANSPORT = 4
EXIT_USAGE = 5
FILE_KEY_PATTERN = re.compile(r"^[A-Za-z0-9]{8,128}$")
FILE_DOCUMENT_URL_PATTERN = re.compile(
    rf"^https://{re.escape(FIGMA_API_HOST)}/v1/files/([A-Za-z0-9]{{8,128}})\?depth=1$"
)
Opener = Callable[[str, Mapping[str, str]], tuple[int, bytes]]
BoundedReader = Callable[[int], bytes]


class FigmaAuthError(Exception):
    """Raised when Figma REST authentication or file load cannot complete."""

    def __init__(self, message: str, exit_code: int) -> None:
        """Record a user-visible failure and the process exit code."""
        super().__init__(message)
        self.exit_code = exit_code


@dataclass(frozen=True)
class CliRequest:
    """Parsed command line for whoami or a single file-key load."""

    file_key: str | None


def read_access_token(environ: Mapping[str, str]) -> str:
    """Return the trimmed personal or plan access token or raise ``FigmaAuthError``."""
    raw = environ.get(TOKEN_ENV_NAME)
    if raw is None:
        raise FigmaAuthError(
            f"{TOKEN_ENV_NAME} is unset. Cloud Agents cannot complete Figma "
            "MCP OAuth; add a Figma personal or plan access token as this secret.",
            EXIT_MISSING_TOKEN,
        )
    token = raw.strip()
    if not token:
        raise FigmaAuthError(
            f"{TOKEN_ENV_NAME} is empty. Generate a Figma personal or plan "
            "access token and store it as this secret; do not commit it.",
            EXIT_MISSING_TOKEN,
        )
    return token


def validate_file_key(file_key: str) -> str:
    """Return a Figma file or branch key or raise ``FigmaAuthError``.

    Keys are the ``:file_key`` segment from
    ``https://www.figma.com/:file_type/:file_key/:file_name``. Only
    alphanumeric keys are accepted so ``..``, slashes, and query characters
    cannot reach the TLS path.
    """
    key = file_key.strip()
    if not FILE_KEY_PATTERN.fullmatch(key):
        raise FigmaAuthError(
            "Figma file key must be 8-128 alphanumeric characters from the "
            "file URL. Next: copy the key between /design/ or /file/ and the "
            "title, then rerun with --file.",
            EXIT_TRANSPORT,
        )
    return key


def file_document_path(file_key: str) -> str:
    """Return the pinned ``GET /v1/files/:key?depth=1`` path."""
    return f"/v1/files/{validate_file_key(file_key)}?depth=1"


def file_document_url(file_key: str) -> str:
    """Return the pinned HTTPS URL for a page-level file load."""
    return f"https://{FIGMA_API_HOST}{file_document_path(file_key)}"


def sanitize_request_headers(headers: Mapping[str, str]) -> dict[str, str]:
    """Allow only ``X-Figma-Token`` so a ``Host`` header cannot retarget TLS."""
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


def pinned_https_get(
    path: str,
    headers: Mapping[str, str],
    max_body_bytes: int,
) -> tuple[int, bytes]:
    """GET a ``/v1/...`` path on the pinned Figma origin and return status/body."""
    if not path.startswith("/v1/"):
        raise FigmaAuthError(
            "Figma REST path must start with /v1/ on api.figma.com.",
            EXIT_TRANSPORT,
        )
    if ".." in path or "\\" in path or " " in path:
        raise FigmaAuthError(
            "Figma REST path contains forbidden characters.",
            EXIT_TRANSPORT,
        )
    connection = http.client.HTTPSConnection(
        FIGMA_API_HOST,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    try:
        connection.request("GET", path, headers=sanitize_request_headers(headers))
        response = connection.getresponse()
        return int(response.status), read_bounded_body(response.read, max_body_bytes)
    except OSError as exc:
        raise FigmaAuthError(
            f"Figma REST transport failed: {exc}",
            EXIT_TRANSPORT,
        ) from exc
    finally:
        connection.close()


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
    return pinned_https_get(WHOAMI_PATH, headers, MAX_WHOAMI_BODY_BYTES)


def default_file_opener(url: str, headers: Mapping[str, str]) -> tuple[int, bytes]:
    """GET a validated ``/v1/files/:key?depth=1`` URL on the pinned origin."""
    match = FILE_DOCUMENT_URL_PATTERN.fullmatch(url)
    if match is None:
        raise FigmaAuthError(
            "Figma REST file opener refuses URLs other than the pinned HTTPS "
            "/v1/files/:key?depth=1 endpoint.",
            EXIT_TRANSPORT,
        )
    return pinned_https_get(file_document_path(match.group(1)), headers, MAX_FILE_BODY_BYTES)


def parse_json_object(body: bytes, source: str) -> dict[str, Any]:
    """Parse a Figma JSON object or raise ``FigmaAuthError``."""
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FigmaAuthError(
            f"Figma REST {source} returned a non-JSON body.",
            EXIT_TRANSPORT,
        ) from exc
    if not isinstance(payload, dict):
        raise FigmaAuthError(
            f"Figma REST {source} returned a JSON value that is not an object.",
            EXIT_TRANSPORT,
        )
    return payload


def parse_whoami_payload(body: bytes) -> dict[str, Any]:
    """Parse a Figma ``/v1/me`` JSON object or raise ``FigmaAuthError``."""
    return parse_json_object(body, "/v1/me")


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


def _string_field(payload: Mapping[str, Any], name: str) -> str:
    """Return a stripped string field or an empty string."""
    value = payload.get(name)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return ""


def _page_names(payload: Mapping[str, Any]) -> list[str]:
    """Return canvas/page names from a ``depth=1`` document object."""
    document = payload.get("document")
    if not isinstance(document, dict):
        return []
    children = document.get("children")
    if not isinstance(children, list):
        return []
    pages: list[str] = []
    for child in children:
        if not isinstance(child, dict):
            continue
        name = _string_field(child, "name")
        if name:
            pages.append(name)
    return pages


def _mapping_count(payload: Mapping[str, Any], name: str) -> int:
    """Return the number of keys in a JSON object field."""
    value = payload.get(name)
    if isinstance(value, dict):
        return len(value)
    return 0


def file_document_summary(file_key: str, payload: Mapping[str, Any]) -> str:
    """Return a token-free page inventory from a ``/v1/files/:key`` object."""
    key = validate_file_key(file_key)
    parts = [f"key={key}"]
    name = _string_field(payload, "name")
    version = _string_field(payload, "version")
    modified = _string_field(payload, "lastModified")
    if name:
        parts.append(f"name={name}")
    if version:
        parts.append(f"version={version}")
    if modified:
        parts.append(f"lastModified={modified}")
    pages = _page_names(payload)
    page_text = ", ".join(pages) if pages else "(none)"
    return (
        "Figma file loaded ("
        + ", ".join(parts)
        + f"; pages={page_text}; components={_mapping_count(payload, 'components')}; "
        f"styles={_mapping_count(payload, 'styles')}). "
        "Next: pick a page and request that node or its images over REST."
    )


def classify_http_status(status: int, source: str) -> None:
    """Raise when a Figma status is not HTTP 200."""
    if status in {401, 403}:
        raise FigmaAuthError(
            f"Figma REST rejected {TOKEN_ENV_NAME} with HTTP {status} on "
            f"{source}. Regenerate the personal or plan access token and "
            "update the secret.",
            EXIT_REJECTED,
        )
    if status != 200:
        raise FigmaAuthError(
            f"Figma REST {source} returned HTTP {status}. Next: confirm the "
            "file key and token scopes include file_content:read.",
            EXIT_TRANSPORT,
        )


def verify_rest_auth(
    environ: Mapping[str, str],
    opener: Opener = default_opener,
) -> str:
    """Authenticate against Figma REST ``/v1/me`` and return an identity line."""
    token = read_access_token(environ)
    status, body = opener(WHOAMI_URL, {TOKEN_HEADER: token})
    classify_http_status(status, "/v1/me")
    return identity_summary(parse_whoami_payload(body))


def fetch_file_document(
    file_key: str,
    environ: Mapping[str, str],
    opener: Opener = default_file_opener,
) -> str:
    """Load page-level Figma file metadata and return a token-free inventory."""
    token = read_access_token(environ)
    url = file_document_url(file_key)
    status, body = opener(url, {TOKEN_HEADER: token})
    classify_http_status(status, "/v1/files/:key")
    return file_document_summary(file_key, parse_json_object(body, "/v1/files/:key"))


def _drop_program_name(argv: list[str]) -> list[str]:
    """Remove the helper's program name when present as ``argv[0]``."""
    if not argv:
        return []
    first = argv[0]
    if first.endswith("figma_rest_auth.py") or first.endswith("figma_rest_auth"):
        return list(argv[1:])
    return list(argv)


def parse_cli_args(argv: list[str]) -> CliRequest:
    """Parse ``[--file FILE_KEY]`` or raise ``FigmaAuthError``."""
    args = _drop_program_name(argv)
    if not args:
        return CliRequest(file_key=None)
    if args[0] == "--file" and len(args) == 1:
        raise FigmaAuthError(
            "Usage: figma_rest_auth.py [--file FILE_KEY]. Next: pass the "
            "alphanumeric key from the Figma file URL.",
            EXIT_USAGE,
        )
    if args[0] == "--file" and len(args) == 2:
        return CliRequest(file_key=validate_file_key(args[1]))
    raise FigmaAuthError(
        "Usage: figma_rest_auth.py [--file FILE_KEY]. Next: omit arguments "
        "to verify the secret, or pass one --file key.",
        EXIT_USAGE,
    )


def main(
    argv: list[str] | None = None,
    environ: Mapping[str, str] | None = None,
    opener: Opener | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Verify ``FIGMA_ACCESS_TOKEN`` and optionally load one Figma file."""
    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr
    env = environ if environ is not None else os.environ
    try:
        request = parse_cli_args(list(argv) if argv is not None else sys.argv)
        if request.file_key is None:
            whoami_opener = default_opener if opener is None else opener
            out.write(verify_rest_auth(env, whoami_opener) + "\n")
        else:
            file_opener = default_file_opener if opener is None else opener
            out.write(fetch_file_document(request.file_key, env, file_opener) + "\n")
    except FigmaAuthError as exc:
        err.write(str(exc) + "\n")
        return exc.exit_code
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    raise SystemExit(main())
