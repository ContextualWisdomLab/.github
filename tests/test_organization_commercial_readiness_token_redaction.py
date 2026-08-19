"""Credential-redaction regressions for the organization coordinator.

GitHub CLI diagnostics are repository-external text. A credential that crosses
the retained-suffix boundary, or appears in an endpoint string, must never be
partially or fully reflected in a workflow error.
"""

from __future__ import annotations

from typing import Any

import pytest

from scripts.ci.organization_commercial_readiness_loop import GitHubClient, GitHubError


def test_cli_error_redacts_token_before_bounding_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A token crossing the final-900-character boundary leaves no suffix leak."""

    token = "ghp_0123456789abcdefghijklmnopqrstuvwxyzAB"
    raw_error = ("A" * 1000) + token + ("B" * 880)

    class Completed:
        returncode = 1
        stdout = ""
        stderr = raw_error

    def fake_run(*_args: Any, **_kwargs: Any) -> Completed:
        return Completed()

    monkeypatch.setattr("subprocess.run", fake_run)

    with pytest.raises(GitHubError) as raised:
        GitHubClient(token).request("/repos/ContextualWisdomLab/example")

    message = str(raised.value)
    assert token not in message
    assert token[-20:] not in message
    assert len(message) < 1200


def test_endpoint_diagnostic_redacts_exact_token_without_masking_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only the credential is removed when it appears in a diagnostic endpoint."""

    token = "ghp_abcdefghijklmnopqrstuvwxyz0123456789AB"

    class Completed:
        returncode = 1
        stdout = ""
        stderr = "request rejected"

    monkeypatch.setattr("subprocess.run", lambda *_args, **_kwargs: Completed())

    with pytest.raises(GitHubError) as raised:
        GitHubClient(token).request(f"/repos/example/{token}/runs")

    message = str(raised.value)
    assert token not in message
    assert "repos/example" in message
    assert "[REDACTED]" in message
