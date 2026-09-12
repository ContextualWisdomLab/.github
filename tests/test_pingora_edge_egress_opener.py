"""Regression tests for the EgressWeave-backed GitHub REST API opener."""

from __future__ import annotations

import importlib.util
import inspect
import sys
from pathlib import Path

import httpx
import pytest

REPO_ROOT = Path(__file__).parents[1]
MODULE_PATH = REPO_ROOT / "scripts" / "ci" / "pingora_edge_egress_opener.py"
VENDOR_MARKER = REPO_ROOT / "vendor" / "egressweave" / "src" / "egressweave" / "__init__.py"

# vendor/egressweave is a git submodule (pinned per docs/adr/0021-...): a plain
# checkout without `git submodule update --init` (or `actions/checkout` with
# `submodules: true`) leaves it as an empty directory. This module's whole
# purpose is exercising that vendored dependency, so — exactly like this
# repository's own `scripts/ci/contextual_orchestrator_review_launcher.py`
# precedent (see pyproject.toml's `[tool.coverage.run] omit` comment) — this
# test module skips outright rather than failing collection for every other
# test in the repository when the submodule is not initialized. The dedicated
# `pingora-edge-egress-opener-quality-ci.yml` workflow always checks out
# submodules, so these tests still run and gate coverage for real there.
if not VENDOR_MARKER.is_file():
    pytest.skip(
        "vendor/egressweave submodule is not initialized; skipping the "
        "EgressWeave-backed opener tests (see pingora-edge-egress-opener-"
        "quality-ci.yml for the workflow that always initializes it)",
        allow_module_level=True,
    )

SPEC = importlib.util.spec_from_file_location("pingora_edge_egress_opener", MODULE_PATH)
assert SPEC and SPEC.loader
opener = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = opener
SPEC.loader.exec_module(opener)

# The module under test inserts vendor/egressweave/src onto sys.path as a side
# effect of import, so this import must run after exec_module above.
from egressweave import EgressNotAllowedError, validation as egressweave_validation  # noqa: E402


class _FakeResponse:
    """A minimal double for ``httpx.Response`` used by ``github_open_json`` tests."""

    def __init__(self, *, status_code=200, json_value=None, json_error=None):
        """Store the canned status, JSON payload, and/or JSON decode failure."""
        self.status_code = status_code
        self._json_value = json_value
        self._json_error = json_error

    def raise_for_status(self) -> None:
        """Raise ``httpx.HTTPStatusError`` the way ``httpx.Response`` would."""
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=None, response=self)

    def json(self):
        """Return the canned JSON value or raise the canned decode failure."""
        if self._json_error is not None:
            raise self._json_error
        return self._json_value


class _FakeClient:
    """A minimal double for ``httpx.Client`` recording the calls it receives."""

    def __init__(self, *, response=None, raise_exc=None):
        """Store the canned response or exception this fake client returns/raises."""
        self._response = response
        self._raise_exc = raise_exc
        self.calls: list[tuple[str, dict[str, str]]] = []

    def get(self, url, *, headers):
        """Record the call and return the canned response or raise."""
        self.calls.append((url, headers))
        if self._raise_exc is not None:
            raise self._raise_exc
        return self._response


def _fake_getaddrinfo(host, port, type=None):
    """Resolve any hostname to one fixed, globally-routable address."""
    return [(2, 1, 6, "", ("93.184.216.34", port))]


def _install_fake_client(monkeypatch, fake: _FakeClient) -> None:
    """Route the public opener through one test-owned transport double."""
    monkeypatch.setattr(opener, "_default_client", lambda: fake)


def test_public_opener_does_not_expose_a_client_injection_seam():
    """Production callers cannot replace the EgressWeave-pinned transport."""
    assert "client" not in inspect.signature(opener.github_open_json).parameters


def test_github_open_json_requires_a_token():
    """An empty token fails closed before any client is touched."""
    with pytest.raises(opener.EgressAdapterError, match="token is required"):
        opener.github_open_json("https://api.github.com/repos/o/r", "")


def test_github_open_json_rejects_non_github_scheme(monkeypatch):
    """A plaintext http:// URL is refused before any client is built."""
    monkeypatch.setattr(
        opener,
        "_default_client",
        lambda: pytest.fail("client must not be built for a rejected URL"),
    )
    with pytest.raises(opener.EgressAdapterError, match="non-GitHub-API URL"):
        opener.github_open_json("http://api.github.com/repos/o/r", "tok")


def test_github_open_json_rejects_non_github_host(monkeypatch):
    """A URL targeting a different host is refused before any client is built."""
    monkeypatch.setattr(
        opener,
        "_default_client",
        lambda: pytest.fail("client must not be built for a rejected URL"),
    )
    with pytest.raises(opener.EgressAdapterError, match="non-GitHub-API URL"):
        opener.github_open_json("https://evil.example/repos/o/r", "tok")


def test_github_open_json_maps_malformed_url_syntax(monkeypatch):
    """Malformed authority syntax is normalized to the adapter's typed failure."""
    monkeypatch.setattr(
        opener,
        "_default_client",
        lambda: pytest.fail("client must not be built for a malformed URL"),
    )
    with pytest.raises(opener.EgressAdapterError, match="malformed GitHub API URL"):
        opener.github_open_json("https://[not-an-ip/repos/o/r", "tok")


def test_github_open_json_returns_parsed_json_on_success(monkeypatch):
    """A 200 response with a valid JSON body is returned as-is."""
    fake = _FakeClient(response=_FakeResponse(status_code=200, json_value={"ok": True}))
    _install_fake_client(monkeypatch, fake)
    result = opener.github_open_json("https://api.github.com/repos/o/r/pulls/1", "tok")
    assert result == {"ok": True}
    [(url, headers)] = fake.calls
    assert url == "https://api.github.com/repos/o/r/pulls/1"
    assert headers["Authorization"] == "Bearer tok"
    assert headers["Accept"] == "application/vnd.github+json"
    assert headers["X-GitHub-Api-Version"] == "2022-11-28"


def test_github_open_json_maps_client_construction_egress_denial(monkeypatch):
    """A policy denial while constructing the pinned client is typed and closed."""
    def _deny_client():
        raise EgressNotAllowedError("denied")

    monkeypatch.setattr(opener, "_default_client", _deny_client)
    with pytest.raises(opener.EgressAdapterError, match="construct pinned GitHub API client"):
        opener.github_open_json("https://api.github.com/repos/o/r", "tok")


def test_github_open_json_maps_client_construction_http_error(monkeypatch):
    """An HTTPX setup failure while constructing the client is typed and closed."""
    def _fail_client():
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(opener, "_default_client", _fail_client)
    with pytest.raises(opener.EgressAdapterError, match="construct pinned GitHub API client"):
        opener.github_open_json("https://api.github.com/repos/o/r", "tok")


def test_github_open_json_maps_egress_denial(monkeypatch):
    """A policy denial from EgressWeave is mapped to EgressAdapterError."""
    fake = _FakeClient(raise_exc=EgressNotAllowedError("denied"))
    _install_fake_client(monkeypatch, fake)
    with pytest.raises(opener.EgressAdapterError, match="denied the GitHub API request"):
        opener.github_open_json("https://api.github.com/repos/o/r", "tok")


def test_github_open_json_maps_http_status_error(monkeypatch):
    """A non-2xx GitHub response is mapped to EgressAdapterError with its status."""
    fake = _FakeClient(response=_FakeResponse(status_code=404))
    _install_fake_client(monkeypatch, fake)
    with pytest.raises(opener.EgressAdapterError, match="status 404"):
        opener.github_open_json("https://api.github.com/repos/o/r", "tok")


def test_github_open_json_maps_generic_http_error(monkeypatch):
    """A transport-level httpx error is mapped to EgressAdapterError."""
    fake = _FakeClient(raise_exc=httpx.ConnectError("boom"))
    _install_fake_client(monkeypatch, fake)
    with pytest.raises(opener.EgressAdapterError, match="ConnectError"):
        opener.github_open_json("https://api.github.com/repos/o/r", "tok")


def test_github_open_json_maps_unexpected_transport_exception(monkeypatch):
    """The adapter boundary does not leak an untyped client exception."""
    fake = _FakeClient(raise_exc=RuntimeError("unexpected client fault"))
    _install_fake_client(monkeypatch, fake)
    with pytest.raises(opener.EgressAdapterError, match="RuntimeError"):
        opener.github_open_json("https://api.github.com/repos/o/r", "tok")


def test_github_open_json_maps_malformed_json(monkeypatch):
    """A successful response whose body is not valid JSON fails closed."""
    fake = _FakeClient(
        response=_FakeResponse(status_code=200, json_error=ValueError("bad json"))
    )
    _install_fake_client(monkeypatch, fake)
    with pytest.raises(opener.EgressAdapterError, match="malformed JSON"):
        opener.github_open_json("https://api.github.com/repos/o/r", "tok")


def test_build_client_pins_the_github_api_authority(monkeypatch):
    """The real client construction path pins api.github.com:443."""
    monkeypatch.setattr(egressweave_validation.socket, "getaddrinfo", _fake_getaddrinfo)
    client = opener._build_client()
    try:
        assert isinstance(client, httpx.Client)
    finally:
        client.close()


def test_default_client_builds_once_and_caches(monkeypatch):
    """The module-wide client is built lazily and reused on later calls."""
    monkeypatch.setattr(egressweave_validation.socket, "getaddrinfo", _fake_getaddrinfo)
    monkeypatch.setattr(opener, "_client", None)
    first = opener._default_client()
    second = opener._default_client()
    assert first is second
    first.close()


def test_default_client_reuses_an_already_built_client(monkeypatch):
    """An already-cached client short-circuits _build_client entirely."""
    sentinel = object()
    monkeypatch.setattr(opener, "_client", sentinel)

    def _fail_build():
        """Fail the test if the cached-client short circuit does not hold."""
        pytest.fail("_build_client should not run when a client is already cached")

    monkeypatch.setattr(opener, "_build_client", _fail_build)
    assert opener._default_client() is sentinel


def test_github_open_json_uses_the_default_client(monkeypatch):
    """The public opener always routes through the pinned default-client boundary."""
    fake = _FakeClient(response=_FakeResponse(status_code=200, json_value={"ok": 1}))
    _install_fake_client(monkeypatch, fake)
    result = opener.github_open_json("https://api.github.com/repos/o/r", "tok")
    assert result == {"ok": 1}
    assert fake.calls
