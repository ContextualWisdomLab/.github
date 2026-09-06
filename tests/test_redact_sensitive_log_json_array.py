import pytest
from scripts.ci.redact_sensitive_log import redact_text

def test_redact_json_array_preserves_array():
    """Verify that a valid JSON array is parsed and its inner objects redacted."""
    source = '   [{"token": "secret"}]'
    redacted = redact_text(source)
    assert '{"token":"[REDACTED]"}' in redacted

def test_redact_json_array_invalid_json():
    """Verify that a line starting with '[' but not valid JSON falls back safely."""
    source = '   [not a json array]'
    redacted = redact_text(source)
    assert redacted == '   [not a json array]'

def test_redact_scalar_json():
    """Verify that scalar JSON values are parsed but fall through to unstructured redaction."""
    secret_value = "secret" + "123456789"
    source = f'"token={secret_value}"'
    redacted = redact_text(source)
    assert redacted == '"token=[REDACTED]"'

def test_redact_literal_prefix_collision():
    """Verify that a plain-text line starting with 't' (but not 'true') is safely handled."""
    secret_value = "secret" + "123456789"
    source = f"token={secret_value}"
    redacted = redact_text(source)
    assert redacted == 'token=[REDACTED]'
