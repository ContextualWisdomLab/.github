"""Contracts for Cloud Agent Figma REST file reads."""

from __future__ import annotations

import io
import json
from pathlib import Path
import ssl
from typing import Any

import pytest

from scripts.ci import figma_rest_auth as auth
from scripts.ci import figma_rest_file as files

ROOT = Path(__file__).resolve().parents[1]
DOCTORING = ROOT / "docs" / "doctoring" / "figma-cloud-agent-mcp-auth.md"
AGENTS = ROOT / "AGENTS.md"
MASTER = ROOT / "docs" / "CWL-MASTER-CONTEXT.md"
CHANGELOG = ROOT / "CHANGELOG.md"
ARCHITECTURE = ROOT / "ARCHITECTURE.md"
CLAUDE = ROOT / "CLAUDE.md"
TOKEN = "figd_test_token_must_never_appear"
FILE_KEY = "TestFileKey0123456789"
FILE_URL = f"https://www.figma.com/design/{FILE_KEY}/Checkout?node-id=12-34"


def _file_body(**fields: object) -> bytes:
    """Return a Figma file JSON body."""
    return json.dumps(fields).encode("utf-8")


def test_validate_file_key_rejects_paths_and_schemes() -> None:
    """File keys cannot smuggle slashes, dots, or URL schemes."""
    for raw in ("", "short", "../passwd", "file://x", "https://x", "abc/def", "key with space"):
        with pytest.raises(auth.FigmaAuthError) as invalid:
            files.validate_file_key(raw)
        assert invalid.value.exit_code == files.EXIT_INVALID_TARGET
        assert TOKEN not in str(invalid.value)
    assert files.validate_file_key(f"  {FILE_KEY} \n") == FILE_KEY


def test_validate_node_id_accepts_url_hyphen_form() -> None:
    """Figma share URLs use 12-34; the REST API uses 12:34."""
    assert files.validate_node_id("12-34") == "12:34"
    assert files.validate_node_id("12:34") == "12:34"
    assert files.validate_node_id("I12-34;56-78") == "I12:34;56:78"
    assert files.validate_node_id("I12:34%3B56:78") == "I12:34;56:78"
    assert files.validate_node_id("I12:34%3b56:78") == "I12:34;56:78"
    with pytest.raises(auth.FigmaAuthError) as invalid:
        files.validate_node_id("root")
    assert invalid.value.exit_code == files.EXIT_INVALID_TARGET


def test_parse_file_locator_reads_design_url() -> None:
    """A Figma design URL yields the file key and node-id query."""
    key, node_ids = files.parse_file_locator(FILE_URL)
    assert key == FILE_KEY
    assert node_ids == ["12:34"]
    assert files.parse_file_locator(FILE_KEY) == (FILE_KEY, [])


@pytest.mark.parametrize(
    "locator",
    [
        "",
        "file:///etc/passwd",
        "http://www.figma.com/design/TestFileKey0123456789/x",
        "https://api.figma.com/v1/files/TestFileKey0123456789",
        "https://www.figma.com/onlykey",
        "https://www.figma.com/unknown/TestFileKey0123456789/x",
        "www.figma.com/design/nope/x",
        "https://www.figma.com@evil.example/design/TestFileKey0123456789/x",
        f"https://user:pass@www.figma.com/design/{FILE_KEY}/x",
    ],
)
def test_parse_file_locator_refuses_unsafe_or_incomplete_urls(locator: str) -> None:
    """Non-https, non-figma, and incomplete locators fail closed."""
    with pytest.raises(auth.FigmaAuthError) as invalid:
        files.parse_file_locator(locator)
    assert invalid.value.exit_code == files.EXIT_INVALID_TARGET


def test_parse_file_locator_accepts_host_without_scheme() -> None:
    """Operators may paste www.figma.com/... without the scheme prefix."""
    key, node_ids = files.parse_file_locator(f"www.figma.com/file/{FILE_KEY}/Home")
    assert key == FILE_KEY
    assert node_ids == []


def test_parse_file_locator_uses_branch_key_not_main_file() -> None:
    """A branch URL must GET the branch key, not silently outline main."""
    branch_key = "BranchKey901234567890"
    key, node_ids = files.parse_file_locator(
        f"https://www.figma.com/design/{FILE_KEY}/branch/{branch_key}/Checkout"
    )
    assert key == branch_key
    assert node_ids == []
    named = files.parse_file_locator(
        f"https://figma.com/design/{FILE_KEY}/Checkout/branch/{branch_key}/Alt"
    )
    assert named == (branch_key, [])


def test_unique_node_ids_preserve_first_seen_order() -> None:
    """Repeated node ids from a URL plus --node-id stay unique."""
    assert files.unique_node_ids(["12-34", "12:34", "1:2"]) == ["12:34", "1:2"]


def test_unique_node_ids_reject_unbounded_lists() -> None:
    """A huge --node-id list cannot build an unbounded images query."""
    too_many = [f"1:{index}" for index in range(files.MAX_NODE_IDS + 1)]
    with pytest.raises(auth.FigmaAuthError) as bounded:
        files.unique_node_ids(too_many)
    assert bounded.value.exit_code == files.EXIT_INVALID_TARGET
    assert str(files.MAX_NODE_IDS) in str(bounded.value)


def test_build_request_path_emits_only_allowlisted_shapes() -> None:
    """File, node, and image paths stay inside the opener allowlist."""
    file_path = files.build_request_path(FILE_KEY)
    assert file_path == f"/v1/files/{FILE_KEY}?depth=2"
    assert files.ALLOWED_REQUEST_PATH.fullmatch(file_path)
    nodes_path = files.build_request_path(FILE_KEY, node_ids=["12:34"], depth=1)
    assert nodes_path == f"/v1/files/{FILE_KEY}/nodes?ids=12:34&depth=1"
    assert files.ALLOWED_REQUEST_PATH.fullmatch(nodes_path)
    image_path = files.build_request_path(FILE_KEY, node_ids=["12:34"], images=True)
    assert image_path == f"/v1/images/{FILE_KEY}?ids=12:34&format=png"
    assert files.ALLOWED_REQUEST_PATH.fullmatch(image_path)
    instance_path = files.build_request_path(FILE_KEY, node_ids=["I12:34;56:78"], images=True)
    assert instance_path == f"/v1/images/{FILE_KEY}?ids=I12:34%3B56:78&format=png"
    assert files.ALLOWED_REQUEST_PATH.fullmatch(instance_path)


def test_build_request_path_rejects_images_without_nodes_and_bad_depth() -> None:
    """Image export and depth stay fail-closed for the operator."""
    with pytest.raises(auth.FigmaAuthError) as missing_nodes:
        files.build_request_path(FILE_KEY, images=True)
    assert missing_nodes.value.exit_code == files.EXIT_INVALID_TARGET
    for depth in (0, 9, True):
        with pytest.raises(auth.FigmaAuthError) as invalid_depth:
            files.build_request_path(FILE_KEY, depth=depth)  # type: ignore[arg-type]
        assert invalid_depth.value.exit_code == files.EXIT_INVALID_TARGET


def test_default_file_opener_refuses_non_allowlisted_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``file://`` and host-relative traversal never construct TLS."""
    constructed: list[object] = []

    def forbidden_connection(*args: object, **kwargs: object) -> object:
        """Fail if a rejected Figma path reaches the network constructor."""
        constructed.append((args, kwargs))
        raise AssertionError("file opener must not connect for a refused path")

    monkeypatch.setattr(files.http.client, "HTTPSConnection", forbidden_connection)
    for path in (
        "file:///etc/passwd",
        "/v1/files/../secrets",
        f"/v1/files/{FILE_KEY}?callback=http://evil",
        "/v1/me",
    ):
        with pytest.raises(auth.FigmaAuthError) as refused:
            files.default_file_opener(path, {auth.TOKEN_HEADER: TOKEN})
        assert refused.value.exit_code == auth.EXIT_TRANSPORT
        assert TOKEN not in str(refused.value)
    assert constructed == []


class _FakeFileResponse:
    """Minimal ``HTTPResponse`` stand-in for ``HTTPSConnection.getresponse``."""

    def __init__(self, status: int, body: bytes) -> None:
        """Record the canned status and body."""
        self.status = status
        self._body = body

    def read(self, amt: int | None = None) -> bytes:
        """Return the canned body, honoring an optional byte limit."""
        if amt is None:
            return self._body
        return self._body[:amt]


class _FakeFileConnection:
    """Record the pinned Figma origin used by ``default_file_opener``."""

    last: _FakeFileConnection | None = None

    def __init__(
        self,
        host: str,
        timeout: int = 0,
        context: ssl.SSLContext | None = None,
    ) -> None:
        """Capture the TLS host and timeout."""
        self.host = host
        self.timeout = timeout
        self.context = context
        self.method = ""
        self.path = ""
        self.headers: dict[str, str] = {}
        self.closed = False
        self._status = 200
        self._body = b'{"name":"Checkout"}'
        type(self).last = self

    def request(self, method: str, path: str, headers: dict[str, str] | None = None) -> None:
        """Record the allowlisted GET."""
        self.method = method
        self.path = path
        self.headers = dict(headers or {})

    def getresponse(self) -> _FakeFileResponse:
        """Return the canned file response."""
        return _FakeFileResponse(self._status, self._body)

    def close(self) -> None:
        """Mark the connection closed."""
        self.closed = True


def test_default_file_opener_reads_success_body(monkeypatch: pytest.MonkeyPatch) -> None:
    """A successful HTTPS response yields its status and body bytes."""
    monkeypatch.setattr(files.http.client, "HTTPSConnection", _FakeFileConnection)
    path = files.build_request_path(FILE_KEY)
    status, body = files.default_file_opener(path, {auth.TOKEN_HEADER: TOKEN})
    assert status == 200
    assert body == b'{"name":"Checkout"}'
    connection = _FakeFileConnection.last
    assert connection is not None
    assert connection.host == "api.figma.com"
    assert connection.timeout == auth.REQUEST_TIMEOUT_SECONDS
    assert isinstance(connection.context, ssl.SSLContext)
    assert connection.method == "GET"
    assert connection.path == path
    assert connection.headers == {auth.TOKEN_HEADER: TOKEN}
    assert connection.closed is True


def test_default_file_opener_rejects_oversize_body(monkeypatch: pytest.MonkeyPatch) -> None:
    """A file body larger than 8 MiB is a transport failure."""

    class HugeConnection(_FakeFileConnection):
        """Return more bytes than the file cap."""

        def __init__(
            self,
            host: str,
            timeout: int = 0,
            context: ssl.SSLContext | None = None,
        ) -> None:
            """Initialize an oversized body."""
            super().__init__(host, timeout, context)
            self._body = b"x" * (files.MAX_FILE_BODY_BYTES + 1)

    monkeypatch.setattr(files.http.client, "HTTPSConnection", HugeConnection)
    with pytest.raises(auth.FigmaAuthError) as oversize:
        files.default_file_opener(files.build_request_path(FILE_KEY), {auth.TOKEN_HEADER: TOKEN})
    assert oversize.value.exit_code == auth.EXIT_TRANSPORT
    assert str(files.MAX_FILE_BODY_BYTES) in str(oversize.value)


def test_default_file_opener_wraps_os_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """Network failures become ``EXIT_TRANSPORT`` without leaking the token."""

    class FailingConnection(_FakeFileConnection):
        """Raise a transport error after the host is already pinned."""

        def request(self, method: str, path: str, headers: dict[str, str] | None = None) -> None:
            """Fail after recording the request."""
            super().request(method, path, headers)
            raise TimeoutError("timed out")

    monkeypatch.setattr(files.http.client, "HTTPSConnection", FailingConnection)
    with pytest.raises(auth.FigmaAuthError) as transport:
        files.default_file_opener(files.build_request_path(FILE_KEY), {auth.TOKEN_HEADER: TOKEN})
    assert transport.value.exit_code == auth.EXIT_TRANSPORT
    assert "timed out" in str(transport.value)
    assert TOKEN not in str(transport.value)
    assert FailingConnection.last is not None
    assert FailingConnection.last.closed is True


def test_parse_json_object_rejects_non_objects() -> None:
    """Non-JSON and non-object bodies are transport failures."""
    with pytest.raises(auth.FigmaAuthError) as invalid_json:
        files.parse_json_object(b"not-json")
    assert invalid_json.value.exit_code == auth.EXIT_TRANSPORT
    with pytest.raises(auth.FigmaAuthError) as not_object:
        files.parse_json_object(b'["file"]')
    assert not_object.value.exit_code == auth.EXIT_TRANSPORT
    with pytest.raises(auth.FigmaAuthError):
        files.parse_json_object(b"\xff")


def test_outline_and_image_summary_stay_token_free() -> None:
    """Outlines keep names and drop token-shaped or non-https image URLs."""
    assert files.outline_node("not-a-node", 2) is None
    assert files.outline_node({"children": "nope"}, 2) is None
    outline = files.outline_node(
        {
            "id": "0:0",
            "name": "Document",
            "type": "DOCUMENT",
            "children": [
                {"id": "1:2", "name": "Page 1", "type": "CANVAS", "children": [{"id": "3:4"}]}
            ],
        },
        1,
    )
    assert outline is not None
    assert outline["node_id"] == "0:0"
    assert outline["child_nodes"][0]["node_name"] == "Page 1"
    assert "child_nodes" not in outline["child_nodes"][0]
    designed = files.outline_node(
        {
            "id": "I12:34;56:78",
            "name": "Hero",
            "type": "FRAME",
            "absoluteBoundingBox": {"x": 0, "y": 8, "width": 360, "height": 80},
            "fills": [
                {"type": "SOLID", "color": {"r": 0.1, "g": 0.2, "b": 0.3, "a": 1}, "opacity": 0.9},
                {"type": "IMAGE"},
                "skip",
            ],
            "style": {
                "fontFamily": "Inter",
                "fontWeight": 600,
                "fontSize": 16,
                "textAlignHorizontal": "CENTER",
                "letterSpacing": 0.2,
                "lineHeightPx": 24,
            },
            "characters": "Pay now",
            "layoutMode": "HORIZONTAL",
            "primaryAxisAlignItems": "CENTER",
            "counterAxisAlignItems": "CENTER",
            "paddingLeft": 16,
            "constraints": {"horizontal": "SCALE", "vertical": "TOP"},
        },
        0,
    )
    assert designed is not None
    assert designed["node_id"] == "I12:34;56:78"
    assert designed["absolute_bounding_box"]["width"] == 360
    assert designed["solid_fills"][0]["color"]["r"] == 0.1
    assert designed["text_style"]["font_family"] == "Inter"
    assert designed["characters"] == "Pay now"
    assert designed["layout"]["layout_mode"] == "HORIZONTAL"
    assert designed["constraints"]["horizontal"] == "SCALE"
    assert files.https_image_url(None) is None
    assert files.https_image_url("http://insecure.example/x") is None
    assert files.https_image_url(f"https://x/{TOKEN}") is None
    assert files.https_image_url(f"https://x/{auth.TOKEN_ENV_NAME}") is None
    assert files.https_image_url("https://evil.example/x.png") is None
    assert files.https_image_url("https://user:pass@figma-alpha-api.s3.amazonaws.com/x.png") is None
    assert files.https_image_url("https://figma-alpha-api.s3.amazonaws.com/x.png")
    assert files.https_image_url("https://s3-alpha-sig.figma.com/img/x")


def test_summarize_file_payload_covers_file_nodes_and_images() -> None:
    """File metadata, selected nodes, and https image URLs are kept."""
    empty = files.summarize_file_payload({}, 2)
    assert empty["read_status"].startswith("Figma REST file read succeeded")
    summary = files.summarize_file_payload(
        {
            "name": "Checkout",
            "lastModified": "2026-08-16T00:00:00Z",
            "version": "9",
            "editorType": "figma",
            "role": "viewer",
            "thumbnailUrl": "https://figma-alpha-api.s3.amazonaws.com/thumb.png",
            "document": {"id": "0:0", "name": "Document", "type": "DOCUMENT"},
            "components": {"1:9": {"key": "component-key", "name": "Button"}, "bad": "skip", "1:8": {"name": None}},
            "componentSets": {"2:9": {"key": "set-key", "name": "Controls"}},
            "styles": {"S:1": {"key": "style-key", "name": "Ink", "styleType": "FILL", "description": "Brand ink"}, "bad": []},
            "nodes": {
                "12:34": {"document": {"id": "12:34", "name": "Hero", "type": "FRAME", "styles": {"FILL": "S:1"}}},
                "I12:34;56:78": {"document": {"id": "I12:34;56:78", "name": "Instance"}},
                "skip": {"document": {"id": "9:9"}},
                "1:2": "not-a-map",
            },
            "images": {
                "12:34": "https://figma-alpha-api.s3.amazonaws.com/hero.png",
                "1:2": None,
            },
        },
        2,
    )
    assert summary["file_name"] == "Checkout"
    assert summary["last_modified"] == "2026-08-16T00:00:00Z"
    assert summary["file_version"] == "9"
    assert summary["editor_type"] == "figma"
    assert summary["viewer_role"] == "viewer"
    assert summary["thumbnail_url"].startswith("https://")
    assert summary["component_names"][0]["component_name"] == "Button"
    assert summary["component_names"][0]["catalog_key"] == "component-key"
    assert summary["component_set_catalog"][0]["component_set_name"] == "Controls"
    assert summary["style_catalog"][0]["style_name"] == "Ink"
    assert summary["style_catalog"][0]["catalog_key"] == "style-key"
    assert summary["style_catalog"][0]["source_key"] == "S:1"
    assert summary["style_catalog"][0]["description"] == "Brand ink"
    assert summary["document_outline"]["node_type"] == "DOCUMENT"
    assert summary["selected_nodes"]["12:34"]["node_name"] == "Hero"
    assert summary["selected_nodes"]["12:34"]["style_references"] == {"FILL": "S:1"}
    assert summary["selected_nodes"]["I12:34;56:78"]["node_name"] == "Instance"
    assert "skip" not in summary["selected_nodes"]
    assert summary["image_urls"]["12:34"].startswith("https://")
    filtered = files.summarize_file_payload(
        {
            "nodes": {"skip": {"document": {"id": "9:9"}}, "1:2": "not-a-map"},
            "images": {"1:2": None, "3:4": "http://insecure.example/x"},
        },
        2,
    )
    assert "selected_nodes" not in filtered
    assert "image_urls" not in filtered
    assert filtered["read_status"].startswith("Figma REST file read succeeded")


def test_summarize_file_payload_collects_nested_node_catalogs() -> None:
    """Node endpoint catalogs remain available alongside node style references."""
    summary = files.summarize_file_payload(
        {
            "nodes": {
                "12:34": {
                    "document": {
                        "id": "12:34",
                        "name": "Hero",
                        "type": "FRAME",
                        "styles": {"FILL": "S:1"},
                    },
                    "components": {"1:9": {"name": "Button"}},
                    "componentSets": {"2:9": {"name": "Controls"}},
                    "styles": {
                        "S:1": {
                            "key": "style-key",
                            "name": "Ink",
                            "styleType": "FILL",
                        }
                    },
                }
            }
        },
        2,
    )
    assert summary["component_names"][0]["component_name"] == "Button"
    assert summary["component_set_catalog"][0]["component_set_name"] == "Controls"
    assert summary["style_catalog"][0]["source_key"] == "S:1"
    assert summary["selected_nodes"]["12:34"]["style_references"] == {"FILL": "S:1"}


@pytest.mark.parametrize(
    ("status", "exit_code"),
    [
        (401, auth.EXIT_REJECTED),
        (403, auth.EXIT_REJECTED),
        (404, files.EXIT_NOT_FOUND),
        (400, files.EXIT_INVALID_TARGET),
        (503, auth.EXIT_TRANSPORT),
    ],
)
def test_classify_file_status_maps_operator_next_action(status: int, exit_code: int) -> None:
    """HTTP classes tell the operator whether to rotate, fix the key, or retry."""
    with pytest.raises(auth.FigmaAuthError) as classified:
        files.classify_file_status(status)
    assert classified.value.exit_code == exit_code
    assert TOKEN not in str(classified.value)


def test_fetch_file_document_reads_url_and_extra_node_ids() -> None:
    """A 200 file response becomes a token-free outline for design-to-code."""
    seen: dict[str, Any] = {}

    def opener(path: str, headers: dict[str, str]) -> tuple[int, bytes]:
        """Capture the allowlisted file path and return a bounded fixture."""
        seen["path"] = path
        seen["headers"] = dict(headers)
        return 200, _file_body(
            name="Checkout",
            document={"id": "0:0", "name": "Document", "type": "DOCUMENT"},
        )

    summary = files.fetch_file_document(
        FILE_URL,
        {auth.TOKEN_ENV_NAME: TOKEN},
        extra_node_ids=["1:2"],
        opener=opener,
    )
    assert seen["path"] == f"/v1/files/{FILE_KEY}/nodes?ids=12:34,1:2&depth=2"
    assert seen["headers"] == {auth.TOKEN_HEADER: TOKEN}
    assert summary["file_name"] == "Checkout"
    assert TOKEN not in json.dumps(summary)


def test_fetch_file_document_rejects_unauthorized_token() -> None:
    """401/403 stay distinct from a missing file key."""

    def opener(path: str, headers: dict[str, str]) -> tuple[int, bytes]:
        """Return an unauthorized Figma response."""
        del path, headers
        return 403, b'{"status":403,"err":"Invalid token"}'

    with pytest.raises(auth.FigmaAuthError) as rejected:
        files.fetch_file_document(FILE_KEY, {auth.TOKEN_ENV_NAME: TOKEN}, opener=opener)
    assert rejected.value.exit_code == auth.EXIT_REJECTED
    assert TOKEN not in str(rejected.value)


def test_helper_pins_https_origin_instead_of_dynamic_urllib() -> None:
    """The fixed TLS sink has one scoped Semgrep false-positive suppression."""
    source = Path(files.__file__).read_text(encoding="utf-8")
    assert "urlopen(" not in source
    assert "http.client.HTTPSConnection" in source
    assert '"api.figma.com"' in source or "FIGMA_API_HOST" in source
    assert source.count(
        "# nosemgrep: "
        "python.lang.security.audit.httpsconnection-detected.httpsconnection-detected"
    ) == 1


def test_main_writes_json_and_error_channels() -> None:
    """CLI success and failure stay on stdout/stderr and never echo the token."""
    stdout = io.StringIO()
    stderr = io.StringIO()

    def opener(path: str, headers: dict[str, str]) -> tuple[int, bytes]:
        """Return a valid file fixture for the CLI success path."""
        del path, headers
        return 200, _file_body(name="Checkout")

    ok = files.main(
        argv=["figma_rest_file.py", FILE_KEY],
        environ={auth.TOKEN_ENV_NAME: TOKEN},
        opener=opener,
        stdout=stdout,
        stderr=stderr,
    )
    assert ok == auth.EXIT_OK
    assert json.loads(stdout.getvalue())["file_name"] == "Checkout"
    assert stderr.getvalue() == ""
    assert TOKEN not in stdout.getvalue()

    missing_out = io.StringIO()
    missing_err = io.StringIO()
    missing = files.main(
        argv=[FILE_KEY],
        environ={},
        opener=opener,
        stdout=missing_out,
        stderr=missing_err,
    )
    assert missing == auth.EXIT_MISSING_TOKEN
    assert missing_out.getvalue() == ""
    assert auth.TOKEN_ENV_NAME in missing_err.getvalue()


def test_main_uses_process_streams_when_unspecified(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The default CLI path reads ``os.environ`` and writes process streams."""
    monkeypatch.setenv(auth.TOKEN_ENV_NAME, TOKEN)

    def opener(path: str, headers: dict[str, str]) -> tuple[int, bytes]:
        """Return a valid file fixture through process streams."""
        del path
        assert headers[auth.TOKEN_HEADER] == TOKEN
        return 200, _file_body(name="Home")

    monkeypatch.setattr(
        "sys.argv",
        ["figma_rest_file.py", FILE_KEY, "--depth", "1", "--node-id", "1:2", "--images"],
    )
    assert files.main(opener=opener) == auth.EXIT_OK
    captured = capsys.readouterr()
    assert json.loads(captured.out)["file_name"] == "Home"
    assert TOKEN not in captured.out


def test_main_maps_argparse_errors_to_invalid_target(capsys: pytest.CaptureFixture[str]) -> None:
    """A missing locator tells the operator to pass a file key or URL."""
    assert files.main(argv=["figma_rest_file.py"], environ={}) == files.EXIT_INVALID_TARGET
    captured = capsys.readouterr()
    assert captured.err
    assert files.main(argv=["figma_rest_file.py", "--help"], environ={}) == auth.EXIT_OK


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (SystemExit(), auth.EXIT_OK),
        (SystemExit(3), 3),
        (SystemExit("usage exploded"), files.EXIT_INVALID_TARGET),
    ],
)
def test_main_maps_system_exit_shapes(exc: SystemExit, expected: int) -> None:
    """Argparse abort codes stay fail-closed and never echo the token."""
    stderr = io.StringIO()

    def boom(_argv: list[str]) -> None:
        """Raise the parametrized argparse shape under test."""
        raise exc

    original = files.parse_cli_args
    files.parse_cli_args = boom  # type: ignore[method-assign]
    try:
        code = files.main(argv=[FILE_KEY], environ={}, stdout=io.StringIO(), stderr=stderr)
    finally:
        files.parse_cli_args = original  # type: ignore[method-assign]
    assert code == expected
    if expected == files.EXIT_INVALID_TARGET:
        assert "usage exploded" in stderr.getvalue()
    assert TOKEN not in stderr.getvalue()


def test_doctoring_and_entry_docs_pin_file_read_fallback() -> None:
    """Agents must run the file helper, not treat whoami as file read."""
    doctoring = DOCTORING.read_text(encoding="utf-8")
    agents = AGENTS.read_text(encoding="utf-8")
    master = MASTER.read_text(encoding="utf-8")
    changelog = CHANGELOG.read_text(encoding="utf-8")
    architecture = ARCHITECTURE.read_text(encoding="utf-8")
    claude = CLAUDE.read_text(encoding="utf-8")
    for text in (doctoring, agents, master):
        assert "FIGMA_ACCESS_TOKEN" in text
        assert "mcp.figma.com" in text
        assert "scripts/ci/figma_rest_file.py" in text
    assert "APA 7th references" in doctoring
    assert "Retrieved August 16, 2026" in doctoring
    assert "file-endpoints" in doctoring
    assert "CWE-22" in doctoring
    assert "CWE-918" in doctoring
    assert "get_design_context" in doctoring
    assert "plan access token" in doctoring
    assert "X-Figma-Token" in changelog
    assert "scripts/ci/figma_rest_file.py" in changelog
    assert "Figma Cloud Agent REST" in architecture
    assert "FIGMA_ACCESS_TOKEN" in claude
    assert "docs/doctoring/figma-cloud-agent-mcp-auth.md" in agents
    assert "docs/doctoring/figma-cloud-agent-mcp-auth.md" in master


def test_design_field_helpers_stay_bounded_and_token_free() -> None:
    """Geometry, fill, type, and catalog helpers refuse junk and tokens."""
    assert files.safe_label(f"keep {TOKEN}") is None
    assert files.safe_label(auth.TOKEN_ENV_NAME) is None
    assert files.finite_number(True) is None
    assert files.finite_number("8") is None
    assert files.finite_number(float("nan")) is None
    assert files.finite_number(float("inf")) is None
    assert files.finite_number(files.MAX_LAYOUT_ABS + 1) is None
    assert files.finite_number(12) == 12.0
    assert files.bounding_box("nope") is None
    assert files.bounding_box({"x": True}) is None
    assert files.solid_fills("nope") == []
    assert files.solid_fills([{"type": "SOLID", "color": {"r": True}}]) == []
    assert files.solid_fills([{"type": "SOLID", "color": "nope"}]) == []
    overflow = [{"type": "SOLID", "color": {"r": 1}} for _ in range(files.MAX_SOLID_FILLS + 2)]
    assert len(files.solid_fills(overflow)) == files.MAX_SOLID_FILLS
    assert files.text_style("nope") is None
    assert files.text_style({}) is None
    assert files.constraint_axes("nope") is None
    assert files.constraint_axes({}) is None
    assert files.bounded_text("  ") is None
    long_text = "a" * (files.MAX_TEXT_CHARS + 8)
    assert files.bounded_text(long_text) == "a" * files.MAX_TEXT_CHARS
    assert files.named_catalog("nope", "component_name", None) == []
    assert files.named_catalog({"1": {"name": "Ink"}}, "style_name", "styleType") == [
        {"style_name": "Ink", "catalog_key": "1"}
    ]
    assert files.named_catalog({"": {"name": "No key"}}, "style_name", None) == [
        {"style_name": "No key"}
    ]
    assert files.style_references({"FILL": None, None: "S:1"}) == {}
    catalog = {str(index): {"name": f"C{index}"} for index in range(files.MAX_CATALOG_ITEMS + 3)}
    assert len(files.named_catalog(catalog, "component_name", None)) == files.MAX_CATALOG_ITEMS
    assert files.allowed_image_host("figma.com") is True
    assert files.allowed_image_host("evil.amazonaws.com") is False
    assert files.allowed_image_host("figma-x.attacker.amazonaws.com") is False
    assert files.encode_node_id_query("I1:2;3:4") == "I1:2%3B3:4"
    metrics = files.layout_metrics(
        {
            "paddingRight": 1,
            "paddingTop": 2,
            "paddingBottom": 3,
            "itemSpacing": 4,
            "cornerRadius": 5,
            "opacity": 0.5,
            "strokeWeight": 1,
        }
    )
    assert metrics["padding_right"] == 1
    assert metrics["stroke_weight"] == 1


def test_live_unauthenticated_file_read_is_rejected_by_figma() -> None:
    """The real files endpoint rejects a missing token with HTTP 401/403/404."""
    status, body = files.default_file_opener(files.build_request_path(FILE_KEY), {})
    assert status in {401, 403, 404}
    decoded = body.decode("utf-8", errors="replace")
    assert TOKEN not in decoded
