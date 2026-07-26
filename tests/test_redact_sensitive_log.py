import pytest
from scripts.ci.redact_sensitive_log import _consume_sensitive_assignment, _redact_assignments, redact_text

def test_consume_sensitive_assignment():
    text = "api_key='123' token=secret"
    res1, cursor = _consume_sensitive_assignment(text, 0)
    assert res1 == "api_key=[REDACTED]"
    assert cursor == 13

    # Ensure it skips whitespace and correctly captures next
    res2, cursor2 = _consume_sensitive_assignment(text, 14)
    assert res2 == "token=[REDACTED]"

def test_redact_assignments():
    text = "api_key='123' and something else token=secret"
    res = _redact_assignments(text)
    assert res == "api_key=[REDACTED] and something else token=[REDACTED]"

def test_consume_sensitive_assignment_no_match():
    text = "not_sensitive='123'"
    res = _consume_sensitive_assignment(text, 0)
    assert res is None

def test_redact_text_integration():
    text = 'some text api_key="secret_value" more text'
    res = redact_text(text)
    assert res == 'some text api_key=[REDACTED] more text'

def test_redact_main_coverage(monkeypatch, capsys):
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO("api_key='123'"))
    from scripts.ci.redact_sensitive_log import main
    assert main() == 0
    captured = capsys.readouterr()
    assert captured.out == "api_key=[REDACTED]"
