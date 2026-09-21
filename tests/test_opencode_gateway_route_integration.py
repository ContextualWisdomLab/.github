"""Executed proof that OpenCode requests the gateway's served route.

The string contracts in ``test_review_failure_taxonomy_contract.py`` pin what
the config says. They cannot show what the OpenCode CLI actually sends, which
is where the 2026-08-27..2026-09-21 outage lived: the provider appended only
``/chat/completions`` to a bare origin, the gateway served ``/v1/…`` and
answered ``route_not_found`` whose message is the bare string ``not found``.

These tests run the installed OpenCode CLI against a stub that answers exactly
like the vendored gateway — the served route succeeds, every other route 404s
with the gateway's own wording — and record which path the CLI asked for. The
tracked ``opencode.jsonc`` provider block is the input, so the proof follows
the shipped config instead of a copy of it.

They skip when no ``opencode`` binary is present (CI images for the quality
workflows do not install it); local execution is the evidence.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

_ORG_REPO_ROOT = Path(__file__).resolve().parents[1]
OPENCODE_CONFIG = _ORG_REPO_ROOT / "opencode.jsonc"

GATEWAY_SERVED_ROUTE = "/v1/chat/completions"
GATEWAY_ROUTE_NOT_FOUND_MESSAGE = "not found"
CLI_TIMEOUT_SECONDS = 120
CLI_EXIT_GRACE_SECONDS = 20


def _tracked_provider_block() -> dict:
    """Return the gateway provider block exactly as opencode.jsonc ships it."""
    text = OPENCODE_CONFIG.read_text(encoding="utf-8")
    without_comments = "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("//")
    )
    config = json.loads(without_comments)
    return config["provider"]["contextual-orchestrator"]


class _GatewayStub(BaseHTTPRequestHandler):
    """Answer like the vendored gateway: one served route, 404 elsewhere."""

    requested_paths: list[str] = []

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        """Record the requested path and answer as the gateway would."""
        length = int(self.headers.get("content-length") or 0)
        self.rfile.read(length)
        type(self).requested_paths.append(self.path)
        if self.path == GATEWAY_SERVED_ROUTE:
            payload = {
                "id": "stub",
                "object": "chat.completion",
                "created": 0,
                "model": "orchestrator/free",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                },
            }
            self._send(200, payload)
            return
        self._send(
            404,
            {"error": {"message": GATEWAY_ROUTE_NOT_FOUND_MESSAGE, "code": "route_not_found"}},
        )

    def _send(self, status: int, payload: dict) -> None:
        """Write one JSON response with an explicit content length."""
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        """Silence the default stderr access log."""


@pytest.fixture(name="gateway_stub")
def gateway_stub_fixture():
    """Serve the gateway stub on a loopback port for one test."""
    _GatewayStub.requested_paths = []
    server = HTTPServer(("127.0.0.1", 0), _GatewayStub)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", _GatewayStub.requested_paths
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _run_opencode(
    tmp_path: Path,
    base_url_template: str,
    gateway_origin: str,
    requested_paths: list[str],
) -> tuple[str, str]:
    """Run the OpenCode CLI until it asks the gateway for one route."""
    provider = _tracked_provider_block()
    provider = json.loads(json.dumps(provider))
    provider["options"]["baseURL"] = base_url_template
    config_home = tmp_path / "config"
    (config_home / "opencode").mkdir(parents=True)
    (config_home / "opencode" / "opencode.json").write_text(
        json.dumps(
            {
                "$schema": "https://opencode.ai/config.json",
                "model": "contextual-orchestrator/orchestrator/free",
                "small_model": "contextual-orchestrator/orchestrator/free",
                "enabled_providers": ["contextual-orchestrator"],
                "provider": {"contextual-orchestrator": provider},
            }
        ),
        encoding="utf-8",
    )
    project = tmp_path / "project"
    project.mkdir()
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(tmp_path / "home"),
        "XDG_CONFIG_HOME": str(config_home),
        "NO_COLOR": "1",
        "CONTEXTUAL_ORCHESTRATOR_BASE_URL": gateway_origin,
        "CONTEXTUAL_ORCHESTRATOR_TOKEN": "stub-token",
    }
    (tmp_path / "home").mkdir()
    process = subprocess.Popen(
        [
            "opencode",
            "run",
            "reply with ok",
            "--pure",
            "--model",
            "contextual-orchestrator/orchestrator/free",
        ],
        cwd=project,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    # The served route answers successfully, after which the agent keeps
    # working; the requested path is the evidence, so stop as soon as one
    # arrives. An unserved route makes the CLI exit on its own.
    deadline = time.monotonic() + CLI_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if requested_paths or process.poll() is not None:
            break
        time.sleep(0.2)
    try:
        return process.communicate(timeout=CLI_EXIT_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        return process.communicate()


pytestmark = pytest.mark.skipif(
    shutil.which("opencode") is None,
    reason="OpenCode CLI is not installed on this runner",
)


def test_tracked_config_requests_the_gateway_served_route(gateway_stub, tmp_path) -> None:
    """The shipped baseURL must make the CLI ask for the served /v1 route."""
    origin, requested_paths = gateway_stub
    base_url = _tracked_provider_block()["options"]["baseURL"]
    _run_opencode(tmp_path, base_url, origin, requested_paths)
    assert requested_paths, "the CLI issued no request to the gateway stub"
    assert requested_paths[0] == GATEWAY_SERVED_ROUTE


def test_bare_origin_reproduces_the_route_not_found_outage(gateway_stub, tmp_path) -> None:
    """Dropping /v1 must reproduce the unserved path and the gateway wording."""
    origin, requested_paths = gateway_stub
    bare = "{env:CONTEXTUAL_ORCHESTRATOR_BASE_URL}"
    stdout, stderr = _run_opencode(tmp_path, bare, origin, requested_paths)
    assert requested_paths, "the CLI issued no request to the gateway stub"
    assert requested_paths[0] == "/chat/completions"
    assert requested_paths[0] != GATEWAY_SERVED_ROUTE
    combined = f"{stdout}\n{stderr}".casefold()
    assert GATEWAY_ROUTE_NOT_FOUND_MESSAGE in combined
