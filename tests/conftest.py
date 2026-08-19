"""Expose the bounded catalogue helper for direct pytest node collection."""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from scripts.ci import materialize_base_python_requirements as materializer


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


_HELPER_NAME = "catalogue_test_helpers"
_HELPER_PATH = Path(__file__).with_name(f"{_HELPER_NAME}.py")

if _HELPER_NAME not in sys.modules:
    _SPEC = importlib.util.spec_from_file_location(_HELPER_NAME, _HELPER_PATH)
    if _SPEC is None or _SPEC.loader is None:
        raise RuntimeError("catalogue test helper could not be loaded")
    _MODULE = importlib.util.module_from_spec(_SPEC)
    sys.modules[_HELPER_NAME] = _MODULE
    _SPEC.loader.exec_module(_MODULE)
