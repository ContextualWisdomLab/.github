"""Fail-closed regression for malformed ``URLError.reason`` values."""

from __future__ import annotations

import urllib.error

import pytest

from scripts.ci import materialize_base_python_requirements as materializer


def test_trusted_uv_download_rejects_string_urlerror_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-exception URL reason fails once without echoing untrusted text."""

    calls: list[tuple[str, int]] = []
    sleeps: list[float] = []

    def fail_with_malformed_reason(url: str, *, timeout: int) -> object:
        """Record the immutable request before raising a malformed URL error."""
        calls.append((url, timeout))
        raise urllib.error.URLError("malformed")

    monkeypatch.setattr(
        materializer.urllib.request,
        "urlopen",
        fail_with_malformed_reason,
    )
    monkeypatch.setattr(materializer.time, "sleep", sleeps.append)

    with pytest.raises(RuntimeError, match=r"URLError$") as captured:
        materializer._download_trusted_uv_archive()

    assert "malformed" not in str(captured.value)
    assert calls == [
        (
            materializer.TRUSTED_UV_ARCHIVE_URL,
            materializer.TRUSTED_UV_DOWNLOAD_TIMEOUT_SECONDS,
        )
    ]
    assert sleeps == []
