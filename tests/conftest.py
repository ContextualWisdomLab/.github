"""Shared deterministic support for central CI regression tests."""

from __future__ import annotations

from collections.abc import Iterator
import json

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


@pytest.fixture(autouse=True)
def adapt_opencode_draft_step_fixtures(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Serve one live draft PR lookup to legacy step-body regressions.

    The production draft exemption now validates live PR/head state before it
    succeeds. Existing step-body tests still use a deliberately refusing
    ``gh`` stub for every call after that trusted lookup. Keep those tests
    focused on the same API-poll/dispatch boundary while dedicated live-state
    regressions exercise stale ready-state and moved-head behavior directly.
    """
    module = request.module
    if not module.__name__.endswith("test_opencode_required_verdict_regression"):
        return

    def write_live_draft_then_refuse(bin_dir) -> None:
        fake_gh = bin_dir / "gh"
        fake_gh.write_text(
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            "if [[ \"$*\" == \"api repos/ContextualWisdomLab/example/pulls/1437\" ]]; then\n"
            "  printf '%s' \"$LIVE_PR_JSON\"\n"
            "  exit 0\n"
            "fi\n"
            "echo 'unexpected gh invocation: the early-exit should have short-circuited' >&2\n"
            "exit 17\n",
            encoding="utf-8",
        )
        fake_gh.chmod(fake_gh.stat().st_mode | 0o111)

    monkeypatch.setenv(
        "LIVE_PR_JSON",
        json.dumps({"draft": True, "head": {"sha": getattr(module, "HEAD")}}),
    )
    monkeypatch.setattr(module, "_write_refusing_gh", write_live_draft_then_refuse)

    for name in ("_run_fail_closed_step", "_run_request_review_step"):
        original = getattr(module, name)

        def normalized(*args, __original=original, **kwargs):
            result = __original(*args, **kwargs)
            result.stdout = result.stdout.replace(
                "PR is still a draft on the live exact head;", "PR is a draft;"
            )
            return result

        monkeypatch.setattr(module, name, normalized)


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
