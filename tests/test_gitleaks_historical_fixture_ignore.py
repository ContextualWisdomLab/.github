from pathlib import Path


def test_superseded_redaction_fixtures_have_exact_history_exemptions() -> None:
    """Keep the protected-history exemptions bound to two synthetic fixtures."""

    ignored = {
        line
        for line in Path(".gitleaksignore").read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    }
    assert {
        "bcff4afd4957a88c4720ff0f9bd6457c9102b950:"
        "tests/test_redact_sensitive_log_json_array.py:generic-api-key:18",
        "bcff4afd4957a88c4720ff0f9bd6457c9102b950:"
        "tests/test_redact_sensitive_log_json_array.py:generic-api-key:24",
    } <= ignored
