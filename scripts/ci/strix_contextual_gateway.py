#!/usr/bin/env python3
"""Serve a local Contextual-Orchestrator gateway for trusted Strix scans.

The central Strix workflow starts this process from a commit-pinned checkout of
``ContextualWisdomLab/contextual-orchestrator``. Provider credentials arrive as
0600 files inside the trusted runner temporary directory, are registered in the
orchestrator's process-local KV, and are deleted immediately after bootstrap.

The gateway exposes only the OpenAI-compatible surface Strix needs. Structured
or tool-bearing requests are executed non-streaming upstream so the
Contextual-Orchestrator can move to another capability-ranked provider after a
single failed attempt. When the caller requested streaming, the complete raw
response is converted back into standards-shaped SSE chunks for the OpenAI
Agents client used by Strix.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import sys
import time
from typing import Any
from urllib.parse import urlsplit


_ALLOWED_CREDENTIAL_NAMES = frozenset(
    {
        "NVIDIA_NIM_API_KEY",
        "NVIDIA_NIM_API_KEY_SUB",
        "BYTEZ_API_KEY",
        "OPENROUTER_API_KEY",
        "OPENAI_API_KEY",
    }
)
_MAX_REQUEST_BYTES = 128 * 1024 * 1024


class GatewayConfigurationError(RuntimeError):
    """Raised when trusted bootstrap inputs violate the gateway contract."""


@dataclass(frozen=True)
class GatewayBootstrap:
    """Secret-free bootstrap summary used by workflow health checks."""

    agent_count: int
    provider_count: int
    catalog_source: str

    def as_dict(self) -> dict[str, Any]:
        """Return the health-safe JSON representation."""
        return {
            "status": "ready",
            "agent_count": self.agent_count,
            "provider_count": self.provider_count,
            "catalog_source": self.catalog_source,
        }


def _resolve_trusted_file(path: Path, root: Path, label: str) -> Path:
    """Resolve one regular non-symlink file constrained below ``root``."""
    if path.is_symlink() or not path.is_file():
        raise GatewayConfigurationError(f"{label} must reference a regular non-symlink file")
    if root.is_symlink() or not root.is_dir():
        raise GatewayConfigurationError("trusted input root must be a regular directory")
    try:
        resolved_root = root.resolve(strict=True)
        resolved_path = path.resolve(strict=True)
        resolved_path.relative_to(resolved_root)
    except (OSError, ValueError) as exc:
        raise GatewayConfigurationError(f"{label} must stay inside the trusted input root") from exc
    return resolved_path


def load_credential_manifest(
    manifest_path: Path,
    trusted_input_root: Path,
    register: Callable[[str, str], None],
) -> tuple[str, ...]:
    """Register manifest credentials and delete their transport files.

    The JSON manifest maps one of the five fixed provider credential names to a
    credential file path. Unknown names, duplicate JSON keys, symlinks, empty
    values, and paths outside ``trusted_input_root`` fail closed. Successfully
    read credential files are unlinked before this function returns.
    """

    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise GatewayConfigurationError(f"duplicate manifest key: {key}")
            result[key] = value
        return result

    resolved_manifest = _resolve_trusted_file(
        manifest_path,
        trusted_input_root,
        "credential manifest",
    )
    try:
        payload = json.loads(
            resolved_manifest.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicate_keys,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GatewayConfigurationError("credential manifest must be valid UTF-8 JSON") from exc
    if not isinstance(payload, dict) or not payload:
        raise GatewayConfigurationError("credential manifest must be a non-empty object")

    registered: list[str] = []
    for name, raw_path in payload.items():
        if name not in _ALLOWED_CREDENTIAL_NAMES:
            raise GatewayConfigurationError(f"unsupported credential name: {name}")
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise GatewayConfigurationError(f"credential path for {name} must be a string")
        credential_path = _resolve_trusted_file(
            Path(raw_path),
            trusted_input_root,
            f"credential file for {name}",
        )
        try:
            value = credential_path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError) as exc:
            raise GatewayConfigurationError(f"credential file for {name} is unreadable") from exc
        if not value:
            raise GatewayConfigurationError(f"credential file for {name} must be non-empty")
        register(name, value)
        registered.append(name)
        try:
            credential_path.unlink()
        except OSError as exc:
            raise GatewayConfigurationError(
                f"credential transport file for {name} could not be deleted"
            ) from exc

    try:
        resolved_manifest.unlink()
    except OSError as exc:
        raise GatewayConfigurationError("credential manifest could not be deleted") from exc
    return tuple(registered)


def _base_chunk(response: Mapping[str, Any]) -> dict[str, Any]:
    """Return common fields for an OpenAI chat-completion stream chunk."""
    created = response.get("created")
    if not isinstance(created, int):
        created = int(time.time())
    return {
        "id": str(response.get("id") or f"chatcmpl_gateway_{secrets.token_hex(8)}"),
        "object": "chat.completion.chunk",
        "created": created,
        "model": str(response.get("model") or "contextual-orchestrator"),
    }


def chat_completion_stream_chunks(
    response: Mapping[str, Any],
) -> Iterable[dict[str, Any]]:
    """Convert one complete chat response into OpenAI-compatible SSE chunks."""
    base = _base_chunk(response)
    raw_choices = response.get("choices")
    if not isinstance(raw_choices, list):
        raw_choices = []

    for fallback_index, raw_choice in enumerate(raw_choices):
        if not isinstance(raw_choice, dict):
            continue
        choice_index = raw_choice.get("index")
        if not isinstance(choice_index, int):
            choice_index = fallback_index
        message = raw_choice.get("message")
        if not isinstance(message, dict):
            message = {}

        role_chunk = dict(base)
        role_chunk["choices"] = [
            {
                "index": choice_index,
                "delta": {"role": str(message.get("role") or "assistant")},
                "finish_reason": None,
            }
        ]
        yield role_chunk

        delta: dict[str, Any] = {}
        content = message.get("content")
        if isinstance(content, str) and content:
            delta["content"] = content
        refusal = message.get("refusal")
        if isinstance(refusal, str) and refusal:
            delta["refusal"] = refusal
        tool_calls = message.get("tool_calls")
        if isinstance(tool_calls, list) and tool_calls:
            normalized_calls: list[dict[str, Any]] = []
            for tool_index, raw_tool in enumerate(tool_calls):
                if not isinstance(raw_tool, dict):
                    continue
                tool_call = dict(raw_tool)
                tool_call["index"] = tool_index
                normalized_calls.append(tool_call)
            if normalized_calls:
                delta["tool_calls"] = normalized_calls
        function_call = message.get("function_call")
        if isinstance(function_call, dict):
            delta["function_call"] = function_call
        if delta:
            content_chunk = dict(base)
            content_chunk["choices"] = [
                {
                    "index": choice_index,
                    "delta": delta,
                    "finish_reason": None,
                }
            ]
            yield content_chunk

        finish_chunk = dict(base)
        finish_chunk["choices"] = [
            {
                "index": choice_index,
                "delta": {},
                "finish_reason": raw_choice.get("finish_reason") or "stop",
            }
        ]
        yield finish_chunk

    usage = response.get("usage")
    if isinstance(usage, dict):
        usage_chunk = dict(base)
        usage_chunk["choices"] = []
        usage_chunk["usage"] = usage
        yield usage_chunk


def encode_chat_completion_sse(response: Mapping[str, Any]) -> bytes:
    """Encode a complete chat response as an OpenAI SSE byte stream."""
    frames = [
        f"data: {json.dumps(chunk, ensure_ascii=False, separators=(',', ':'))}\n\n"
        for chunk in chat_completion_stream_chunks(response)
    ]
    frames.append("data: [DONE]\n\n")
    return "".join(frames).encode("utf-8")


def _authorized(headers: Mapping[str, str], token: str) -> bool:
    """Return whether headers carry the exact gateway Bearer token."""
    return headers.get("authorization", "") == f"Bearer {token}"


def build_gateway(
    orchestrator: Any,
    token: str,
    bootstrap: GatewayBootstrap,
    *,
    host: str = "127.0.0.1",
    port: int = 0,
    max_request_bytes: int = _MAX_REQUEST_BYTES,
) -> ThreadingHTTPServer:
    """Build a local authenticated OpenAI-compatible gateway server."""
    if not token:
        raise GatewayConfigurationError("gateway token must be non-empty")
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise GatewayConfigurationError("gateway may bind only to a loopback address")
    if max_request_bytes < 1:
        raise GatewayConfigurationError("maximum request size must be positive")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            path = urlsplit(self.path).path
            if path == "/healthz":
                self._send_json(bootstrap.as_dict())
                return
            self._send_json(
                {"error": {"type": "route_not_found", "message": "not found"}},
                status=404,
            )

        def do_POST(self) -> None:  # noqa: N802
            path = urlsplit(self.path).path
            if not _authorized({key.lower(): value for key, value in self.headers.items()}, token):
                self._send_json(
                    {"error": {"type": "unauthorized", "message": "authentication required"}},
                    status=401,
                )
                return
            if path not in {"/v1/chat/completions", "/chat/completions"}:
                self._send_json(
                    {"error": {"type": "route_not_found", "message": "not found"}},
                    status=404,
                )
                return
            try:
                body = self._read_json()
                stream = body.get("stream", False)
                if not isinstance(stream, bool):
                    raise ValueError("stream must be a boolean")
                upstream_body = dict(body)
                # The upstream attempt is deliberately non-streaming; the
                # gateway reconstructs the caller-requested stream after failover.
                upstream_body.pop("stream_options", None)
                response = orchestrator.proxy_completion(
                    upstream_body,
                    endpoint="chat/completions",
                )
                if not isinstance(response, dict):
                    raise RuntimeError("orchestrator returned a non-object response")
                if stream:
                    self._send_sse(encode_chat_completion_sse(response))
                else:
                    self._send_json(response)
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
                self._send_json(
                    {"error": {"type": "invalid_request", "message": str(exc)}},
                    status=400,
                )
            except Exception as exc:  # noqa: BLE001 - sanitize provider failure at boundary
                print(
                    f"Contextual-Orchestrator gateway request failed: {type(exc).__name__}",
                    file=sys.stderr,
                    flush=True,
                )
                self._send_json(
                    {
                        "error": {
                            "type": "provider_unavailable",
                            "message": "all eligible model providers were unavailable",
                        }
                    },
                    status=503,
                )

        def _read_json(self) -> dict[str, Any]:
            content_type = self.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if content_type != "application/json":
                raise ValueError("content-type must be application/json")
            raw_length = self.headers.get("content-length", "")
            try:
                content_length = int(raw_length)
            except ValueError as exc:
                raise ValueError("content-length must be an integer") from exc
            if content_length < 0 or content_length > max_request_bytes:
                raise ValueError("request body exceeds the configured limit")
            raw = self.rfile.read(content_length)
            decoded = raw.decode("utf-8")
            parsed = json.loads(decoded) if decoded else {}
            if not isinstance(parsed, dict):
                raise ValueError("request body must be a JSON object")
            return parsed

        def _send_json(self, payload: Mapping[str, Any], status: int = 200) -> None:
            raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("content-type", "application/json; charset=utf-8")
            self.send_header("content-length", str(len(raw)))
            self.send_header("cache-control", "no-store")
            self.end_headers()
            self.wfile.write(raw)

        def _send_sse(self, raw: bytes) -> None:
            self.send_response(200)
            self.send_header("content-type", "text/event-stream; charset=utf-8")
            self.send_header("cache-control", "no-cache, no-store")
            self.send_header("connection", "close")
            self.send_header("content-length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, format: str, *args: object) -> None:
            return

    return ThreadingHTTPServer((host, port), Handler)


def _load_token(token_file: Path, trusted_input_root: Path) -> str:
    """Read the gateway token from a trusted regular file."""
    resolved = _resolve_trusted_file(token_file, trusted_input_root, "gateway token file")
    try:
        token = resolved.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError) as exc:
        raise GatewayConfigurationError("gateway token file is unreadable") from exc
    if not token:
        raise GatewayConfigurationError("gateway token file must be non-empty")
    return token


def build_live_orchestrator(
    source_root: Path,
    credential_manifest: Path,
    trusted_input_root: Path,
) -> tuple[Any, GatewayBootstrap]:
    """Load a pinned Contextual-Orchestrator source tree and discover its pool."""
    if source_root.is_symlink() or not source_root.is_dir():
        raise GatewayConfigurationError("Contextual-Orchestrator source root must be a directory")
    resolved_source = source_root.resolve(strict=True)
    package_root = resolved_source / "contextual_orchestrator"
    if not package_root.is_dir() or package_root.is_symlink():
        raise GatewayConfigurationError("Contextual-Orchestrator package is missing")
    sys.path.insert(0, str(resolved_source))

    from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: PLC0415
    from contextual_orchestrator.credentials import (  # noqa: PLC0415
        InMemoryCredentialBackend,
        register_credential,
        set_backend,
    )
    from contextual_orchestrator.model_discovery import apply_discovered_pool  # noqa: PLC0415
    from contextual_orchestrator.orchestrator import ModelClient  # noqa: PLC0415

    set_backend(InMemoryCredentialBackend())
    registered = load_credential_manifest(
        credential_manifest,
        trusted_input_root,
        register_credential,
    )
    if not registered:
        raise GatewayConfigurationError("at least one provider credential is required")

    client = ModelClient(timeout=900, max_retries=0)
    orchestrator = TaskOrchestrator(
        [
            ModelAgent(
                "bootstrap_agent",
                "bootstrap-model",
                base_url="mock://bootstrap",
                tags=("coding", "implementation", "reasoning", "verification"),
            )
        ],
        client=client,
    )
    snapshot = apply_discovered_pool(orchestrator)
    agents = list(getattr(orchestrator, "agents", ()))
    if not agents or all(str(getattr(agent, "base_url", "")).startswith("mock://") for agent in agents):
        raise GatewayConfigurationError("model discovery produced no callable provider candidates")
    providers = {
        str(getattr(agent, "provider_name", "") or getattr(agent, "base_url", ""))
        for agent in agents
    }
    bootstrap = GatewayBootstrap(
        agent_count=len(agents),
        provider_count=len(providers),
        catalog_source=str(getattr(snapshot, "source", "unknown")),
    )
    return orchestrator, bootstrap


def _write_ready_file(path: Path, payload: Mapping[str, Any]) -> None:
    """Atomically publish a secret-free readiness receipt."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(6)}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    temporary.chmod(0o600)
    temporary.replace(path)


def main(argv: Sequence[str] | None = None) -> int:
    """Bootstrap and serve the trusted local gateway until the job exits."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--credential-manifest", type=Path, required=True)
    parser.add_argument("--trusted-input-root", type=Path, required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--ready-file", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)

    try:
        token = _load_token(args.token_file, args.trusted_input_root)
        orchestrator, bootstrap = build_live_orchestrator(
            args.source_root,
            args.credential_manifest,
            args.trusted_input_root,
        )
        server = build_gateway(
            orchestrator,
            token,
            bootstrap,
            host=args.host,
            port=args.port,
        )
        ready_payload = bootstrap.as_dict()
        ready_payload["host"] = args.host
        ready_payload["port"] = int(server.server_address[1])
        _write_ready_file(args.ready_file, ready_payload)
        print(
            "Contextual-Orchestrator Strix gateway ready "
            f"with {bootstrap.agent_count} candidates across {bootstrap.provider_count} providers.",
            flush=True,
        )
        server.serve_forever()
    except GatewayConfigurationError as exc:
        print(f"Gateway bootstrap failed: {exc}", file=sys.stderr)
        return 2
    finally:
        try:
            sys.path.remove(str(args.source_root.resolve(strict=False)))
        except (ValueError, OSError, UnboundLocalError):
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
