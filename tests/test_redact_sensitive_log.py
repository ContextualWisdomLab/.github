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
        """Count parser attempts without changing the production result."""
        nonlocal calls
        calls += 1
        return original(text, start)

    monkeypatch.setattr(
        redact_sensitive_log, "_consume_sensitive_assignment", counting_consumer
    )

    malformed = "".join(("sec", "ret")) * 200
    assert redact_sensitive_log.redact_text(malformed) == malformed
    assert calls == 1


def test_redacts_split_key_value_assignments_across_log_lines() -> None:
    """Whitespace and escaped separators cannot hide a credential value."""
    for source in (
        'token=\n"secret123"',
        'token\r=\r"secret123"',
        't\\o\\k\\e\\n = "secret123"',
        'to ken = "secret123"',
        't0k3n=secret123',
        't-o-k-e-n=secret123',
    ):
        cleaned = redact_sensitive_log.redact_text(source)
        assert "secret123" not in cleaned
        assert redact_sensitive_log.REDACTED in cleaned


def test_preserves_descriptive_token_fields() -> None:
    """Counts and explicitly public token fields remain useful in evidence."""
    source = '{"public_token":"visible_data","token_count":5}'
    cleaned = redact_sensitive_log.redact_text(source)
    assert cleaned == source


def test_assignment_parser_handles_invalid_keys_and_separator_branches() -> None:
    """The low-level parser rejects malformed keys and accepts spaced assignments."""
    assert redact_sensitive_log._consume_sensitive_assignment("", 0) is None
    assert redact_sensitive_log._consume_sensitive_assignment("9token=value", 0) is None
    assert redact_sensitive_log._consume_sensitive_assignment("token_count=value", 0) is None
    assert redact_sensitive_log._consume_sensitive_assignment("token", 0) is None
    assert redact_sensitive_log._consume_sensitive_assignment('"token" : value', 0) == (
        '"token" : [REDACTED]',
        len('"token" : value'),
    )
    assert redact_sensitive_log._consume_sensitive_assignment("token = value", 0) == (
        "token = [REDACTED]",
        len("token = value"),
    )
