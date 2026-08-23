import runpy
import sys

import pytest

from scripts.ci.sanitize_github_output_summary import sanitize_text


def test_sanitizes_secret_like_coverage_summary_values_without_losing_result():
    source = """## Coverage Decision

- Result: PASS
DATABASE_URL: postgresql://naruon:secret@db:5432/ai_email
AUTH_SESSION_HMAC_SECRET: super-secret
ENCRYPTION_KEY=abc123
Authorization: Bearer token-value
github_pat_11ABCD2222333344445555
ghp_AbCdEfGhIjKlMnOpQrStUvWxYz1234567890
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
    assert "github_pat_11ABCD2222333344445555" not in sanitized
    assert "ghp_AbCdEfGhIjKlMnOpQrStUvWxYz1234567890" not in sanitized
    assert "<redacted>" in sanitized
    assert "regular evidence line stays intact" in sanitized


def test_sanitizes_url_credentials_without_secret_key_prefix():
    sanitized = sanitize_text("postgresql://user:secret@db:5432/app\n")

    assert sanitized == "postgresql://<redacted>@db:5432/app\n"


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

    from scripts.ci.sanitize_github_output_summary import main
    assert main() == 0
    assert destination.read_text(encoding="utf-8") == "DATABASE_URL=<redacted>\n- Result: PASS\n"


def test_sanitize_text_without_trailing_newline():
    from scripts.ci.sanitize_github_output_summary import sanitize_text
    source = "DATABASE_URL=postgresql://user:secret@db/app\n- Result: PASS"
    sanitized = sanitize_text(source)
    assert sanitized == "DATABASE_URL=<redacted>\n- Result: PASS"
