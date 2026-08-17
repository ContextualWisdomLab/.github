#!/usr/bin/env python3
"""Read a Figma file over REST for Cloud Agents.

Cursor Cloud Agents cannot complete Figma MCP OAuth. After
``figma_rest_auth.py`` confirms ``FIGMA_ACCESS_TOKEN``, this helper GETs
``/v1/files/{file_key}`` (optional ``/nodes`` or ``/images``) on a pinned
``api.figma.com`` HTTPS connection. File keys and node IDs are allowlisted
before they enter the request path. The token is never printed.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import re
import ssl
import sys
from collections.abc import Callable, Mapping, Sequence
from typing import Any, TextIO
from urllib.parse import parse_qs, unquote, urlparse

from scripts.ci.figma_rest_auth import (
    EXIT_OK,
    EXIT_REJECTED,
    EXIT_TRANSPORT,
    REQUEST_TIMEOUT_SECONDS,
    TOKEN_ENV_NAME,
    TOKEN_HEADER,
    FigmaAuthError,
    identity_field,
    read_access_token,
    read_bounded_body,
    sanitize_request_headers,
)

EXIT_INVALID_TARGET = 5
EXIT_NOT_FOUND = 6
FIGMA_API_HOST = "api.figma.com"
FILE_KEY_PATTERN = re.compile(r"^[A-Za-z0-9]{10,128}$")
NODE_ID_PATTERN = re.compile(r"^\d+:\d+$")
FILE_URL_TYPES = frozenset({"file", "design", "board", "proto", "slides", "deck", "figjam"})
FILE_URL_HOSTS = frozenset({"www.figma.com", "figma.com"})
ALLOWED_REQUEST_PATH = re.compile(
    r"^/v1/(?:"
    r"files/[A-Za-z0-9]{10,128}(?:\?depth=[1-8])?"
    r"|files/[A-Za-z0-9]{10,128}/nodes\?ids=\d+:\d+(?:,\d+:\d+)*(?:&depth=[1-8])?"
    r"|images/[A-Za-z0-9]{10,128}\?ids=\d+:\d+(?:,\d+:\d+)*&format=png"
    r")$"
)
DEFAULT_TREE_DEPTH = 2
MAX_TREE_DEPTH = 8
MAX_FILE_BODY_BYTES = 8_388_608
FileOpener = Callable[[str, Mapping[str, str]], tuple[int, bytes]]


def validate_file_key(raw: str) -> str:
    """Return an allowlisted Figma file or branch key."""
    key = raw.strip()
    if not FILE_KEY_PATTERN.fullmatch(key):
        raise FigmaAuthError(
            "Figma file key must be 10-128 letters or digits. Paste the key "
            "or a https://www.figma.com/design/<key>/... URL; do not pass "
            "paths, schemes, or query strings as the key.",
            EXIT_INVALID_TARGET,
        )
    return key


def validate_node_id(raw: str) -> str:
    """Return a Figma node id in ``page:node`` form."""
    candidate = raw.strip().replace("-", ":", 1)
    if not NODE_ID_PATTERN.fullmatch(candidate):
        raise FigmaAuthError(
            "Figma node id must look like 12:34 (URL form 12-34 is accepted).",
            EXIT_INVALID_TARGET,
        )
    return candidate


def parse_file_locator(raw: str) -> tuple[str, list[str]]:
    """Return ``(file_key, node_ids)`` from a key or Figma file URL."""
    text = raw.strip()
    if not text:
        raise FigmaAuthError(
            "Pass a Figma file key or https://www.figma.com/design/<key>/... URL.",
            EXIT_INVALID_TARGET,
        )
    if "://" in text or text.startswith(("figma.com/", "www.figma.com/")):
        parsed = urlparse(text if "://" in text else f"https://{text}")
        if parsed.scheme != "https":
            raise FigmaAuthError(
                "Figma file URLs must use https://www.figma.com. "
                "file:// and http:// locators are refused.",
                EXIT_INVALID_TARGET,
            )
        host = (parsed.hostname or "").lower()
        if host not in FILE_URL_HOSTS:
            raise FigmaAuthError(
                "Figma file URLs must be on www.figma.com. "
                "api.figma.com paths are not locators.",
                EXIT_INVALID_TARGET,
            )
        parts = [unquote(part) for part in parsed.path.split("/") if part]
        if len(parts) < 2 or parts[0] not in FILE_URL_TYPES:
            raise FigmaAuthError(
                "Figma file URL must look like "
                "https://www.figma.com/design/<file_key>/<name>.",
                EXIT_INVALID_TARGET,
            )
        node_ids = [
            validate_node_id(value) for value in parse_qs(parsed.query).get("node-id", [])
        ]
        return validate_file_key(parts[1]), node_ids
    return validate_file_key(text), []


def unique_node_ids(values: Sequence[str]) -> list[str]:
    """Return allowlisted node ids in first-seen order."""
    seen: set[str] = set()
    ordered: list[str] = []
    for raw in values:
        node_id = validate_node_id(raw)
        if node_id in seen:
            continue
        seen.add(node_id)
        ordered.append(node_id)
    return ordered


def build_request_path(
    file_key: str,
    *,
    node_ids: Sequence[str] = (),
    depth: int = DEFAULT_TREE_DEPTH,
    images: bool = False,
) -> str:
    """Return a pinned Figma REST path after allowlisting every parameter."""
    key = validate_file_key(file_key)
    ids = unique_node_ids(node_ids)
    if not isinstance(depth, int) or isinstance(depth, bool) or depth < 1 or depth > MAX_TREE_DEPTH:
        raise FigmaAuthError(
            f"Figma tree depth must be an integer from 1 to {MAX_TREE_DEPTH}.",
            EXIT_INVALID_TARGET,
        )
    if images:
        if not ids:
            raise FigmaAuthError(
                "Image export needs at least one --node-id so Figma can render "
                "those nodes. Pass the frame id from the Figma URL.",
                EXIT_INVALID_TARGET,
            )
        return f"/v1/images/{key}?ids={','.join(ids)}&format=png"
    if ids:
        return f"/v1/files/{key}/nodes?ids={','.join(ids)}&depth={depth}"
    return f"/v1/files/{key}?depth={depth}"


def default_file_opener(path: str, headers: Mapping[str, str]) -> tuple[int, bytes]:
    """GET an allowlisted Figma REST path and return ``(status, body)``.

    Host is the string literal ``api.figma.com``. ``path`` must match
    ``ALLOWED_REQUEST_PATH`` so ``file://``, ``..``, and other schemes never
    reach the TLS sink. This path does not call ``urllib.request.urlopen``.
    ``ssl.create_default_context()`` makes certificate verification explicit.
    The scoped Semgrep suppression is only for the historical
    ``httpsconnection-detected`` audit, not for a dynamic host or scheme.
    """
    if ALLOWED_REQUEST_PATH.fullmatch(path) is None:
        raise FigmaAuthError(
            "Figma REST file opener refuses paths other than allowlisted "
            "/v1/files or /v1/images requests on api.figma.com.",
            EXIT_TRANSPORT,
        )
    request_headers = sanitize_request_headers(headers)
    connection = http.client.HTTPSConnection(  # nosemgrep: python.lang.security.audit.httpsconnection-detected.httpsconnection-detected
        FIGMA_API_HOST,
        timeout=REQUEST_TIMEOUT_SECONDS,
        context=ssl.create_default_context(),
    )
    try:
        connection.request("GET", path, headers=request_headers)
        response = connection.getresponse()
        return int(response.status), read_bounded_body(response.read, MAX_FILE_BODY_BYTES)
    except OSError as exc:
        raise FigmaAuthError(
            f"Figma REST transport failed: {exc}",
            EXIT_TRANSPORT,
        ) from exc
    finally:
        connection.close()


def parse_json_object(body: bytes) -> dict[str, Any]:
    """Parse a Figma JSON object or raise ``FigmaAuthError``."""
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FigmaAuthError(
            "Figma REST file endpoint returned a non-JSON body.",
            EXIT_TRANSPORT,
        ) from exc
    if not isinstance(payload, dict):
        raise FigmaAuthError(
            "Figma REST file endpoint returned a JSON value that is not an object.",
            EXIT_TRANSPORT,
        )
    return payload


def outline_node(node: object, remaining_depth: int) -> dict[str, Any] | None:
    """Return a token-free id/name/type outline of one Figma node."""
    if not isinstance(node, Mapping):
        return None
    summary: dict[str, Any] = {}
    node_id = identity_field(node.get("id"))
    name = identity_field(node.get("name"))
    node_type = identity_field(node.get("type"))
    if node_id is not None:
        summary["node_id"] = node_id
    if name is not None:
        summary["node_name"] = name
    if node_type is not None:
        summary["node_type"] = node_type
    if remaining_depth > 0:
        children = node.get("children")
        if isinstance(children, list):
            outlined = [outline_node(child, remaining_depth - 1) for child in children]
            summary["child_nodes"] = [child for child in outlined if child is not None]
    return summary or None


def https_image_url(value: object) -> str | None:
    """Return a https image URL, refusing token-shaped or non-https values."""
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned.startswith("https://"):
        return None
    if "figd_" in cleaned or TOKEN_ENV_NAME in cleaned:
        return None
    return cleaned


def summarize_file_payload(payload: Mapping[str, Any], outline_depth: int) -> dict[str, Any]:
    """Return a compact, token-free file, node, or image summary."""
    summary: dict[str, Any] = {}
    file_name = identity_field(payload.get("name"))
    last_modified = identity_field(payload.get("lastModified"))
    version = identity_field(payload.get("version"))
    editor_type = identity_field(payload.get("editorType"))
    role = identity_field(payload.get("role"))
    if file_name is not None:
        summary["file_name"] = file_name
    if last_modified is not None:
        summary["last_modified"] = last_modified
    if version is not None:
        summary["file_version"] = version
    if editor_type is not None:
        summary["editor_type"] = editor_type
    if role is not None:
        summary["viewer_role"] = role
    document = outline_node(payload.get("document"), outline_depth)
    if document is not None:
        summary["document_outline"] = document
    raw_nodes = payload.get("nodes")
    if isinstance(raw_nodes, Mapping):
        nodes: dict[str, Any] = {}
        for raw_id, raw_node in raw_nodes.items():
            candidate = str(raw_id).replace("-", ":", 1)
            node_id = validate_node_id(str(raw_id)) if NODE_ID_PATTERN.fullmatch(candidate) else None
            if node_id is None:
                continue
            document_node = raw_node.get("document") if isinstance(raw_node, Mapping) else None
            outlined = outline_node(document_node, outline_depth)
            if outlined is not None:
                nodes[node_id] = outlined
        if nodes:
            summary["selected_nodes"] = nodes
    raw_images = payload.get("images")
    if isinstance(raw_images, Mapping):
        images = {
            str(node_id): image_url
            for node_id, raw_url in raw_images.items()
            if (image_url := https_image_url(raw_url)) is not None
        }
        if images:
            summary["image_urls"] = images
    if not summary:
        return {"read_status": "Figma REST file read succeeded with no outline fields."}
    return summary


def classify_file_status(status: int) -> None:
    """Raise ``FigmaAuthError`` for every non-200 Figma file status."""
    if status in {401, 403}:
        raise FigmaAuthError(
            f"Figma REST rejected {TOKEN_ENV_NAME} with HTTP {status}. "
            "Regenerate the personal access token with file_content:read "
            "and confirm the token can open that file.",
            EXIT_REJECTED,
        )
    if status == 404:
        raise FigmaAuthError(
            "Figma REST returned HTTP 404. Check the file key and that the "
            "token's owner can open the file.",
            EXIT_NOT_FOUND,
        )
    if status == 400:
        raise FigmaAuthError(
            "Figma REST returned HTTP 400. Check --node-id and --depth.",
            EXIT_INVALID_TARGET,
        )
    if status != 200:
        raise FigmaAuthError(
            f"Figma REST file endpoint returned HTTP {status}.",
            EXIT_TRANSPORT,
        )


def fetch_file_document(
    locator: str,
    environ: Mapping[str, str],
    *,
    extra_node_ids: Sequence[str] = (),
    depth: int = DEFAULT_TREE_DEPTH,
    images: bool = False,
    opener: FileOpener = default_file_opener,
) -> dict[str, Any]:
    """Authenticate and return a token-free Figma file summary."""
    file_key, url_node_ids = parse_file_locator(locator)
    node_ids = unique_node_ids([*url_node_ids, *extra_node_ids])
    path = build_request_path(
        file_key,
        node_ids=node_ids,
        depth=depth,
        images=images,
    )
    token = read_access_token(environ)
    status, body = opener(path, {TOKEN_HEADER: token})
    classify_file_status(status)
    return summarize_file_payload(parse_json_object(body), depth)


def build_argument_parser() -> argparse.ArgumentParser:
    """Return the Cloud Agent CLI for Figma file reads."""
    parser = argparse.ArgumentParser(
        prog="figma_rest_file.py",
        description=(
            "Read a Figma file over REST after FIGMA_ACCESS_TOKEN is set. "
            "Prints a token-free JSON outline so a Cloud Agent can continue "
            "design-to-code without Figma MCP."
        ),
    )
    parser.add_argument(
        "locator",
        help="Figma file key or https://www.figma.com/design/<key>/... URL",
    )
    parser.add_argument(
        "--depth",
        type=int,
        default=DEFAULT_TREE_DEPTH,
        help="Tree depth 1-8 (default 2: pages and top-level frames)",
    )
    parser.add_argument(
        "--node-id",
        action="append",
        default=[],
        dest="node_ids",
        help="Figma node id (12:34 or URL form 12-34). Repeatable.",
    )
    parser.add_argument(
        "--images",
        action="store_true",
        help="Render --node-id frames as PNG URLs instead of JSON outline",
    )
    return parser


def parse_cli_args(argv: Sequence[str]) -> argparse.Namespace:
    """Parse CLI arguments, ignoring a leading script path."""
    raw = list(argv)
    if raw and raw[0].endswith("figma_rest_file.py"):
        raw = raw[1:]
    return build_argument_parser().parse_args(raw)


def main(
    argv: list[str] | None = None,
    environ: Mapping[str, str] | None = None,
    opener: FileOpener = default_file_opener,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Read a Figma file and print a token-free JSON outline."""
    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr
    env = environ if environ is not None else os.environ
    try:
        args = parse_cli_args(sys.argv if argv is None else argv)
        summary = fetch_file_document(
            args.locator,
            env,
            extra_node_ids=args.node_ids,
            depth=args.depth,
            images=args.images,
            opener=opener,
        )
        out.write(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    except FigmaAuthError as exc:
        err.write(str(exc) + "\n")
        return exc.exit_code
    except SystemExit as exc:
        code = exc.code
        if code in {None, 0}:
            return EXIT_OK
        if isinstance(code, int):
            return EXIT_INVALID_TARGET if code == 2 else code
        err.write(str(code) + "\n")
        return EXIT_INVALID_TARGET
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    raise SystemExit(main())
