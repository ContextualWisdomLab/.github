"""Regression contracts for Strix repository-visibility authority."""

from __future__ import annotations

import subprocess

import pytest

from scripts.ci import strix_resolve_target_visibility as visibility


def test_cli_visibility_query_maps_internal_as_private(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The GitHub CLI query must map internal/private to the private contract."""

    def internal_response(
        argv: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        """Return the boolean that the production jq mapping emits for internal."""
        query = argv[argv.index("--jq") + 1]
        assert ".visibility" in query
        assert '== "internal"' in query
        assert '== "private"' in query
        assert '== "public"' in query
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout="HTTP/2 200 OK\r\nContent-Type: application/json\r\n\r\ntrue\n",
            stderr="",
        )

    monkeypatch.setattr(visibility.subprocess, "run", internal_response)
    assert visibility.run_gh_visibility("ContextualWisdomLab/aFIPC") == "true\n"


def test_split_gh_response_keeps_only_the_terminal_body() -> None:
    """Proxy/redirect header blocks must never be mistaken for visibility body."""
    output = (
        "HTTP/1.1 200 Connection established\r\nProxy-Agent: example\r\n\r\n"
        "HTTP/2 200 OK\r\nContent-Type: application/json\r\n\r\nfalse\n"
    )

    headers, body = visibility.split_gh_response(output)

    assert headers == (
        "HTTP/1.1 200 Connection established\r\nProxy-Agent: example\r\n\r\n"
        "HTTP/2 200 OK\r\nContent-Type: application/json\r\n\r\n"
    )
    assert body == "false\n"
