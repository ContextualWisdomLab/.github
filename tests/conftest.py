"""Shared deterministic support for central CI regression tests."""

from __future__ import annotations

from collections.abc import Iterator
import os
import pathlib

import pytest

from scripts.ci import materialize_base_python_requirements as materializer


_MATERIALIZER_OPEN_INSTRUMENTATION_TESTS = {
    "test_javascript_materializer_descriptor_ancestry.py",
    "test_javascript_materializer_output_security.py",
}


class _DynamicDirectoryFdSupport:
    """Preserve ``dir_fd`` truth for an instrumented forwarding ``os.open``."""

    def __init__(self, baseline: object) -> None:
        """Retain the platform capability set used before test instrumentation."""
        self._baseline = baseline

    def __contains__(self, function: object) -> bool:
        """Treat the current forwarding ``os.open`` like the supported original."""
        return function is os.open or function in self._baseline  # type: ignore[operator]


@pytest.fixture(autouse=True)
def preserve_instrumented_open_directory_fd_support(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """Keep race-injection wrappers from invalidating the platform preflight."""
    test_filename = pathlib.Path(str(request.node.path)).name
    if test_filename not in _MATERIALIZER_OPEN_INSTRUMENTATION_TESTS:
        yield
        return

    baseline = os.supports_dir_fd
    monkeypatch.setattr(
        os,
        "supports_dir_fd",
        _DynamicDirectoryFdSupport(baseline),
    )
    yield


@pytest.fixture(autouse=True)
def clear_trusted_uv_process_caches() -> Iterator[None]:
    """Isolate process-global trusted uv caches even when a test fails early."""
    materializer._install_trusted_uv.cache_clear()
    materializer._install_trusted_uv_url_opener.cache_clear()
    yield
    materializer._install_trusted_uv.cache_clear()
    materializer._install_trusted_uv_url_opener.cache_clear()


class FakeHttpResponse:
    """Expose bounded context-managed reads from one deterministic final URL."""

    def __init__(
        self,
        final_url: str,
        payload: bytes = b"archive",
        *,
        maximum_chunk_size: int | None = None,
    ) -> None:
        """Store response bytes, final URL, and an optional short-read bound."""
        if maximum_chunk_size is not None and maximum_chunk_size < 1:
            raise ValueError("maximum_chunk_size must be positive when provided")
        self._final_url = final_url
        self._payload = payload
        self._maximum_chunk_size = maximum_chunk_size
        self._offset = 0

    def __enter__(self) -> "FakeHttpResponse":
        """Return this response from the context manager."""
        return self

    def __exit__(self, *_args: object) -> None:
        """Leave the synthetic response context without suppressing errors."""

    def geturl(self) -> str:
        """Return the final URL observed by the downloader."""
        return self._final_url

    def read(self, size: int) -> bytes:
        """Return the next bounded response chunk and advance the stream cursor."""
        if size < 0:
            size = len(self._payload) - self._offset
        if self._maximum_chunk_size is not None:
            size = min(size, self._maximum_chunk_size)
        start = self._offset
        end = min(len(self._payload), start + size)
        self._offset = end
        return self._payload[start:end]
