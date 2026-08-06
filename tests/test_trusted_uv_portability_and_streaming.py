"""Regression contracts for portable and bounded trusted uv bootstrapping."""

from __future__ import annotations

import errno
import io
import platform
import socket
import ssl
import urllib.error
from pathlib import Path

import pytest

from scripts.ci import materialize_base_python_requirements as materializer


class _ChunkedResponse:
    """Return deterministic short reads from one trusted final URL."""

    def __init__(self, chunks: list[bytes | BaseException]) -> None:
        """Store response outcomes in the order an HTTP stream exposes them."""
        self._chunks = iter(chunks)

    def __enter__(self) -> "_ChunkedResponse":
        """Return this response from its context manager."""
        return self

    def __exit__(self, *_args: object) -> None:
        """Leave the response context without suppressing exceptions."""

    @staticmethod
    def geturl() -> str:
        """Return the immutable trusted Astral release origin."""
        return materializer.TRUSTED_UV_ARCHIVE_URL

    def read(self, _size: int) -> bytes:
        """Return one short chunk, raise a scripted failure, or return EOF."""
        outcome = next(self._chunks, b"")
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _http_error(status: int) -> urllib.error.HTTPError:
    """Return one file-like HTTP failure for the fixed trusted archive URL."""

    return urllib.error.HTTPError(
        materializer.TRUSTED_UV_ARCHIVE_URL,
        status,
        "synthetic failure",
        None,
        io.BytesIO(b""),
    )


def _scripted_urlopen(
    outcomes: list[object],
    calls: list[tuple[str, int]],
):
    """Return a fake urlopen that records the immutable request contract."""

    remaining = iter(outcomes)

    def fake_urlopen(url: str, *, timeout: int) -> object:
        calls.append((url, timeout))
        outcome = next(remaining)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    return fake_urlopen


def test_trusted_uv_download_collects_short_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A valid archive is accumulated until EOF instead of accepting a prefix."""
    response = _ChunkedResponse([b"ab", b"cd", b""])
    monkeypatch.setattr(
        materializer.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: response,
    )

    assert materializer._download_trusted_uv_archive() == b"abcd"


def test_trusted_uv_download_rejects_oversize_across_short_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Many individually small chunks cannot bypass the total download bound."""
    response = _ChunkedResponse([b"12", b"34", b"5", b""])
    monkeypatch.setattr(
        materializer.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: response,
    )
    monkeypatch.setattr(materializer, "TRUSTED_UV_DOWNLOAD_MAX_BYTES", 4)

    with pytest.raises(RuntimeError, match="bounded download size"):
        materializer._download_trusted_uv_archive()


@pytest.mark.parametrize("status", [408, 425, 429, 500, 502, 503, 504])
def test_trusted_uv_download_retries_only_closed_http_status_set(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
) -> None:
    """Every explicitly transient HTTP status receives one bounded retry."""

    calls: list[tuple[str, int]] = []
    sleeps: list[float] = []
    monkeypatch.setattr(
        materializer.urllib.request,
        "urlopen",
        _scripted_urlopen(
            [_http_error(status), _ChunkedResponse([b"archive", b""])],
            calls,
        ),
    )
    monkeypatch.setattr(materializer.time, "sleep", sleeps.append)

    assert materializer._download_trusted_uv_archive() == b"archive"
    assert calls == [
        (
            materializer.TRUSTED_UV_ARCHIVE_URL,
            materializer.TRUSTED_UV_DOWNLOAD_TIMEOUT_SECONDS,
        ),
        (
            materializer.TRUSTED_UV_ARCHIVE_URL,
            materializer.TRUSTED_UV_DOWNLOAD_TIMEOUT_SECONDS,
        ),
    ]
    assert sleeps == [1.0]


@pytest.mark.parametrize("status", [400, 401, 403, 404, 405, 410, 422])
def test_trusted_uv_download_does_not_retry_permanent_http_failure(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
) -> None:
    """Permanent source and authorization responses fail immediately."""

    calls: list[tuple[str, int]] = []
    sleeps: list[float] = []
    monkeypatch.setattr(
        materializer.urllib.request,
        "urlopen",
        _scripted_urlopen([_http_error(status)], calls),
    )
    monkeypatch.setattr(materializer.time, "sleep", sleeps.append)

    with pytest.raises(RuntimeError, match=rf"HTTP {status}$"):
        materializer._download_trusted_uv_archive()

    assert len(calls) == 1
    assert sleeps == []


def test_trusted_uv_download_retries_temporary_dns_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only the DNS resolver's temporary failure signal is retried."""

    calls: list[tuple[str, int]] = []
    sleeps: list[float] = []
    failure = urllib.error.URLError(
        socket.gaierror(socket.EAI_AGAIN, "temporary DNS failure")
    )
    monkeypatch.setattr(
        materializer.urllib.request,
        "urlopen",
        _scripted_urlopen(
            [failure, _ChunkedResponse([b"archive", b""])], calls
        ),
    )
    monkeypatch.setattr(materializer.time, "sleep", sleeps.append)

    assert materializer._download_trusted_uv_archive() == b"archive"
    assert len(calls) == 2
    assert sleeps == [1.0]


def test_trusted_uv_download_retries_timeout_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real timeout receives one bounded retry with the exact request."""

    calls: list[tuple[str, int]] = []
    sleeps: list[float] = []
    monkeypatch.setattr(
        materializer.urllib.request,
        "urlopen",
        _scripted_urlopen(
            [TimeoutError(errno.ETIMEDOUT, "timed out"), _ChunkedResponse([b"ok", b""])],
            calls,
        ),
    )
    monkeypatch.setattr(materializer.time, "sleep", sleeps.append)

    assert materializer._download_trusted_uv_archive() == b"ok"
    assert calls == [
        (
            materializer.TRUSTED_UV_ARCHIVE_URL,
            materializer.TRUSTED_UV_DOWNLOAD_TIMEOUT_SECONDS,
        ),
        (
            materializer.TRUSTED_UV_ARCHIVE_URL,
            materializer.TRUSTED_UV_DOWNLOAD_TIMEOUT_SECONDS,
        ),
    ]
    assert sleeps == [1.0]


def test_trusted_uv_download_retries_connection_reset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A connection reset receives one bounded retry with the same request."""

    calls: list[tuple[str, int]] = []
    sleeps: list[float] = []
    monkeypatch.setattr(
        materializer.urllib.request,
        "urlopen",
        _scripted_urlopen(
            [ConnectionResetError(errno.ECONNRESET, "reset"), _ChunkedResponse([b"ok", b""])],
            calls,
        ),
    )
    monkeypatch.setattr(materializer.time, "sleep", sleeps.append)

    assert materializer._download_trusted_uv_archive() == b"ok"
    assert len(calls) == 2
    assert sleeps == [1.0]


def test_trusted_uv_download_does_not_retry_tls_certificate_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Certificate verification is an integrity failure, never availability noise."""

    calls: list[tuple[str, int]] = []
    sleeps: list[float] = []
    failure = urllib.error.URLError(
        ssl.SSLCertVerificationError(1, "certificate verify failed")
    )
    monkeypatch.setattr(
        materializer.urllib.request,
        "urlopen",
        _scripted_urlopen([failure], calls),
    )
    monkeypatch.setattr(materializer.time, "sleep", sleeps.append)

    with pytest.raises(RuntimeError, match=r"SSLCertVerificationError$"):
        materializer._download_trusted_uv_archive()

    assert len(calls) == 1
    assert sleeps == []


def test_trusted_uv_download_does_not_retry_non_temporary_dns_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unknown host is a permanent source failure rather than transient DNS."""

    calls: list[tuple[str, int]] = []
    sleeps: list[float] = []
    failure = urllib.error.URLError(
        socket.gaierror(socket.EAI_NONAME, "name not known")
    )
    monkeypatch.setattr(
        materializer.urllib.request,
        "urlopen",
        _scripted_urlopen([failure], calls),
    )
    monkeypatch.setattr(materializer.time, "sleep", sleeps.append)

    with pytest.raises(RuntimeError, match=r"gaierror$"):
        materializer._download_trusted_uv_archive()

    assert len(calls) == 1
    assert sleeps == []


def test_trusted_uv_download_does_not_retry_unclassified_os_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Local or malformed OS failures cannot be promoted to network availability."""

    calls: list[tuple[str, int]] = []
    sleeps: list[float] = []
    monkeypatch.setattr(
        materializer.urllib.request,
        "urlopen",
        _scripted_urlopen([OSError(errno.EINVAL, "invalid local state")], calls),
    )
    monkeypatch.setattr(materializer.time, "sleep", sleeps.append)

    with pytest.raises(RuntimeError, match=r"OSError$"):
        materializer._download_trusted_uv_archive()

    assert len(calls) == 1
    assert sleeps == []


def test_trusted_uv_download_does_not_retry_malformed_url_error_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-exception URL reason fails once without exposing untrusted text."""

    calls: list[tuple[str, int]] = []
    sleeps: list[float] = []
    failure = urllib.error.URLError("malformed")
    monkeypatch.setattr(
        materializer.urllib.request,
        "urlopen",
        _scripted_urlopen([failure], calls),
    )
    monkeypatch.setattr(materializer.time, "sleep", sleeps.append)

    with pytest.raises(RuntimeError) as exc_info:
        materializer._download_trusted_uv_archive()

    assert str(exc_info.value) == "trusted uv archive download failed: URLError"
    assert calls == [
        (
            materializer.TRUSTED_UV_ARCHIVE_URL,
            materializer.TRUSTED_UV_DOWNLOAD_TIMEOUT_SECONDS,
        )
    ]
    assert sleeps == []


def test_trusted_uv_download_exhausts_bounded_transient_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Persistent transient failures stop after three total network attempts."""

    calls: list[tuple[str, int]] = []
    sleeps: list[float] = []
    monkeypatch.setattr(
        materializer.urllib.request,
        "urlopen",
        _scripted_urlopen([_http_error(503), _http_error(503), _http_error(503)], calls),
    )
    monkeypatch.setattr(materializer.time, "sleep", sleeps.append)

    with pytest.raises(RuntimeError, match=r"HTTP 503 after 3 attempts"):
        materializer._download_trusted_uv_archive()

    assert len(calls) == 3
    assert sleeps == [1.0, 2.0]


def test_trusted_uv_download_discards_partial_bytes_before_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bytes read from a failed attempt never contaminate the next response."""

    calls: list[tuple[str, int]] = []
    sleeps: list[float] = []
    first = _ChunkedResponse(
        [b"partial-", ConnectionResetError(errno.ECONNRESET, "reset")]
    )
    second = _ChunkedResponse([b"fresh", b""])
    monkeypatch.setattr(
        materializer.urllib.request,
        "urlopen",
        _scripted_urlopen([first, second], calls),
    )
    monkeypatch.setattr(materializer.time, "sleep", sleeps.append)

    assert materializer._download_trusted_uv_archive() == b"fresh"
    assert len(calls) == 2
    assert sleeps == [1.0]


@pytest.mark.parametrize(
    ("runner_platform", "runner_machine"),
    [("darwin", "x86_64"), ("linux", "aarch64")],
)
def test_trusted_uv_install_rejects_unsupported_runner_before_download(
    monkeypatch: pytest.MonkeyPatch,
    runner_platform: str,
    runner_machine: str,
) -> None:
    """The Linux x86_64 archive is never downloaded on an unsupported runner."""
    materializer._install_trusted_uv.cache_clear()
    monkeypatch.setattr(materializer.sys, "platform", runner_platform)
    monkeypatch.setattr(platform, "machine", lambda: runner_machine)

    def unexpected_download() -> bytes:
        raise AssertionError("unsupported runners must fail before network access")

    monkeypatch.setattr(materializer, "_download_trusted_uv_archive", unexpected_download)

    with pytest.raises(RuntimeError, match="supports only linux x86_64"):
        materializer._install_trusted_uv()


def test_python_310_toml_parser_fallback_is_declared() -> None:
    """Python 3.10 receives the production fallback and conditional dependency."""
    repository_root = Path(__file__).resolve().parents[1]
    materializer_source = (
        repository_root / "scripts" / "ci" / "materialize_base_python_requirements.py"
    ).read_text(encoding="utf-8")
    project_source = (repository_root / "pyproject.toml").read_text(encoding="utf-8")

    assert "import tomli as tomllib" in materializer_source
    assert "python_version < '3.11'" in project_source or 'python_version < "3.11"' in project_source
