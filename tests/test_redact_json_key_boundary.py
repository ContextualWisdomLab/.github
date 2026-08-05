"""Regression evidence for credential-shaped JSON object keys."""

from __future__ import annotations

import re

from scripts.ci import redact_sensitive_log as redactor


def test_json_object_keys_use_the_unstructured_redaction_boundary(monkeypatch) -> None:
    """A JSON key matching a credential format must never bypass redaction."""

    monkeypatch.setattr(
        redactor,
        "PROVIDER_TOKEN_RES",
        (re.compile(r"\bcredential_key_marker\b"),),
    )

    assert redactor.redact_text('{"credential_key_marker":"safe"}\n') == (
        '{"[REDACTED]":"safe"}\n'
    )
