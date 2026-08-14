from scripts.ci.redact_sensitive_log import redact_text


def test_redacts_allowlisted_operational_identifiers_in_json() -> None:
    source = (
        '{"email":"alice@example.com","phone":"+82 10-1234-5678",'
        '"ip":"192.0.2.10","path":"/home/runner/work/repo/run.json",'
        '"head_sha":"' + "a" * 40 + '","source":"backend/api.py"}\n'
    )

    cleaned = redact_text(source)

    assert "alice@example.com" not in cleaned
    assert "+82 10-1234-5678" not in cleaned
    assert "192.0.2.10" not in cleaned
    assert "/home/runner/work/repo/run.json" not in cleaned
    assert "[REDACTED_EMAIL]" in cleaned
    assert "[REDACTED_PHONE]" in cleaned
    assert "[REDACTED_IP]" in cleaned
    assert "[REDACTED_PATH]" in cleaned
    assert "a" * 40 in cleaned
    assert "backend/api.py" in cleaned


def test_redacts_allowlisted_identifiers_in_plain_diagnostics() -> None:
    source = (
        "contact bob@example.org at 010-1234-5678 from 203.0.113.4 "
        "/tmp/runner/secret.log\n"
    )

    cleaned = redact_text(source)

    assert "bob@example.org" not in cleaned
    assert "010-1234-5678" not in cleaned
    assert "203.0.113.4" not in cleaned
    assert "/tmp/runner/secret.log" not in cleaned
    assert cleaned.count("[REDACTED_") == 4
