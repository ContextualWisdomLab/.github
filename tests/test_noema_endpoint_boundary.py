"""Credential-egress contracts for Noema's configurable model endpoint."""

from __future__ import annotations

import json
import socket
from collections.abc import Callable
from typing import Any

import pytest

from scripts.ci import noema_review_gate as noema


APPROVAL_RESPONSE = {
    "choices": [
        {
            "message": {
                "content": json.dumps(
                    {"decision": "approve", "summary": "ok", "findings": []}
                )
            }
        }
    ]
}


class FakeResponse:
    """Return bounded response bytes through urllib's context-manager contract."""

    def __init__(self, payload: dict[str, Any]) -> None:
        """Serialize one deterministic response payload."""
        self.raw = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> FakeResponse:
        """Return this response for the request context."""
        return self

    def __exit__(self, *_args: object) -> bool:
        """Propagate exceptions raised while consuming the response."""
        return False

    def read(self, size: int = -1) -> bytes:
        """Return at most the caller's requested number of bytes."""
        return self.raw if size < 0 else self.raw[:size]


class FakeOpener:
    """Capture credentialed requests and return a deterministic response."""

    def __init__(
        self,
        payload: dict[str, Any],
        capture: Callable[[noema.urllib.request.Request], None] | None = None,
    ) -> None:
        """Store response data and an optional request observer."""
        self.payload = payload
        self.capture = capture

    def open(
        self,
        request: noema.urllib.request.Request,
        timeout: int | None = None,
    ) -> FakeResponse:
        """Record the request and return the configured response."""
        assert timeout == 120
        if self.capture is not None:
            self.capture(request)
        return FakeResponse(self.payload)


def _pr() -> dict[str, Any]:
    """Return the minimum current-head pull-request envelope for a model call."""
    return {"title": "review me", "headRefOid": "a" * 40}


def _configure(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    """Configure one synthetic Noema model endpoint without a real credential."""
    monkeypatch.setenv("NOEMA_LLM_API_URL", url)
    monkeypatch.setenv("NOEMA_LLM_API_KEY", "unit-test-key")
    monkeypatch.setenv("NOEMA_LLM_MODEL", "review-model")


def _addrinfo(address: str, port: int) -> list[tuple[Any, ...]]:
    """Return one getaddrinfo-compatible stream address record."""
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    sockaddr: tuple[Any, ...] = (
        (address, port, 0, 0) if family == socket.AF_INET6 else (address, port)
    )
    return [(family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", sockaddr)]


def test_pinned_http_connection_uses_only_validated_numeric_destination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prevent a second hostname resolution from selecting an unvalidated peer."""
    fake_socket = object()
    observed: list[tuple[tuple[object, ...], float | object, object]] = []

    def fake_create_connection(
        target: tuple[object, ...],
        timeout: float | object,
        source_address: object,
    ) -> object:
        observed.append((target, timeout, source_address))
        return fake_socket

    monkeypatch.setattr(noema.socket, "create_connection", fake_create_connection)
    connection = noema.PinnedHTTPConnection(
        "model.example.test",
        port=443,
        timeout=17,
        validated_addresses=frozenset({noema.ipaddress.ip_address("8.8.8.8")}),
    )

    connection.connect()

    assert connection.sock is fake_socket
    assert observed == [(('8.8.8.8', 443), 17, None)]


def test_pinned_connection_supports_ipv6_destination_shape() -> None:
    """Preserve the four-field socket address shape required by IPv6 connect."""
    assert noema._socket_target(noema.ipaddress.ip_address("::1"), 443) == (
        "::1",
        443,
        0,
        0,
    )


def test_pinned_connection_retries_only_other_validated_addresses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retry a failed connection only within the already validated address set."""
    attempts: list[tuple[object, ...]] = []
    fake_socket = object()

    def fake_create_connection(
        target: tuple[object, ...],
        _timeout: float | object,
        _source_address: object,
    ) -> object:
        attempts.append(target)
        if len(attempts) == 1:
            raise OSError("first validated address unavailable")
        return fake_socket

    monkeypatch.setattr(noema.socket, "create_connection", fake_create_connection)
    connection = noema.PinnedHTTPConnection(
        "model.example.test",
        port=443,
        validated_addresses=frozenset(
            {
                noema.ipaddress.ip_address("8.8.8.8"),
                noema.ipaddress.ip_address("1.1.1.1"),
            }
        ),
    )

    connection.connect()

    assert connection.sock is fake_socket
    assert attempts == [("1.1.1.1", 443), ("8.8.8.8", 443)]


def test_pinned_https_connection_keeps_hostname_for_tls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pin TCP to the validated IP while retaining the URL hostname for TLS SNI."""
    fake_socket = object()
    wrapped_socket = object()

    class Context:
        """Provide the small SSL context surface used by HTTPSConnection."""

        check_hostname = True

        def wrap_socket(self, value: object, *, server_hostname: str) -> object:
            """Record the original hostname and return the wrapped socket."""
            assert value is fake_socket
            assert server_hostname == "model.example.test"
            return wrapped_socket

    monkeypatch.setattr(
        noema.socket,
        "create_connection",
        lambda *_args: fake_socket,
    )
    connection = noema.PinnedHTTPSConnection(
        "model.example.test",
        port=443,
        context=Context(),
        validated_addresses=frozenset({noema.ipaddress.ip_address("8.8.8.8")}),
    )

    connection.connect()

    assert connection.sock is wrapped_socket


@pytest.mark.parametrize(
    ("handler_type", "connection_type"),
    [
        (noema.PinnedHTTPHandler, noema.PinnedHTTPConnection),
        (noema.PinnedHTTPSHandler, noema.PinnedHTTPSConnection),
    ],
)
def test_pinned_handlers_construct_pinned_connections(
    monkeypatch: pytest.MonkeyPatch,
    handler_type: type[Any],
    connection_type: type[Any],
) -> None:
    """Keep urllib's HTTP and HTTPS paths on the validated connection classes."""
    addresses = frozenset({noema.ipaddress.ip_address("8.8.8.8")})
    handler = handler_type(addresses)
    observed: dict[str, Any] = {}

    def fake_do_open(factory: Any, request: object, **kwargs: Any) -> str:
        observed["request"] = request
        observed["connection"] = factory("model.example.test", timeout=3, **kwargs)
        return "opened"

    monkeypatch.setattr(handler, "do_open", fake_do_open)
    request = object()
    opened = handler.http_open(request) if isinstance(handler, noema.PinnedHTTPHandler) else handler.https_open(request)

    assert opened == "opened"
    assert observed["request"] is request
    assert isinstance(observed["connection"], connection_type)
    assert observed["connection"]._validated_addresses == tuple(addresses)


def test_public_endpoint_requires_https_and_stable_global_dns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject plaintext transport and pre/post-request DNS identity drift."""
    _configure(monkeypatch, "http://model.example.test/v1/chat/completions")
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: _addrinfo("8.8.8.8", 80),
    )
    with pytest.raises(ValueError, match="non-loopback endpoints must use HTTPS"):
        noema.call_llm("owner/repo", 1, _pr(), "diff", False)

    _configure(monkeypatch, "https://model.example.test/v1/chat/completions")
    resolutions = iter(
        [_addrinfo("8.8.8.8", 443), _addrinfo("1.1.1.1", 443)]
    )
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_args, **_kwargs: next(resolutions))
    sent: list[noema.urllib.request.Request] = []
    monkeypatch.setattr(
        noema.urllib.request,
        "build_opener",
        lambda *_args: FakeOpener(APPROVAL_RESPONSE, sent.append),
    )

    with pytest.raises(ValueError, match="DNS addresses changed during the request"):
        noema.call_llm("owner/repo", 1, _pr(), "diff", False)
    assert len(sent) == 1


def test_public_endpoint_accepts_stable_global_dual_stack_dns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Accept an HTTPS endpoint only when every A and AAAA result stays global."""
    _configure(monkeypatch, "https://model.example.test/v1/chat/completions")
    records = [*_addrinfo("8.8.8.8", 443), *_addrinfo("2606:4700:4700::1111", 443)]
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_args, **_kwargs: records)
    monkeypatch.setattr(
        noema.urllib.request,
        "build_opener",
        lambda *_args: FakeOpener(APPROVAL_RESPONSE),
    )

    verdict = noema.call_llm("owner/repo", 1, _pr(), "diff", False)
    assert verdict["decision"] == "approve"


@pytest.mark.parametrize(
    ("url", "address"),
    [
        ("http://127.0.0.1:43123/v1/chat/completions", "127.0.0.1"),
        ("http://[::1]:43123/v1/chat/completions", "::1"),
    ],
)
def test_trusted_loopback_sidecar_keeps_the_narrow_http_exception(
    monkeypatch: pytest.MonkeyPatch,
    url: str,
    address: str,
) -> None:
    """Allow the existing same-job orchestrator address without opening remote HTTP."""
    _configure(monkeypatch, url)
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: _addrinfo(address, 43123),
    )
    observed: list[noema.urllib.request.Request] = []
    monkeypatch.setattr(
        noema.urllib.request,
        "build_opener",
        lambda *_args: FakeOpener(APPROVAL_RESPONSE, observed.append),
    )

    verdict = noema.call_llm("owner/repo", 1, _pr(), "diff", False)
    assert verdict["decision"] == "approve"
    assert observed[0].full_url == url


def test_loopback_exception_requires_literal_and_loopback_only_dns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject a loopback literal if resolver evidence escapes loopback."""
    _configure(monkeypatch, "http://127.0.0.1:43123/v1/chat/completions")
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: _addrinfo("8.8.8.8", 43123),
    )

    with pytest.raises(ValueError, match="left loopback"):
        noema.call_llm("owner/repo", 1, _pr(), "diff", False)


def test_loopback_exception_rejects_other_loopback_literals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep plaintext access narrower than the whole IPv4 loopback block."""
    _configure(monkeypatch, "http://127.0.0.2:43123/v1/chat/completions")

    with pytest.raises(ValueError, match="non-loopback endpoints must use HTTPS"):
        noema.call_llm("owner/repo", 1, _pr(), "diff", False)


def test_endpoint_rejects_url_user_information(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject embedded URL credentials before resolving or sending the API key."""
    _configure(monkeypatch, "https://user:pass@model.example.test/v1/chat/completions")

    with pytest.raises(ValueError, match="cannot contain user information"):
        noema.call_llm("owner/repo", 1, _pr(), "diff", False)


@pytest.mark.parametrize(
    "address",
    [
        "0.0.0.0",
        "10.0.0.5",
        "100.64.0.1",
        "127.0.0.1",
        "169.254.169.254",
        "192.0.2.1",
        "224.0.0.1",
        "::",
        "::1",
        "fe80::1",
        "ff02::1",
    ],
)
def test_non_loopback_hostname_rejects_every_special_address(
    monkeypatch: pytest.MonkeyPatch,
    address: str,
) -> None:
    """Reject private, shared, loopback, link-local, reserved, and multicast DNS."""
    _configure(monkeypatch, "https://model.example.test/v1/chat/completions")
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: _addrinfo(address, 443),
    )

    class UnexpectedOpener:
        """Fail if invalid DNS evidence reaches a credentialed request."""

        def open(self, *_args: object, **_kwargs: object) -> None:
            """Reject any attempted network call."""
            pytest.fail("credentialed request crossed special-address validation")

    monkeypatch.setattr(
        noema.urllib.request,
        "build_opener",
        lambda *_args: UnexpectedOpener(),
    )
    with pytest.raises(ValueError, match="globally routable unicast"):
        noema.call_llm("owner/repo", 1, _pr(), "diff", False)


@pytest.mark.parametrize("failure", ["dns_error", "empty", "malformed"])
def test_dns_failure_is_closed_before_request_construction(
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    """Reject resolver errors, empty answers, and malformed socket addresses."""
    _configure(monkeypatch, "https://model.example.test/v1/chat/completions")

    def fail_resolution(*_args: object, **_kwargs: object) -> list[tuple[Any, ...]]:
        """Return the selected invalid resolver outcome."""
        if failure == "dns_error":
            raise socket.gaierror("unavailable")
        if failure == "empty":
            return []
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ())]

    monkeypatch.setattr(socket, "getaddrinfo", fail_resolution)
    with pytest.raises(ValueError, match="DNS resolution"):
        noema.call_llm("owner/repo", 1, _pr(), "diff", False)


def test_response_body_is_bounded_before_json_decoding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject more than one MiB of response data without allocating the full body."""
    _configure(monkeypatch, "https://model.example.test/v1/chat/completions")
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: _addrinfo("8.8.8.8", 443),
    )
    oversized = {
        "choices": [
            {"message": {"content": "x" * noema.MAX_LLM_RESPONSE_BYTES}}
        ]
    }
    monkeypatch.setattr(
        noema.urllib.request,
        "build_opener",
        lambda *_args: FakeOpener(oversized),
    )

    with pytest.raises(RuntimeError, match="response exceeded the byte limit"):
        noema.call_llm("owner/repo", 1, _pr(), "diff", False)
