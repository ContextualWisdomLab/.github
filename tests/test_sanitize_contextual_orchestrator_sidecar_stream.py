"""Regression tests for contextual-orchestrator sidecar stream sanitization."""

from scripts.ci import sanitize_contextual_orchestrator_sidecar_stream as sanitizer


def test_sanitize_line_fast_path_bypasses() -> None:
    """Keep substring guards behaviorally equivalent to the full regex contracts."""
    assert sanitizer.sanitize_line("request_failed but invalid") is None
    assert sanitizer.sanitize_line("provider_discovery_failed but invalid") is None
    assert sanitizer.sanitize_line("preflight_route_ but invalid") is None

    assert sanitizer.sanitize_line("request_failed status=500 code=error") is not None
    assert (
        sanitizer.sanitize_line("provider_discovery_failed provider=test code=error")
        is not None
    )
    assert (
        sanitizer.sanitize_line(
            "preflight_route_rejected provider=test error_type=error"
        )
        is not None
    )
