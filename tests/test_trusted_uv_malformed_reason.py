"""Regression contract for malformed trusted-uv transport reasons."""

from __future__ import annotations

import urllib.error

import pytest

from scripts.ci import materialize_base_python_requirements as materializer


def test_trusted_uv_download_rejects_string_url_error_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-exception URLError reason fails once without leaking its text."""
    calls: list[tuple[str, int]] = []
    sleeps: list[float] = []

    def malformed_urlopen(url: str, *, timeout: int) -> object:
        """Raise one malformed transport failure after recording the request."""
        calls.append((url, timeout))
        raise urllib.error.URLError("malformed")

    monkeypatch.setattr(materializer.urllib.request, "urlopen", malformed_urlopen)
    monkeypatch.setattr(materializer.time, "sleep", sleeps.append)

    with pytest.raises(RuntimeError, match=r"URLError$") as exc_info:
        materializer._download_trusted_uv_archive()

    assert "malformed" not in str(exc_info.value)
    assert calls == [
        (
            materializer.TRUSTED_UV_ARCHIVE_URL,
            materializer.TRUSTED_UV_DOWNLOAD_TIMEOUT_SECONDS,
        )
    ]
    assert sleeps == []
