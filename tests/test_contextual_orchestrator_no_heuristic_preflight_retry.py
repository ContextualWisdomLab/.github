"""Regression contracts for fail-closed review preflight transport allocation."""

from __future__ import annotations

import inspect

from scripts.ci import contextual_orchestrator_review_launcher as launcher


def test_preflight_has_no_repository_authored_transport_retry_budget() -> None:
    """A transient status cannot manufacture an extra model call in central CI."""
    source = inspect.getsource(launcher)
    assert "REVIEW_PREFLIGHT_TRANSIENT_RETRIES" not in source
    assert "transport_retry_budget" not in source
    assert "max_retries=1" not in source


def test_preflight_uses_single_attempt_transport_and_preserves_typed_failure() -> None:
    """Without an identified retry policy, preflight fails closed after one send."""
    source = inspect.getsource(launcher._send_preflight_request)
    assert "proxy_send_once" in source
    assert "proxy_send(" not in source
