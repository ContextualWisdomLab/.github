"""Regression tests for the trusted local Strix Contextual-Orchestrator gateway."""

from __future__ import annotations

import copy
from http.client import HTTPConnection
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import tempfile
import threading
import unittest
import urllib.error


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "ci"
    / "strix_contextual_gateway.py"
)


def load_module():
    """Load the production gateway helper from its repository path."""
    spec = importlib.util.spec_from_file_location("strix_contextual_gateway", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load strix_contextual_gateway")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeOrchestrator:
    """Record gateway calls and return deterministic raw provider responses."""

    def __init__(self, response: dict | None = None, failure: Exception | None = None) -> None:
        self.agents = [SimpleNamespace(provider_name="provider_a")]
        self.response = response or {
            "id": "chatcmpl_test",
            "object": "chat.completion",
            "created": 1_725_000_000,
            "model": "fallback-model",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "read_file",
                                    "arguments": "{\"path\":\"a.py\"}",
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
        }
        self.failure = failure
        self.calls: list[tuple[dict, str]] = []

    def proxy_completion(self, body: dict, *, endpoint: str) -> dict:
        """Record the request and return or raise the configured outcome."""
        self.calls.append((copy.deepcopy(body), endpoint))
        if self.failure is not None:
            raise self.failure
        return copy.deepcopy(self.response)


class GatewayTests(unittest.TestCase):
    """Exercise authentication, streaming conversion, and trusted bootstrap inputs."""

    def setUp(self) -> None:
        self.module = load_module()

    def _start(self, orchestrator: FakeOrchestrator, token: str = "gateway-token"):
        bootstrap = self.module.GatewayBootstrap(2, 2, "live")
        server = self.module.build_gateway(orchestrator, token, bootstrap, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server, token

    def _request(
        self,
        server,
        method: str,
        path: str,
        *,
        token: str | None = None,
        body: object | None = None,
        content_type: str = "application/json",
    ) -> tuple[int, dict[str, str], bytes]:
        connection = HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
        headers = {"content-type": content_type}
        if token is not None:
            headers["authorization"] = f"Bearer {token}"
        raw = None if body is None else json.dumps(body).encode("utf-8")
        connection.request(method, path, body=raw, headers=headers)
        response = connection.getresponse()
        payload = response.read()
        response_headers = {key.lower(): value for key, value in response.getheaders()}
        connection.close()
        return response.status, response_headers, payload

    def test_health_is_secret_free_and_unauthenticated(self) -> None:
        server, _token = self._start(FakeOrchestrator())
        status, headers, payload = self._request(server, "GET", "/healthz")
        self.assertEqual(status, 200)
        self.assertEqual(headers["cache-control"], "no-store")
        self.assertEqual(
            json.loads(payload),
            {
                "status": "ready",
                "agent_count": 2,
                "provider_count": 2,
                "catalog_source": "live",
            },
        )
        self.assertEqual(self._request(server, "GET", "/missing")[0], 404)

    def test_streaming_tool_response_is_reframed_as_sse(self) -> None:
        orchestrator = FakeOrchestrator()
        server, token = self._start(orchestrator)
        request_body = {
            "model": "contextual-orchestrator",
            "messages": [{"role": "user", "content": "inspect"}],
            "tools": [
                {
                    "type": "function",
                    "function": {"name": "read_file", "parameters": {}},
                }
            ],
            "tool_choice": "auto",
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        original = copy.deepcopy(request_body)

        status, headers, payload = self._request(
            server,
            "POST",
            "/v1/chat/completions",
            token=token,
            body=request_body,
        )

        self.assertEqual(status, 200)
        self.assertTrue(headers["content-type"].startswith("text/event-stream"))
        text = payload.decode("utf-8")
        self.assertIn('"tool_calls"', text)
        self.assertIn('"finish_reason":"tool_calls"', text)
        self.assertIn('"usage"', text)
        self.assertTrue(text.endswith("data: [DONE]\n\n"))
        self.assertEqual(request_body, original)
        forwarded, endpoint = orchestrator.calls[0]
        self.assertEqual(endpoint, "chat/completions")
        self.assertNotIn("stream_options", forwarded)
        self.assertTrue(forwarded["stream"])
        self.assertEqual(forwarded["tools"], original["tools"])

    def test_nonstream_response_preserves_raw_provider_shape(self) -> None:
        orchestrator = FakeOrchestrator()
        server, token = self._start(orchestrator)
        status, headers, payload = self._request(
            server,
            "POST",
            "/chat/completions",
            token=token,
            body={
                "messages": [{"role": "user", "content": "inspect"}],
                "tools": [],
                "stream": False,
            },
        )
        self.assertEqual(status, 200)
        self.assertTrue(headers["content-type"].startswith("application/json"))
        self.assertEqual(json.loads(payload)["model"], "fallback-model")

    def test_auth_route_content_type_and_size_fail_closed(self) -> None:
        server, token = self._start(FakeOrchestrator())
        self.assertEqual(
            self._request(server, "POST", "/v1/chat/completions", body={})[0],
            401,
        )
        self.assertEqual(
            self._request(server, "POST", "/v1/unknown", token=token, body={})[0],
            404,
        )
        self.assertEqual(
            self._request(
                server,
                "POST",
                "/v1/chat/completions",
                token=token,
                body={},
                content_type="text/plain",
            )[0],
            400,
        )
        self.assertEqual(
            self._request(
                server,
                "POST",
                "/v1/chat/completions",
                token=token,
                body={"stream": "yes"},
            )[0],
            400,
        )
        self.assertEqual(
            self._request(
                server,
                "POST",
                "/v1/chat/completions",
                token=token,
                body=["not", "an", "object"],
            )[0],
            400,
        )

        tiny_server = self.module.build_gateway(
            FakeOrchestrator(),
            token,
            self.module.GatewayBootstrap(1, 1, "live"),
            port=0,
            max_request_bytes=1,
        )
        thread = threading.Thread(target=tiny_server.serve_forever, daemon=True)
        thread.start()
        try:
            self.assertEqual(
                self._request(
                    tiny_server,
                    "POST",
                    "/v1/chat/completions",
                    token=token,
                    body={"x": 1},
                )[0],
                400,
            )
        finally:
            tiny_server.shutdown()
            tiny_server.server_close()

    def test_provider_failure_and_non_object_response_are_sanitized(self) -> None:
        failures = (
            urllib.error.HTTPError("https://provider", 429, "secret details", None, None),
            None,
        )
        responses = (None, ["not", "an", "object"])
        for index in range(2):
            orchestrator = FakeOrchestrator(
                response=responses[index],
                failure=failures[index],
            )
            if index == 1:
                orchestrator.response = responses[index]
            server, token = self._start(orchestrator)
            status, _headers, payload = self._request(
                server,
                "POST",
                "/v1/chat/completions",
                token=token,
                body={"messages": [], "tools": [], "stream": False},
            )
            self.assertEqual(status, 503)
            self.assertEqual(json.loads(payload)["error"]["type"], "provider_unavailable")
            self.assertNotIn(b"secret details", payload)

    def test_stream_converter_handles_text_refusal_legacy_and_sparse_choices(self) -> None:
        response = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "hello",
                        "refusal": "no",
                        "function_call": {"name": "legacy", "arguments": "{}"},
                        "tool_calls": ["ignored"],
                    },
                    "finish_reason": "stop",
                },
                {"index": 9, "message": "not-an-object"},
                "ignored",
            ]
        }
        chunks = list(self.module.chat_completion_stream_chunks(response))
        self.assertEqual(chunks[0]["choices"][0]["index"], 0)
        self.assertEqual(chunks[1]["choices"][0]["delta"]["content"], "hello")
        self.assertEqual(chunks[1]["choices"][0]["delta"]["refusal"], "no")
        self.assertEqual(
            chunks[1]["choices"][0]["delta"]["function_call"]["name"],
            "legacy",
        )
        self.assertEqual(chunks[2]["choices"][0]["finish_reason"], "stop")
        self.assertEqual(chunks[3]["choices"][0]["index"], 9)
        self.assertEqual(chunks[4]["choices"][0]["finish_reason"], "stop")
        self.assertEqual(list(self.module.chat_completion_stream_chunks({"choices": "bad"})), [])
        encoded = self.module.encode_chat_completion_sse({"choices": []})
        self.assertEqual(encoded, b"data: [DONE]\n\n")

    def test_manifest_registers_fixed_names_and_deletes_transport_files(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            key_path = root / "openai.key"
            key_path.write_text("secret-value\n", encoding="utf-8")
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps({"OPENAI_API_KEY": str(key_path)}),
                encoding="utf-8",
            )
            registered: dict[str, str] = {}
            names = self.module.load_credential_manifest(
                manifest,
                root,
                registered.__setitem__,
            )
            self.assertEqual(names, ("OPENAI_API_KEY",))
            self.assertEqual(registered, {"OPENAI_API_KEY": "secret-value"})
            self.assertFalse(key_path.exists())
            self.assertFalse(manifest.exists())

    def test_manifest_rejects_untrusted_or_invalid_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root, tempfile.TemporaryDirectory() as raw_external:
            root = Path(raw_root)
            external = Path(raw_external) / "secret"
            external.write_text("x", encoding="utf-8")

            cases = [
                '{"OPENAI_API_KEY":"a","OPENAI_API_KEY":"b"}',
                json.dumps({"UNKNOWN_API_KEY": str(external)}),
                json.dumps({"OPENAI_API_KEY": ""}),
                json.dumps({"OPENAI_API_KEY": str(external)}),
                "[]",
                "{invalid",
            ]
            for index, payload in enumerate(cases):
                manifest = root / f"manifest-{index}.json"
                manifest.write_text(payload, encoding="utf-8")
                with self.subTest(index=index), self.assertRaises(
                    self.module.GatewayConfigurationError
                ):
                    self.module.load_credential_manifest(
                        manifest,
                        root,
                        lambda _name, _value: None,
                    )

            empty_key = root / "empty-key"
            empty_key.write_text("  \n", encoding="utf-8")
            manifest = root / "manifest-empty-key.json"
            manifest.write_text(
                json.dumps({"OPENAI_API_KEY": str(empty_key)}),
                encoding="utf-8",
            )
            with self.assertRaises(self.module.GatewayConfigurationError):
                self.module.load_credential_manifest(
                    manifest,
                    root,
                    lambda _name, _value: None,
                )

            target = root / "target"
            target.write_text("secret", encoding="utf-8")
            link = root / "link"
            try:
                link.symlink_to(target)
            except OSError:
                return
            manifest = root / "manifest-link.json"
            manifest.write_text(
                json.dumps({"OPENAI_API_KEY": str(link)}),
                encoding="utf-8",
            )
            with self.assertRaises(self.module.GatewayConfigurationError):
                self.module.load_credential_manifest(
                    manifest,
                    root,
                    lambda _name, _value: None,
                )

    def test_token_gateway_configuration_and_ready_receipt_validation(self) -> None:
        bootstrap = self.module.GatewayBootstrap(1, 1, "floor")
        with self.assertRaises(self.module.GatewayConfigurationError):
            self.module.build_gateway(FakeOrchestrator(), "", bootstrap)
        with self.assertRaises(self.module.GatewayConfigurationError):
            self.module.build_gateway(
                FakeOrchestrator(),
                "x",
                bootstrap,
                host="0.0.0.0",
            )
        with self.assertRaises(self.module.GatewayConfigurationError):
            self.module.build_gateway(
                FakeOrchestrator(),
                "x",
                bootstrap,
                max_request_bytes=0,
            )
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            token_file = root / "token"
            token_file.write_text("token-value\n", encoding="utf-8")
            self.assertEqual(
                self.module._load_token(token_file, root),
                "token-value",
            )
            token_file.write_text("\n", encoding="utf-8")
            with self.assertRaises(self.module.GatewayConfigurationError):
                self.module._load_token(token_file, root)
            ready = root / "ready.json"
            self.module._write_ready_file(ready, {"status": "ready"})
            self.assertEqual(
                json.loads(ready.read_text(encoding="utf-8")),
                {"status": "ready"},
            )
            self.assertEqual(ready.stat().st_mode & 0o777, 0o600)

        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            regular = root / "file"
            regular.write_text("x", encoding="utf-8")
            missing_root = root / "missing-root"
            with self.assertRaises(self.module.GatewayConfigurationError):
                self.module._resolve_trusted_file(regular, missing_root, "file")

    def test_live_orchestrator_rejects_missing_source_contract(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            manifest = root / "manifest.json"
            manifest.write_text("{}", encoding="utf-8")
            with self.assertRaises(self.module.GatewayConfigurationError):
                self.module.build_live_orchestrator(
                    root / "missing",
                    manifest,
                    root,
                )
            package_root = root / "source" / "contextual_orchestrator"
            package_root.mkdir(parents=True)
            package_root.symlink_to(package_root, target_is_directory=True) if False else None
            package_root.rmdir()
            with self.assertRaises(self.module.GatewayConfigurationError):
                self.module.build_live_orchestrator(
                    root / "source",
                    manifest,
                    root,
                )


if __name__ == "__main__":
    unittest.main()
