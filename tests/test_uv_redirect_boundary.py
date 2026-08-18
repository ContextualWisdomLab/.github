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


def test_trusted_uv_redirect_handler_allows_one_github_asset_hop() -> None:
    """GitHub Releases may take one hop onto the official release-asset CDN."""
    handler = materializer._TrustedUvReleaseAssetRedirects()
    original = urllib.request.Request(materializer.TRUSTED_UV_ARCHIVE_URL)
    allowed = (
        "https://release-assets.githubusercontent.com/"
        "github-production-release-asset/699532645/archive"
    )

    followed = handler.redirect_request(
        original,
        None,
        302,
        "Found",
        {},
        allowed,
    )

    assert followed is not None
    assert followed.full_url == allowed


def test_trusted_uv_redirect_handler_rejects_before_following() -> None:
    """Non-allowlisted hops are rejected before urllib creates a target request."""
    handler = materializer._TrustedUvReleaseAssetRedirects()
    original = urllib.request.Request(materializer.TRUSTED_UV_ARCHIVE_URL)

    with pytest.raises(RuntimeError, match="redirected outside"):
        handler.redirect_request(
            original,
            None,
            302,
            "Found",
            {},
            "https://127.0.0.1/internal",
        )


def test_trusted_uv_redirect_handler_rejects_asset_host_follow_on() -> None:
    """A second hop from the asset CDN cannot retarget the download."""
    handler = materializer._TrustedUvReleaseAssetRedirects()
    current = urllib.request.Request(
        "https://release-assets.githubusercontent.com/"
        "github-production-release-asset/699532645/archive"
    )

    with pytest.raises(RuntimeError, match="redirected outside"):
        handler.redirect_request(
            current,
            None,
            302,
            "Found",
            {},
            "https://objects.githubusercontent.com/other",
        )


def test_trusted_uv_redirect_handler_allows_legacy_objects_asset_hop() -> None:
    """The previous GitHub release-asset hostname remains a valid first hop."""
    handler = materializer._TrustedUvReleaseAssetRedirects()
    original = urllib.request.Request(materializer.TRUSTED_UV_ARCHIVE_URL)
    allowed = "https://objects.githubusercontent.com/github-production-release-asset/1/file"

    followed = handler.redirect_request(
        original,
        None,
        302,
        "Found",
        {},
        allowed,
    )

    assert followed is not None
    assert followed.full_url == allowed


def test_trusted_uv_redirect_handler_fails_closed_when_parent_drops_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A parent handler that drops the follow-on request cannot open a new origin."""
    handler = materializer._TrustedUvReleaseAssetRedirects()
    original = urllib.request.Request(materializer.TRUSTED_UV_ARCHIVE_URL)
    allowed = (
        "https://release-assets.githubusercontent.com/"
        "github-production-release-asset/699532645/archive"
    )

    monkeypatch.setattr(
        urllib.request.HTTPRedirectHandler,
        "redirect_request",
        lambda *_args, **_kwargs: None,
    )

    with pytest.raises(RuntimeError, match="redirected outside"):
        handler.redirect_request(
            original,
            None,
            302,
            "Found",
            {},
            allowed,
        )


@pytest.mark.parametrize(
    "new_url",
    [
        "https://user@release-assets.githubusercontent.com/archive",
        "https://:secret@release-assets.githubusercontent.com/archive",
        "https://release-assets.githubusercontent.com:444/archive",
        "https://release-assets.githubusercontent.com:not-a-port/archive",
        "http://release-assets.githubusercontent.com/archive",
    ],
)
def test_trusted_uv_redirect_handler_rejects_unsafe_asset_locations(
    new_url: str,
) -> None:
    """Userinfo, non-HTTPS, and nondefault ports cannot become the asset origin."""
    handler = materializer._TrustedUvReleaseAssetRedirects()
    original = urllib.request.Request(materializer.TRUSTED_UV_ARCHIVE_URL)

    with pytest.raises(RuntimeError, match="redirected outside"):
        handler.redirect_request(
            original,
            None,
            302,
            "Found",
            {},
            new_url,
        )


def test_trusted_uv_opener_is_cached_and_disables_ambient_proxies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The dedicated process installs one no-proxy GitHub-origin opener."""
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
    assert isinstance(handlers[1], materializer._TrustedUvReleaseAssetRedirects)
