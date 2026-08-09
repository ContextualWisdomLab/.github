"""Behavioral contracts for the trusted uv download redirect boundary."""

from __future__ import annotations

import urllib.request
from collections.abc import Iterator

import pytest

from scripts.ci import materialize_base_python_requirements as materializer


@pytest.fixture(autouse=True)
def clear_trusted_uv_opener_cache() -> Iterator[None]:
    """Clear process-global opener state before and after every boundary test."""
    materializer._install_trusted_uv_url_opener.cache_clear()
    yield
    materializer._install_trusted_uv_url_opener.cache_clear()


def test_trusted_uv_redirect_handler_rejects_before_following() -> None:
    """Every HTTP redirect is rejected before urllib creates a target request."""
    handler = materializer._RejectTrustedUvRedirects()
    original = urllib.request.Request(materializer.TRUSTED_UV_ARCHIVE_URL)

    with pytest.raises(RuntimeError, match="redirects are forbidden"):
        handler.redirect_request(
            original,
            None,
            302,
            "Found",
            {},
            "https://127.0.0.1/internal",
        )


def test_trusted_uv_opener_is_cached_and_disables_ambient_proxies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The dedicated process installs one no-proxy, no-redirect opener."""
    captured: dict[str, object] = {"builds": 0, "installs": 0}
    sentinel = object()

    def fake_build_opener(*handlers: object) -> object:
        captured["builds"] = int(captured["builds"]) + 1
        captured["handlers"] = handlers
        return sentinel

    def fake_install_opener(opener: object) -> None:
        captured["installs"] = int(captured["installs"]) + 1
        captured["opener"] = opener

    monkeypatch.setattr(materializer.urllib.request, "build_opener", fake_build_opener)
    monkeypatch.setattr(materializer.urllib.request, "install_opener", fake_install_opener)

    materializer._install_trusted_uv_url_opener()
    materializer._install_trusted_uv_url_opener()

    assert captured["builds"] == 1
    assert captured["installs"] == 1
    assert captured["opener"] is sentinel
    handlers = captured["handlers"]
    assert isinstance(handlers, tuple)
    assert len(handlers) == 2
    assert isinstance(handlers[0], urllib.request.ProxyHandler)
    assert handlers[0].proxies == {}
    assert isinstance(handlers[1], materializer._RejectTrustedUvRedirects)


def test_trusted_uv_origin_accepts_explicit_default_https_port() -> None:
    """The fixed trusted HTTPS origin remains valid when port 443 is explicit."""
    materializer._verify_trusted_uv_origin(
        "https://releases.astral.sh:443/uv-x86_64-unknown-linux-gnu.tar.gz"
    )


def test_trusted_uv_origin_rejects_non_default_port() -> None:
    """A non-443 port cannot stay inside the governed trusted uv origin."""
    with pytest.raises(RuntimeError, match="redirected outside.*releases\.astral\.sh"):
        materializer._verify_trusted_uv_origin(
            "https://releases.astral.sh:444/uv-x86_64-unknown-linux-gnu.tar.gz"
        )


def test_trusted_uv_origin_rejects_malformed_port() -> None:
    """A malformed URL port is normalized to the same fail-closed origin error."""
    with pytest.raises(RuntimeError, match="redirected outside.*releases\.astral\.sh"):
        materializer._verify_trusted_uv_origin(
            "https://releases.astral.sh:not-a-port/uv-x86_64-unknown-linux-gnu.tar.gz"
        )
