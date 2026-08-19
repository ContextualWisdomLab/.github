"""Regression tests for credential redaction and bounded scanning."""

from __future__ import annotations

import pytest

from scripts.ci import redact_sensitive_log


def test_redacts_assignments_and_preserves_non_sensitive_context() -> None:
    """Sensitive assignments are masked without dropping surrounding text."""

    assert redact_sensitive_log.redact_text("prefix secret=value suffix") == (
        "prefix secret=[REDACTED] suffix"
    )
    assert redact_sensitive_log.redact_text("123secret=value") == "123secret=[REDACTED]"
    assert redact_sensitive_log.redact_text("broken'--.token:value") == (
        "broken'--.token:[REDACTED]"
    )


def test_skips_a_malformed_sensitive_key_after_one_parse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A malformed key token cannot make the scanner retry every character."""

    calls = 0
    original = redact_sensitive_log._consume_sensitive_assignment

    def counting_consumer(text: str, start: int):
        nonlocal calls
        calls += 1
        return original(text, start)

    monkeypatch.setattr(redact_sensitive_log, "_consume_sensitive_assignment", counting_consumer)

    malformed = "secret" * 200
    assert redact_sensitive_log.redact_text(malformed) == malformed
    assert calls == 1
