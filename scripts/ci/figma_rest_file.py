#!/usr/bin/env python3
"""Read a Figma file over REST for Cloud Agents.

Cursor Cloud Agents cannot complete Figma MCP OAuth. After
``figma_rest_auth.py`` confirms ``FIGMA_ACCESS_TOKEN``, this helper GETs
``/v1/files/{file_key}`` (optional ``/nodes`` or ``/images``) on a pinned
``api.figma.com`` HTTPS connection. File keys and node IDs are allowlisted
before they enter the request path. The token is never printed. The JSON
outline keeps geometry, solid fills, text, and auto-layout so a Cloud Agent
can implement a frame; Desktop/CLI Figma MCP remains the
``get_design_context`` path.
"""

from __future__ import annotations

import argparse
import http.client
import json
import math
import os
import re
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
NODE_ID_PATTERN = re.compile(r"^I?\d+:\d+(?:;\d+:\d+)*$")
NODE_ID_QUERY = r"I?\d+:\d+(?:(?:;|%3B)\d+:\d+)*"
FILE_URL_TYPES = frozenset({"file", "design", "board", "proto", "slides", "deck", "figjam"})
FILE_URL_HOSTS = frozenset({"www.figma.com", "figma.com"})
ALLOWED_REQUEST_PATH = re.compile(
    r"^/v1/(?:"
    r"files/[A-Za-z0-9]{10,128}(?:\?depth=[1-8])?"
    rf"|files/[A-Za-z0-9]{{10,128}}/nodes\?ids={NODE_ID_QUERY}(?:,{NODE_ID_QUERY})*(?:&depth=[1-8])?"
    rf"|images/[A-Za-z0-9]{{10,128}}\?ids={NODE_ID_QUERY}(?:,{NODE_ID_QUERY})*&format=png"
    r")$"
)
DEFAULT_TREE_DEPTH = 2
MAX_TREE_DEPTH = 8
MAX_FILE_BODY_BYTES = 8_388_608
MAX_NODE_IDS = 16
MAX_TEXT_CHARS = 2_000
MAX_SOLID_FILLS = 8
MAX_CATALOG_ITEMS = 32
MAX_LAYOUT_ABS = 10_000_000
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
    """Return a Figma node id, including instance ids such as ``I12:34;56:78``."""
    candidate = raw.strip().replace("%3B", ";").replace("%3b", ";").replace("-", ":")
    if not NODE_ID_PATTERN.fullmatch(candidate):
        raise FigmaAuthError(
            "Figma node id must look like 12:34 or I12:34;56:78 "
            "(URL hyphens are accepted).",
            EXIT_INVALID_TARGET,
        )
    return candidate


def file_key_from_url_parts(parts: Sequence[str]) -> str:
    """Return the file or branch key from a parsed Figma URL path."""
    if len(parts) >= 4 and parts[2] == "branch":
        return validate_file_key(parts[3])
    if len(parts) >= 5 and parts[3] == "branch":
        return validate_file_key(parts[4])
    return validate_file_key(parts[1])


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
        if parsed.username is not None or parsed.password is not None:
            raise FigmaAuthError(
                "Figma file URLs cannot include userinfo. Paste the "
                "https://www.figma.com/design/<key> URL only.",
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
        node_ids = [validate_node_id(value) for value in parse_qs(parsed.query).get("node-id", [])]
        return file_key_from_url_parts(parts), node_ids
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
    if len(ordered) > MAX_NODE_IDS:
        raise FigmaAuthError(
            f"Pass at most {MAX_NODE_IDS} node ids so the files/images query "
            "stays bounded. Select the frames the buyer asked to implement.",
            EXIT_INVALID_TARGET,
        )
    return ordered


def encode_node_id_query(node_id: str) -> str:
    """Encode ``;`` in instance ids so the query string stays one parameter."""
    return validate_node_id(node_id).replace(";", "%3B")


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
    encoded_ids = ",".join(encode_node_id_query(node_id) for node_id in ids)
    if images:
        if not ids:
            raise FigmaAuthError(
                "Image export needs at least one --node-id so Figma can render "
                "those nodes. Pass the frame id from the Figma URL.",
                EXIT_INVALID_TARGET,
            )
        return f"/v1/images/{key}?ids={encoded_ids}&format=png"
    if ids:
        return f"/v1/files/{key}/nodes?ids={encoded_ids}&depth={depth}"
    return f"/v1/files/{key}?depth={depth}"


def default_file_opener(path: str, headers: Mapping[str, str]) -> tuple[int, bytes]:
    """GET an allowlisted Figma REST path and return ``(status, body)``.

    Host is the string literal ``api.figma.com``. ``path`` must match
    ``ALLOWED_REQUEST_PATH`` so ``file://``, ``..``, and other schemes never
    reach the TLS sink. This path does not call ``urllib.request.urlopen``.
    """
    if ALLOWED_REQUEST_PATH.fullmatch(path) is None:
        raise FigmaAuthError(
            "Figma REST file opener refuses paths other than allowlisted "
            "/v1/files or /v1/images requests on api.figma.com.",
            EXIT_TRANSPORT,
        )
    connection = http.client.HTTPSConnection(  # nosemgrep: python.lang.security.audit.httpsconnection-detected.httpsconnection-detected
        FIGMA_API_HOST,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    try:
        connection.request("GET", path, headers=sanitize_request_headers(headers))
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


def safe_label(value: object) -> str | None:
    """Return a single-line label that cannot look like a Figma token."""
    label = identity_field(value)
    if label is None:
        return None
    if "figd_" in label or TOKEN_ENV_NAME in label:
        return None
    return label


def finite_number(value: object) -> float | None:
    """Return a finite layout number, refusing NaN and unbounded magnitudes."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    if not math.isfinite(number) or abs(number) > MAX_LAYOUT_ABS:
        return None
    return number


def bounding_box(value: object) -> dict[str, float] | None:
    """Return ``x``/``y``/``width``/``height`` from a Figma box object."""
    if not isinstance(value, Mapping):
        return None
    box: dict[str, float] = {}
    for key in ("x", "y", "width", "height"):
        number = finite_number(value.get(key))
        if number is not None:
            box[key] = number
    return box or None


def solid_fills(value: object) -> list[dict[str, Any]]:
    """Return bounded SOLID fill colors from a Figma ``fills`` array."""
    if not isinstance(value, list):
        return []
    fills: list[dict[str, Any]] = []
    for raw_fill in value:
        if len(fills) >= MAX_SOLID_FILLS:
            break
        if not isinstance(raw_fill, Mapping):
            continue
        if safe_label(raw_fill.get("type")) != "SOLID":
            continue
        color = raw_fill.get("color")
        if not isinstance(color, Mapping):
            continue
        channels: dict[str, float] = {}
        for channel in ("r", "g", "b", "a"):
            number = finite_number(color.get(channel))
            if number is not None:
                channels[channel] = number
        if not channels:
            continue
        fill: dict[str, Any] = {"fill_type": "SOLID", "color": channels}
        opacity = finite_number(raw_fill.get("opacity"))
        if opacity is not None:
            fill["opacity"] = opacity
        fills.append(fill)
    return fills


def text_style(value: object) -> dict[str, Any] | None:
    """Return implementable type fields from a Figma TEXT ``style`` object."""
    if not isinstance(value, Mapping):
        return None
    style: dict[str, Any] = {}
    family = safe_label(value.get("fontFamily"))
    align = safe_label(value.get("textAlignHorizontal"))
    if family is not None:
        style["font_family"] = family
    weight = finite_number(value.get("fontWeight"))
    if weight is not None:
        style["font_weight"] = weight
    size = finite_number(value.get("fontSize"))
    if size is not None:
        style["font_size"] = size
    if align is not None:
        style["text_align"] = align
    letter_spacing = finite_number(value.get("letterSpacing"))
    if letter_spacing is not None:
        style["letter_spacing"] = letter_spacing
    line_height = finite_number(value.get("lineHeightPx"))
    if line_height is not None:
        style["line_height_px"] = line_height
    return style or None


def layout_metrics(node: Mapping[str, Any]) -> dict[str, Any]:
    """Return auto-layout and padding fields used to implement a frame."""
    metrics: dict[str, Any] = {}
    layout_mode = safe_label(node.get("layoutMode"))
    if layout_mode is not None:
        metrics["layout_mode"] = layout_mode
    primary = safe_label(node.get("primaryAxisAlignItems"))
    if primary is not None:
        metrics["primary_axis_align"] = primary
    counter = safe_label(node.get("counterAxisAlignItems"))
    if counter is not None:
        metrics["counter_axis_align"] = counter
    for source, dest in (
        ("paddingLeft", "padding_left"),
        ("paddingRight", "padding_right"),
        ("paddingTop", "padding_top"),
        ("paddingBottom", "padding_bottom"),
        ("itemSpacing", "item_spacing"),
        ("cornerRadius", "corner_radius"),
        ("opacity", "opacity"),
        ("strokeWeight", "stroke_weight"),
    ):
        number = finite_number(node.get(source))
        if number is not None:
            metrics[dest] = number
    return metrics


def constraint_axes(value: object) -> dict[str, str] | None:
    """Return horizontal/vertical constraints from a Figma node."""
    if not isinstance(value, Mapping):
        return None
    axes: dict[str, str] = {}
    horizontal = safe_label(value.get("horizontal"))
    vertical = safe_label(value.get("vertical"))
    if horizontal is not None:
        axes["horizontal"] = horizontal
    if vertical is not None:
        axes["vertical"] = vertical
    return axes or None


def bounded_text(value: object) -> str | None:
    """Return TEXT ``characters`` capped so a prompt cannot swallow the file."""
    text = safe_label(value)
    if text is None:
        return None
    if len(text) > MAX_TEXT_CHARS:
        return text[:MAX_TEXT_CHARS]
    return text


def named_catalog(value: object, name_key: str, type_key: str | None) -> list[dict[str, str]]:
    """Return bounded component/style metadata without access tokens."""
    if not isinstance(value, Mapping):
        return []
    items: list[dict[str, str]] = []
    for raw_key, raw_item in value.items():
        if len(items) >= MAX_CATALOG_ITEMS:
            break
        if not isinstance(raw_item, Mapping):
            continue
        name = safe_label(raw_item.get("name"))
        if name is None:
            continue
        entry = {name_key: name}
        catalog_key = safe_label(raw_item.get("key")) or safe_label(raw_key)
        if catalog_key is not None:
            entry["catalog_key"] = catalog_key
        if type_key is not None:
            style_type = safe_label(raw_item.get(type_key))
            if style_type is not None:
                entry["style_type"] = style_type
        description = bounded_text(raw_item.get("description"))
        if description is not None:
            entry["description"] = description
        items.append(entry)
    return items


def style_references(value: object) -> dict[str, str]:
    """Return safe node style references that link nodes to the style catalog."""
    if not isinstance(value, Mapping):
        return {}
    references: dict[str, str] = {}
    for raw_type, raw_id in value.items():
        style_type = safe_label(raw_type)
        style_id = safe_label(raw_id)
        if style_type is not None and style_id is not None:
            references[style_type] = style_id
    return references


def outline_node(node: object, remaining_depth: int) -> dict[str, Any] | None:
    """Return a token-free implementable outline of one Figma node."""
    if not isinstance(node, Mapping):
        return None
    summary: dict[str, Any] = {}
    node_id = safe_label(node.get("id"))
    name = safe_label(node.get("name"))
    node_type = safe_label(node.get("type"))
    if node_id is not None:
        summary["node_id"] = node_id
    if name is not None:
        summary["node_name"] = name
    if node_type is not None:
        summary["node_type"] = node_type
    box = bounding_box(node.get("absoluteBoundingBox"))
    if box is not None:
        summary["absolute_bounding_box"] = box
    fills = solid_fills(node.get("fills"))
    if fills:
        summary["solid_fills"] = fills
    style = text_style(node.get("style"))
    if style is not None:
        summary["text_style"] = style
    characters = bounded_text(node.get("characters"))
    if characters is not None:
        summary["characters"] = characters
    metrics = layout_metrics(node)
    if metrics:
        summary["layout"] = metrics
    constraints = constraint_axes(node.get("constraints"))
    if constraints is not None:
        summary["constraints"] = constraints
    style_refs = style_references(node.get("styles"))
    if style_refs:
        summary["style_references"] = style_refs
    if remaining_depth > 0:
        children = node.get("children")
        if isinstance(children, list):
            outlined = [outline_node(child, remaining_depth - 1) for child in children]
            summary["child_nodes"] = [child for child in outlined if child is not None]
    return summary or None


def allowed_image_host(host: str) -> bool:
    """Return whether ``host`` is a Figma or Figma-S3 image origin."""
    lowered = host.lower().rstrip(".")
    if lowered == "figma.com" or lowered.endswith(".figma.com"):
        return True
    return lowered.startswith("figma-") and lowered.endswith(".amazonaws.com")


def https_image_url(value: object) -> str | None:
    """Return a https Figma/S3 image URL, refusing token-shaped values."""
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if "figd_" in cleaned or TOKEN_ENV_NAME in cleaned:
        return None
    parsed = urlparse(cleaned)
    if parsed.scheme != "https":
        return None
    if parsed.username is not None or parsed.password is not None:
        return None
    host = parsed.hostname or ""
    if not allowed_image_host(host):
        return None
    return cleaned


def summarize_file_payload(payload: Mapping[str, Any], outline_depth: int) -> dict[str, Any]:
    """Return a compact, token-free file, node, or image summary."""
    summary: dict[str, Any] = {}
    file_name = safe_label(payload.get("name"))
    last_modified = safe_label(payload.get("lastModified"))
    version = safe_label(payload.get("version"))
    editor_type = safe_label(payload.get("editorType"))
    role = safe_label(payload.get("role"))
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
    thumbnail = https_image_url(payload.get("thumbnailUrl"))
    if thumbnail is not None:
        summary["thumbnail_url"] = thumbnail
    document = outline_node(payload.get("document"), outline_depth)
    if document is not None:
        summary["document_outline"] = document
    components = named_catalog(payload.get("components"), "component_name", None)
    if components:
        summary["component_names"] = components
    component_sets = named_catalog(payload.get("componentSets"), "component_set_name", None)
    if component_sets:
        summary["component_set_catalog"] = component_sets
    styles = named_catalog(payload.get("styles"), "style_name", "styleType")
    if styles:
        summary["style_catalog"] = styles
    raw_nodes = payload.get("nodes")
    if isinstance(raw_nodes, Mapping):
        nodes: dict[str, Any] = {}
        for raw_id, raw_node in raw_nodes.items():
            normalized = str(raw_id).replace("%3B", ";").replace("%3b", ";").replace("-", ":")
            node_id = validate_node_id(normalized) if NODE_ID_PATTERN.fullmatch(normalized) else None
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
            "Prints a token-free JSON outline with geometry, solid fills, "
            "text, and auto-layout. Desktop/CLI Figma MCP remains the "
            "get_design_context path."
        ),
    )
    parser.add_argument(
        "locator",
        help="Figma file or branch key, or https://www.figma.com/design/<key>/... URL",
    )
    parser.add_argument(
        "--depth",
        type=int,
        default=DEFAULT_TREE_DEPTH,
        help=(
            "Tree depth 1-8. GET /v1/files uses pages + top-level frames at 2; "
            "GET /v1/files/.../nodes counts levels under the selected node"
        ),
    )
    parser.add_argument(
        "--node-id",
        action="append",
        default=[],
        dest="node_ids",
        help="Figma node id (12:34, I12:34;56:78, or URL hyphen form). Repeatable.",
    )
    parser.add_argument(
        "--images",
        action="store_true",
        help="Render --node-id frames as expiring HTTPS PNG URLs instead of JSON outline",
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
