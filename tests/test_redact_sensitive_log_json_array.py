import pytest
from scripts.ci.redact_sensitive_log import redact_text

def test_redact_json_array_preserves_array():
    source = '   [{"token": "secret"}]'
    redacted = redact_text(source)
    assert '{"token":"[REDACTED]"}' in redacted

def test_redact_json_array_invalid_json():
    source = '   [not a json array]'
    redacted = redact_text(source)
    assert redacted == '   [not a json array]'
