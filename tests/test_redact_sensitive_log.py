"""Tests for redact_sensitive_log CI script."""
import pytest
import sys
import os
import json
import runpy

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'scripts', 'ci')))
from redact_sensitive_log import redact_text, main  # type: ignore

def test_redact_empty() -> None:
    """Test redacting empty and None strings."""
    assert redact_text("") == ""
    assert redact_text(None) is None

def test_redact_preserve_newlines() -> None:
    """Test redacting preserves newlines and carriage returns."""
    text = "line1\nline2\r\nline3"
    assert redact_text(text) == "line1\nline2\r\nline3"

    text2 = "line1\nline2\r\nline3\n"
    assert redact_text(text2) == "line1\nline2\r\nline3\n"

def test_redact_json() -> None:
    """Test redacting handles valid JSON recursively."""
    raw = {
        "safe_key": "safe_value",
        "password": "super_secret",  # nosec B105
        "nested": {
            "token": "my_token",  # nosec B105
            "list": [{"api_key": "abc"}, "normal"]
        },
        "list_root": ["a", "b"]
    }
    raw_str = json.dumps(raw)
    redacted_str = redact_text(raw_str)
    redacted = json.loads(redacted_str)

    assert redacted["safe_key"] == "safe_value"
    assert redacted["password"] == "[REDACTED]"
    assert redacted["nested"]["token"] == "[REDACTED]"
    assert redacted["nested"]["list"][0]["api_key"] == "[REDACTED]"
    assert redacted["nested"]["list"][1] == "normal"
    assert redacted["list_root"] == ["a", "b"]

def test_redact_unstructured_tokens() -> None:
    """Test redacting known token patterns from unstructured text."""
    text = "Here is my token: ghp_123456789012345678901234567890123456\nand another github_pat_123456789012345678901234567890\nsk-12345678901234567890\nxoxb-12345678901234567890\nAKIA1234567890ABCDEF"
    redacted = redact_text(text)
    assert "ghp_" not in redacted
    assert "github_pat_" not in redacted
    assert "sk-" not in redacted
    assert "xoxb-" not in redacted
    assert "AKIA" not in redacted
    assert redacted.count("[REDACTED]") == 5

def test_redact_assignments() -> None:
    """Test redacting structured sensitive key-value assignments."""
    cases = [
        ("token=secret", "token=[REDACTED]"),
        ("password = \"secret\"", "password = [REDACTED]"),
        ("api_key: secret", "api_key: [REDACTED]"),
        ("'session_key': 'secret'", "'session_key': [REDACTED]"),
        ("token=secret, safe=value", "token=[REDACTED], safe=value"),
        ("token=\"secret with \\\" escape\", safe=value", "token=[REDACTED], safe=value"),
        ("safe=value token=secret", "safe=value token=[REDACTED]"),
        ("jwt = a.b.c", "jwt = [REDACTED]"),
    ]
    for raw, expected in cases:
        assert redact_text(raw) == expected

def test_redact_assignments_edge_cases() -> None:
    """Test edge cases in token assignment parser logic."""
    cases = [
        ("no_equals_here", "no_equals_here"),
        ("=", "="),
        ("\"key_no_closing", "\"key_no_closing"),
        ("\"token\" = \"val", "\"token\" = [REDACTED]"),
        ("token = ", "token = "),
        ("!token = val", "!token = [REDACTED]"),
        ("123token = val", "123token = [REDACTED]"),
        ("key: \"unfinished_string", "key: \"unfinished_string"),
    ]
    for raw, expected in cases:
        assert redact_text(raw) == expected

def test_redact_assignment_empty_value() -> None:
    """Test token assignment parser correctly stops on empty values."""
    assert redact_text("token=, safe") == "token=, safe"
    assert redact_text("token=} safe") == "token=} safe"

def test_redact_jwt_and_bearer() -> None:
    """Test redacting JWT and Bearer patterns from headers/text."""
    text = "Basic user:pass\nheader.payload.signature"
    redacted = redact_text(text)
    assert "user:pass" not in redacted
    assert "header.payload.signature" not in redacted
    assert redacted.count("[REDACTED]") == 2

    text_bearer = "Bearer my_secret_token"
    redacted_bearer = redact_text(text_bearer)
    assert "my_secret_token" not in redacted_bearer
    assert redacted_bearer.count("[REDACTED]") == 1

def test_main(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """Test the main entrypoint reading stdin and printing stdout."""
    monkeypatch.setattr(sys.stdin, 'read', lambda: "password=secret\n")
    assert main() == 0
    captured = capsys.readouterr()
    assert captured.out == "password=[REDACTED]\n"

def test_main_sys_exit(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """Test script invocation via runpy to cover SystemExit handling."""
    monkeypatch.setattr(sys.stdin, 'read', lambda: "password=secret\n")
    with pytest.raises(SystemExit) as e:
        runpy.run_path(os.path.join(os.path.dirname(__file__), '..', 'scripts', 'ci', 'redact_sensitive_log.py'), run_name='__main__')
    assert e.value.code == 0
    captured = capsys.readouterr()
    assert captured.out == "password=[REDACTED]\n"
