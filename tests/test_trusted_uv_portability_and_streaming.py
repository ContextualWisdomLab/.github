"""Regression contracts for portable and bounded trusted uv bootstrapping."""

from __future__ import annotations

import platform
from pathlib import Path

import pytest

from scripts.ci import materialize_base_python_requirements as materializer


class _ChunkedResponse:
    """Return deterministic short reads from one trusted final URL."""

    def __init__(self, chunks: list[bytes]) -> None:
        """Store response chunks in the order an HTTP stream would expose them."""
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
        """Return one short chunk, followed by EOF when chunks are exhausted."""
        return next(self._chunks, b"")


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


@pytest.mark.parametrize(
    ("runner_platform", "runner_machine"),
    [
        ("darwin", "x86_64"),
        ("darwin", "amd64"),
        ("linux", "aarch64"),
        ("linux", "arm64"),
    ],
)
def test_trusted_uv_install_rejects_unsupported_runner_before_download(
    monkeypatch: pytest.MonkeyPatch,
    runner_platform: str,
    runner_machine: str,
) -> None:
    """The Linux x86_64 archive is never downloaded on an unsupported runner."""
    materializer._install_trusted_uv.cache_clear()
    monkeypatch.setattr(materializer.sys, "platform", runner_platform)
    monkeypatch.setattr(materializer.platform, "machine", lambda: runner_machine)

    def unexpected_download() -> bytes:
        raise AssertionError("unsupported runners must fail before network access")

    monkeypatch.setattr(materializer, "_download_trusted_uv_archive", unexpected_download)

    with pytest.raises(RuntimeError, match="supports only linux x86_64"):
        materializer._install_trusted_uv()


@pytest.mark.parametrize("runner_machine", ["x86_64", "amd64", "AMD64", " x86_64"])
def test_trusted_uv_install_accepts_linux_amd64_aliases_as_pinned_isa(
    monkeypatch: pytest.MonkeyPatch,
    runner_machine: str,
) -> None:
    """Debian-style amd64 and padded x86_64 labels share the pinned archive ISA."""
    materializer._install_trusted_uv.cache_clear()
    monkeypatch.setattr(materializer.sys, "platform", "linux")
    monkeypatch.setattr(materializer.platform, "machine", lambda: runner_machine)

    def marker_download() -> bytes:
        raise RuntimeError("reached trusted uv download after ISA gate")

    monkeypatch.setattr(materializer, "_download_trusted_uv_archive", marker_download)

    assert materializer._trusted_uv_runner_supported() is True
    with pytest.raises(RuntimeError, match="reached trusted uv download after ISA gate"):
        materializer._install_trusted_uv()


def test_trusted_uv_runner_supported_rejects_non_linux_before_machine_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Darwin host that reports amd64 is still outside the pinned archive ISA."""
    monkeypatch.setattr(materializer.sys, "platform", "darwin")
    monkeypatch.setattr(materializer.platform, "machine", lambda: "amd64")
    assert materializer._trusted_uv_runner_supported() is False
    assert materializer.TRUSTED_UV_LINUX_MACHINES == frozenset({"x86_64", "amd64"})


def test_python_310_toml_parser_fallback_is_declared() -> None:
    """Python 3.10 receives the production fallback and conditional dependency."""
    repository_root = Path(__file__).resolve().parents[1]
    materializer_source = (
        repository_root / "scripts" / "ci" / "materialize_base_python_requirements.py"
    ).read_text(encoding="utf-8")
    project_source = (repository_root / "pyproject.toml").read_text(encoding="utf-8")

    assert "import tomli as tomllib" in materializer_source
    assert "python_version < '3.11'" in project_source or 'python_version < "3.11"' in project_source
