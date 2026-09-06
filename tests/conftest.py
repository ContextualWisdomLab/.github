"""Shared deterministic support for central CI regression tests."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from scripts.ci import materialize_base_python_requirements as materializer


@pytest.fixture(autouse=True)
def clear_trusted_uv_process_caches() -> Iterator[None]:
    """Isolate the original process-global trusted uv caches across monkeypatches."""
    install_cache_clear = materializer._install_trusted_uv.cache_clear
    opener_cache_clear = materializer._install_trusted_uv_url_opener.cache_clear
    install_cache_clear()
    opener_cache_clear()
    yield
    install_cache_clear()
    opener_cache_clear()


@pytest.fixture(autouse=True)
def isolate_noema_repair_deadline_from_external_dns(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the repair-deadline unit test about wall time, not external DNS latency.

    ``call_llm`` deliberately resolves configured public hosts as part of its
    SSRF guard.  The deadline regression replaces the HTTP opener but used to
    leave that DNS lookup live, so a cold/slow resolver could consume several
    seconds before the synthetic slow-read path even began and make the
    otherwise-correct 50 ms process-timer assertion fail nondeterministically.
    Other Noema SSRF tests retain the real resolver/mocked resolver behavior;
    only this single unit test gets a no-op URL guard because URL admission is
    outside the behavior it is asserting.
    """
    if request.node.name != "test_total_repair_wall_clock_deadline_interrupts_slow_read":
        return
    from scripts.ci import noema_review_gate as gate

    monkeypatch.setattr(gate, "reject_private_llm_url", lambda _url: None)


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
