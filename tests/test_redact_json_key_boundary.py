"""Regression evidence for credential-shaped JSON keys and bounded scanning."""

from __future__ import annotations

import re

from scripts.ci import redact_sensitive_log as redactor


def test_json_object_keys_use_the_unstructured_redaction_boundary(monkeypatch) -> None:
    """A JSON key matching a credential format must never bypass redaction."""

    monkeypatch.setattr(
        redactor,
        "PROVIDER_TOKEN_RES",
        (re.compile(r"\bprovider_marker_value\b"),),
    )

    assert redactor.redact_text('{"provider_marker_value":"safe"}\n') == (
        '{"[REDACTED]":"safe"}\n'
    )


def test_assignment_scan_does_not_rescan_one_long_ordinary_identifier(
    monkeypatch,
) -> None:
    """A long non-sensitive token must be inspected once rather than quadratically."""

    class CountingSensitivePattern:
        """Count the total candidate characters inspected by key classification."""

        def __init__(self) -> None:
            self.inspected_characters = 0

        def search(self, value: str):
            """Record one candidate and report that it is not a sensitive key."""

            self.inspected_characters += len(value)
            return None

    counting_pattern = CountingSensitivePattern()
    monkeypatch.setattr(redactor, "SENSITIVE_KEY_RE", counting_pattern)
    ordinary_identifier = "ordinary_identifier_" * 512

    assert redactor.redact_text(ordinary_identifier) == ordinary_identifier
    assert counting_pattern.inspected_characters <= len(ordinary_identifier)
