import sys

import pytest

from scripts.ci.sanitize_github_output_summary import _entrypoint, sanitize_text


def test_sanitizes_secret_like_coverage_summary_values_without_losing_result():
    source = """## Coverage Decision

- Result: PASS
DATABASE_URL: postgresql://naruon:secret@db:5432/ai_email
AUTH_SESSION_HMAC_SECRET: super-secret
ENCRYPTION_KEY=abc123
Authorization: Bearer token-value
regular evidence line stays intact
"""

    sanitized = sanitize_text(source)

    assert "- Result: PASS" in sanitized
    assert "DATABASE_URL: <redacted>" in sanitized
    assert "AUTH_SESSION_HMAC_SECRET: <redacted>" in sanitized
    assert "ENCRYPTION_KEY=<redacted>" in sanitized
    assert "Authorization: Bearer <redacted>" in sanitized
    assert "secret@db" not in sanitized
    assert "super-secret" not in sanitized
    assert "token-value" not in sanitized
    assert "regular evidence line stays intact" in sanitized


def test_sanitizes_url_credentials_without_secret_key_prefix():
    sanitized = sanitize_text("postgresql://user:secret@db:5432/app\n")

    assert sanitized == "postgresql://<redacted>@db:5432/app\n"


def test_sanitizes_url_userinfo_without_password():
    """A username-only URL authority cannot leak through coverage evidence."""
    sanitized = sanitize_text("https://alice@example.invalid/artifact\n")

    assert sanitized == "https://<redacted>@example.invalid/artifact\n"
    assert "alice" not in sanitized


def test_sanitizes_mixed_credentials_before_truncating_at_secret_key():
    """Mixed URL, Authorization, and key-value secrets are all removed."""
    source = (
        "failure https://alice:url-secret@example.invalid/a.tgz "
        "Authorization: Bearer bearer-secret TOKEN=token-secret trailing context\n"
    )

    sanitized = sanitize_text(source)

    assert "https://<redacted>@example.invalid/a.tgz" in sanitized
    assert "Authorization: Bearer <redacted>" in sanitized
    assert "TOKEN=<redacted>" in sanitized
    assert "url-secret" not in sanitized
    assert "bearer-secret" not in sanitized
    assert "token-secret" not in sanitized


def test_cli_writes_sanitized_summary(tmp_path, monkeypatch):
    source = tmp_path / "coverage.md"
    destination = tmp_path / "coverage-output.md"
    source.write_text("DATABASE_URL=postgresql://user:secret@db/app\n- Result: PASS\n", encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "sanitize_github_output_summary.py",
            str(source),
            str(destination),
        ],
    )

    with pytest.raises(SystemExit) as excinfo:
        _entrypoint("__main__")

    assert excinfo.value.code == 0
    assert destination.read_text(encoding="utf-8") == "DATABASE_URL=<redacted>\n- Result: PASS\n"
