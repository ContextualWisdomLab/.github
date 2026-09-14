"""Regression coverage for visible removal of legacy review-policy knobs."""

from __future__ import annotations

from scripts.ci import contextual_orchestrator_review_policy as policy


def test_explicit_legacy_limit_flags_emit_operator_diagnostics(capsys) -> None:
    """Ignored flags must not silently hide stale deployment configuration."""
    warn = getattr(policy, "_warn_explicit_legacy_options")

    warn(["--limit", "99", "--account-cap=7"])

    assert capsys.readouterr().err.splitlines() == [
        "contextual-orchestrator review policy: --limit is deprecated and ignored",
        "contextual-orchestrator review policy: --account-cap is deprecated and ignored",
    ]


def test_default_cli_does_not_emit_legacy_option_diagnostics(capsys) -> None:
    """Only explicit stale configuration should create warning noise."""
    warn = getattr(policy, "_warn_explicit_legacy_options")

    warn(["--pool", "free"])

    assert capsys.readouterr().err == ""
