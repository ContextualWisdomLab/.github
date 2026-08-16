"""Regression tests for privileged OpenCode workflow security boundaries."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import runpy
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from scripts.ci import opencode_dispatch_status as dispatch_status
from scripts.ci import opencode_existing_approval_gate as approval_gate
from scripts.ci import opencode_review_normalize_output as normalizer
from scripts.ci import redact_sensitive_log as redactor
from scripts.ci import safe_pytest_command as safe_pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_sandbox_redaction_quality_gate_checks_nested_public_callables() -> None:
    """The docstring gate must inspect public methods and nested helpers."""
    workflow = (
        REPO_ROOT / ".github/workflows/sandbox-log-redaction-quality-ci.yml"
    ).read_text(encoding="utf-8")

    assert "name: Sandbox Log Redaction Quality CI" in workflow
    assert "name: Exact-head sandbox redaction contract" in workflow
    assert "name: Verify fail-closed sandbox redaction contract" in workflow
    assert "for node in ast.walk(tree):" in workflow
    assert "for node in tree.body:" not in workflow
    assert '      - "ARCHITECTURE.md"' in workflow
    assert '      - "docs/doctoring/sandbox-log-redaction.md"' in workflow


def _synthetic_jwt() -> str:
    """Build JWT-shaped fixture text without committing secret-looking literals."""
    header = base64.urlsafe_b64encode(b'{"alg":"HS256","typ":"JWT"}').rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(b'{"sub":"fixture-user"}').rstrip(b"=").decode()
    return ".".join((header, payload, "signaturefixture"))


def test_sensitive_log_redaction_handles_json_credentials_and_jwts() -> None:
    """Structured credentials and provider-independent JWTs never survive evidence redaction."""
    jwt_fixture = _synthetic_jwt()
    secrets = {
        "apikey": "fixture-joined-api-key",
        "token": jwt_fixture,
        "jwt": jwt_fixture,
        "oidc_token": jwt_fixture,
        "oidctoken": "fixture-joined-oidc-token",
        "api_credential": "fixture-api-credential",
        "client_secret": "fixture-client-secret",
        "client_secret_b64": "fixture-client-secret-base64",
        "clientsecrethash": "fixture-joined-client-secret-hash",
        "connection_string": "fixture-connection-string",
        "credential_data": "fixture-credential-data",
        "credentials_json": "fixture-credentials-json",
        "database_url": "fixture-database-url",
        "encryption_key": "fixture-encryption-key",
        "githubtoken": "fixture-joined-github-token",
        "myservicecredential": "fixture-joined-service-credential",
        "MY_SERVICE_TOKEN": "fixture-service-token",
        "password_hash": "fixture-password-hash",
        "private_key_data": "fixture-private-key-data",
        "private_key_pem": "fixture-private-key-pem",
        "refreshtoken": "fixture-joined-refresh-token",
        "secret_key": "fixture-secret-key",
        "secret_material": "fixture-secret-material",
        "servicepasswordhash": "fixture-joined-service-password-hash",
        "signing_key": "fixture-signing-key",
        "token_response": "fixture-token-response",
    }
    cleaned = redactor.redact_text(json.dumps({"nested": secrets}))

    assert all(value not in cleaned for value in secrets.values())
    assert set(json.loads(cleaned)["nested"].values()) == {redactor.REDACTED}

    key_collision = json.loads(
        redactor.redact_text(
            json.dumps({"password": "second-credential-material-731"}),
            sensitive_values=("password",),
        )
    )
    assert key_collision == {redactor.REDACTED: redactor.REDACTED}


def test_sensitive_log_redaction_preserves_normal_diagnostics() -> None:
    """Ordinary failure reasons remain visible while credentials are removed."""
    source = (
        "build failed for package requests==2.31.0\n"
        "Authorization: Bearer abc.def.ghi\n"
        "SERVICE_TOKEN=opaque_service_value_123456789\n"
    )
    cleaned = redactor.redact_text(source)

    assert "build failed for package requests==2.31.0" in cleaned
    assert "abc.def.ghi" not in cleaned
    assert "opaque_service_value_123456789" not in cleaned
    assert cleaned.count(redactor.REDACTED) >= 2


def test_sensitive_log_redaction_handles_auth_headers_urls_and_command_values() -> None:
    """Common registry, URL-userinfo, and separated curl credential forms are removed."""
    opaque_secret = "opaque-auth-material-123456789"
    source = (
        f"Authorization: token {opaque_secret}\n"
        f"Proxy-Authorization: Custom {opaque_secret}\n"
        f"registry https://alice:{opaque_secret}@registry.example.test/image\n"
        f"cache redis://:{opaque_secret}@cache.internal:6379/0\n"
        f"auth={opaque_secret}\n"
    )

    cleaned = redactor.redact_text(source)
    structured = json.loads(
        redactor.redact_text(
            json.dumps(
                {
                    "detail": (
                        f'Authorization: Custom "{opaque_secret}"\n'
                        "ordinary structured diagnostic"
                    )
                }
            )
        )
    )
    command = redactor.redact_command_argv(
        [
            "curl",
            "--user",
            f"alice:{opaque_secret}",
            "-H",
            f"Authorization: token {opaque_secret}",
        ]
    )
    inline_command = redactor.redact_command_argv(
        ["curl", f"--user=alice:{opaque_secret}", "-u", f"alice:{opaque_secret}"]
    )
    proxy_command = redactor.redact_command_argv(
        [
            "curl",
            "--proxy-user",
            f"alice:{opaque_secret}",
            "--oauth2-bearer",
            opaque_secret,
        ]
    )

    assert opaque_secret not in cleaned
    assert opaque_secret not in structured["detail"]
    assert "ordinary structured diagnostic" in structured["detail"]
    assert "alice:" not in cleaned
    assert opaque_secret not in " ".join(command)
    assert command[2] == redactor.REDACTED
    assert command[4].endswith(redactor.REDACTED)
    assert inline_command == [
        "curl",
        f"--user={redactor.REDACTED}",
        "-u",
        redactor.REDACTED,
    ]
    assert proxy_command == [
        "curl",
        "--proxy-user",
        redactor.REDACTED,
        "--oauth2-bearer",
        redactor.REDACTED,
    ]


@pytest.mark.parametrize("program", ["docker", "podman", "/usr/bin/docker"])
def test_command_redaction_handles_container_login_short_password(
    program: str,
) -> None:
    """Container login passwords are hidden without masking publish ports."""
    credential = "-".join(("quartz", "capybara", "731", "opaque"))

    assert redactor.redact_command_argv(
        [program, "login", "-p", credential]
    ) == [program, "login", "-p", redactor.REDACTED]
    assert redactor.redact_command_argv(
        [program, "login", f"-p={credential}"]
    ) == [program, "login", f"-p={redactor.REDACTED}"]
    assert redactor.redact_command_argv(
        [program, "login", f"--password={credential}"]
    ) == [program, "login", f"--password={redactor.REDACTED}"]
    assert redactor.redact_command_argv(
        [program, "run", "-p", "8080:80", "image"]
    ) == [program, "run", "-p", "8080:80", "image"]


def test_command_redaction_preserves_unrelated_short_port_option() -> None:
    """Program-aware password handling cannot consume an SSH port."""
    assert redactor.redact_command_argv(
        ["ssh", "-p", "22", "host"]
    ) == ["ssh", "-p", "22", "host"]


def test_sensitive_log_redaction_removes_multiline_private_key_blocks() -> None:
    """Credential assignments cannot expose later lines of a PEM private key block."""
    begin_private_key = "-----BEGIN " + "PRIVATE KEY-----"
    end_private_key = "-----END " + "PRIVATE KEY-----"
    begin_pgp_private_key = "-----BEGIN PGP " + "PRIVATE KEY BLOCK-----"
    end_pgp_private_key = "-----END PGP " + "PRIVATE KEY BLOCK-----"
    source = (
        f"PRIVATE_KEY={begin_private_key}\n"
        "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSj\n"
        f"{end_private_key}\n"
        f"PGP_PRIVATE_KEY={begin_pgp_private_key}\n"
        "xcLYBFfixturePrivatePacketBody731\n"
        f"{end_pgp_private_key}\n"
        "ordinary diagnostic after\n"
    )

    cleaned = redactor.redact_text(source)
    structured_cleaned = json.loads(
        redactor.redact_text(json.dumps({"detail": source}))
    )["detail"]

    assert "BEGIN PRIVATE KEY" not in cleaned
    assert "MIIEvQ" not in cleaned
    assert "END PRIVATE KEY" not in cleaned
    assert "fixturePrivatePacketBody" not in cleaned
    assert "MIIEvQ" not in structured_cleaned
    assert "fixturePrivatePacketBody" not in structured_cleaned
    assert "ordinary diagnostic after" in cleaned
    assert cleaned.count("\n") == source.count("\n")


def test_sensitive_log_redaction_handles_adversarial_quoted_values() -> None:
    """Quoted sensitive assignments are parsed linearly even with many escapes."""
    source = "_jwt:\"" + "\\!" * 5000
    cleaned = redactor.redact_text(source)

    assert "\\!" not in cleaned
    assert cleaned == f"_jwt:{redactor.REDACTED}"


def test_sensitive_log_redaction_assignment_parser_edges_remain_auditable() -> None:
    """Malformed assignments remain parseable while valid quoted secrets are scrubbed."""
    cases = {
        "'jwt': visible": f"'jwt': {redactor.REDACTED}",
        "'jwt: visible": f"'jwt: {redactor.REDACTED}",
        "token : visible": f"token : {redactor.REDACTED}",
        "token visible": "token visible",
        "token=": "token=",
        "token=,": "token=,",
        "9safe=value": "9safe=value",
        '"token: value': f'"token: {redactor.REDACTED}',
        "token:   ": "token:   ",
    }

    for source, expected in cases.items():
        assert redactor.redact_text(source) == expected

    assert redactor.redact_text('token="safe\\"inside" trailing') == (
        f"token={redactor.REDACTED} trailing"
    )


def test_sensitive_log_redaction_scrubs_provider_token_shapes() -> None:
    """Provider-shaped tokens are removed even when they are not key/value assignments."""
    source = "\n".join(
        [
            "classic ghp_" + ("A" * 24),
            "fine github_pat_" + ("B" * 24),
            "openai sk-" + ("C" * 24),
            "slack xoxb-" + ("D" * 24),
            "aws AKIA" + ("E" * 16),
        ]
    )
    cleaned = redactor.redact_text(source)

    assert "ghp_" not in cleaned
    assert "github_pat_" not in cleaned
    assert "sk-" not in cleaned
    assert "xoxb-" not in cleaned
    assert "AKIA" not in cleaned
    assert cleaned.count(redactor.REDACTED) == 5


def test_sensitive_log_redaction_distinguishes_jwts_from_diagnostic_domains() -> None:
    """JWT recognition preserves provider hostnames used by failed-check classification."""
    jwt_fixture = _synthetic_jwt()
    non_jose_header = base64.urlsafe_b64encode(b'{"typ":"diagnostic"}').rstrip(b"=").decode()
    dotted_diagnostic = f"{non_jose_header}.payload.signature"
    source = (
        f"provider api.deepseek.com failed\n"
        f"dotted diagnostic {dotted_diagnostic}\n"
        f"opaque jwt {jwt_fixture}\n"
    )

    cleaned = redactor.redact_text(source)

    assert "api.deepseek.com" in cleaned
    assert dotted_diagnostic in cleaned
    assert jwt_fixture not in cleaned
    assert cleaned.count(redactor.REDACTED) == 1


def test_sensitive_log_redaction_falls_back_safely_for_excessive_json_nesting() -> None:
    """Pathological structured diagnostics cannot abort the shared evidence collector."""
    provider_token = "ghp_" + ("N" * 24)
    source = "[" * 2000 + json.dumps(provider_token) + "]" * 2000

    cleaned = redactor.redact_text(source)

    assert provider_token not in cleaned
    assert redactor.REDACTED in cleaned

    excessive_integer = "9" * 5000
    assert redactor.redact_text(excessive_integer) == excessive_integer


def test_sensitive_log_redaction_bounds_near_limit_malformed_json_rescans() -> None:
    """Near-limit malformed JSON candidates must complete within the CI budget."""
    source = (
        "from scripts.ci.redact_sensitive_log import "
        "MAX_RAW_JSON_INPUT_BYTES, REDACTED, redact_text; "
        "tail = '{\"token\":\"secret-value\"'; "
        "text = '[' * (MAX_RAW_JSON_INPUT_BYTES - len(tail) - 1) + tail; "
        "assert redact_text(text) == REDACTED"
    )

    subprocess.run(
        [sys.executable, "-c", source],
        cwd=REPO_ROOT,
        check=True,
        shell=False,
        timeout=5,
    )


def test_sensitive_log_redaction_handles_lists_empty_input_and_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    """Recursive lists, empty input, and the streaming CLI share the same scrubber."""
    source = '{"values":[{"ok":1,"api_key":"secret-value"},2]}\n'
    assert redactor.redact_text("") == ""
    assert json.loads(redactor.redact_text(source))["values"] == [
        {"ok": 1, "api_key": redactor.REDACTED},
        2,
    ]

    stdin = io.StringIO("SERVICE_TOKEN=opaque-service-token-value\n")
    stdout = io.StringIO()
    monkeypatch.setattr(redactor.sys, "stdin", stdin)
    monkeypatch.setattr(redactor.sys, "stdout", stdout)
    assert redactor.main() == 0
    assert "opaque-service-token-value" not in stdout.getvalue()

    monkeypatch.setattr(sys, "argv", ["redact_sensitive_log.py"])
    monkeypatch.setattr(sys, "stdin", io.StringIO("password=hunter2\n"))
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    with pytest.raises(SystemExit) as exc:
        runpy.run_path("scripts/ci/redact_sensitive_log.py", run_name="__main__")
    assert exc.value.code == 0


def test_sensitive_log_redaction_scans_opaque_json_values_without_hiding_metadata() -> None:
    """Opaque JSON values are scrubbed while benign token and password metadata remains useful."""
    provider_token = "ghp_" + ("A" * 24)
    source = json.dumps(
        {
            "build_status": "failed",
            "diagnostic": provider_token,
            "nested": [{"detail": f"Bearer {provider_token}"}],
            "authorization_failure_reason": "missing repository scope",
            "credential_rotation_status": "current",
            "jwt_decode_error": "signature expired",
            "notsecret": "ordinary negative assertion",
            "password_policy": "minimum 14 characters",
            "password_policy_status": "compliant",
            "retoken": "retry label",
            "secret_scan_count": 0,
            "token_budget": 4096,
            "token_count": 512,
            "token_expires_at": "2026-08-09T00:00:00Z",
            "token_type": "Bearer",
            "token_usage": {"input": 256, "output": 128},
        }
    )

    cleaned = json.loads(redactor.redact_text(source))

    assert cleaned["build_status"] == "failed"
    assert cleaned["diagnostic"] == redactor.REDACTED
    assert cleaned["nested"] == [{"detail": f"Bearer {redactor.REDACTED}"}]
    assert cleaned["authorization_failure_reason"] == "missing repository scope"
    assert cleaned["credential_rotation_status"] == "current"
    assert cleaned["jwt_decode_error"] == "signature expired"
    assert cleaned["notsecret"] == "ordinary negative assertion"
    assert cleaned["password_policy"] == "minimum 14 characters"
    assert cleaned["password_policy_status"] == "compliant"
    assert cleaned["retoken"] == "retry label"
    assert cleaned["secret_scan_count"] == 0
    assert cleaned["token_budget"] == 4096
    assert cleaned["token_count"] == 512
    assert cleaned["token_expires_at"] == "2026-08-09T00:00:00Z"
    assert cleaned["token_type"] == "Bearer"
    assert cleaned["token_usage"] == {"input": 256, "output": 128}


def test_sensitive_log_redaction_removes_ansi_bypasses_but_preserves_visible_diagnostics() -> None:
    """Terminal control sequences cannot split credential keys or provider-token signatures."""
    opaque_secret = "-".join(("opaque", "fixture", "secret", "123456"))
    provider_body = "B" * 24
    source = (
        "ordinary build failure\n"
        f"to\x1b[31mken\x1b[0m={opaque_secret}\n"
        f"to\x1b(Bken={opaque_secret}\n"
        f"to\x1b7ken={opaque_secret}\n"
        f"to\x9b31mken={opaque_secret}\n"
        f"provider ghp_\x1b[32m{provider_body}\x1b[0m\n"
        + json.dumps(
            {
                "to\x1b[31mken": opaque_secret,
                "ghp_" + provider_body: "provider key diagnostic",
                f"{redactor.REDACTED}#2": "existing suffixed marker key",
                redactor.REDACTED: "existing marker key",
            }
        )
        + "\n"
    )

    cleaned = redactor.redact_text(source)

    assert opaque_secret not in cleaned
    assert provider_body not in cleaned
    assert "ordinary build failure" in cleaned
    assert "\x1b" not in cleaned
    assert "\x9b" not in cleaned
    structured = json.loads(cleaned.splitlines()[-1])
    assert len(structured) == 4
    assert sorted(structured.values()) == [
        redactor.REDACTED,
        "existing marker key",
        "existing suffixed marker key",
        "provider key diagnostic",
    ]
    assert all("ghp_" not in key for key in structured)


def test_sensitive_log_redaction_fails_closed_for_terminal_overwrite_controls() -> None:
    """Backspace, cursor motion, and invisible format controls cannot reconstruct secrets."""
    opaque_secret = "opaque-rendered-secret-123456"
    provider_body = "R" * 24
    source = (
        "ordinary diagnostic before\n"
        f"toX\bken={opaque_secret}\n"
        f"toX\x1b[1Dken={opaque_secret}\n"
        f"to\u200bken={opaque_secret}\n"
        f"to\u034fken={opaque_secret}\n"
        f"to\ufe0fken={opaque_secret}\n"
        f"provider ghp_X\b{provider_body}\n"
        + json.dumps({"toX\bken": opaque_secret})
        + "\nordinary diagnostic after\n"
    )

    cleaned = redactor.redact_text(source)

    assert opaque_secret not in cleaned
    assert provider_body not in cleaned
    assert "\b" not in cleaned
    assert "\x1b" not in cleaned
    assert "\u200b" not in cleaned
    assert "ordinary diagnostic before" in cleaned
    assert "ordinary diagnostic after" in cleaned
    assert cleaned.count(redactor.REDACTED) >= 7
    assert (
        redactor.redact_json_value(f"toX\x1b[1Dken={opaque_secret}")
        == redactor.REDACTED
    )


def test_sensitive_log_redaction_fails_closed_for_multiline_terminal_sequences() -> None:
    """Secrets inside multiline OSC/DCS control payloads cannot escape line-local checks."""
    opaque_secret = "opaque-multiline-terminal-secret-731"
    source = (
        "ordinary diagnostic before\n"
        f"\x1b]0;title-prefix\n{opaque_secret}\ntitle-suffix\x07\n"
        "ordinary diagnostic after\n"
    )

    cleaned = redactor.redact_text(source)

    assert opaque_secret not in cleaned
    assert "\x1b" not in cleaned
    assert "\x07" not in cleaned
    assert "ordinary diagnostic before" in cleaned
    assert "ordinary diagnostic after" in cleaned
    assert cleaned.count("\n") == source.count("\n")

    unterminated = f"\x1b]0;title-prefix\n{opaque_secret}\ntitle-suffix"
    unterminated_cleaned = redactor.redact_text(unterminated)
    assert opaque_secret not in unterminated_cleaned
    assert unterminated_cleaned.count("\n") == unterminated.count("\n")


def test_sensitive_log_redaction_accepts_explicit_literal_secrets() -> None:
    """Caller-supplied opaque and multiline credential values are removed exactly."""
    opaque_secret = "-".join(("opaque", "allow", "env", "fixture", "123456"))
    multiline_secret = "private-line-one\nprivate-line-two"
    ansi_secret = "violet\x1b[31m-capybara-731"
    source = f"ordinary diagnostic\n{opaque_secret}\n{multiline_secret}\n{ansi_secret}\n"

    cleaned = redactor.redact_text(
        source,
        sensitive_values=(
            opaque_secret,
            multiline_secret,
            ansi_secret,
            "",
            opaque_secret,
        ),
    )

    assert opaque_secret not in cleaned
    assert "private-line-one" not in cleaned
    assert "private-line-two" not in cleaned
    assert "violet-capybara-731" not in cleaned
    assert "ordinary diagnostic" in cleaned
    assert cleaned.count(redactor.REDACTED) == 3
    assert cleaned.count("\n") == source.count("\n")

    escaped = repr(multiline_secret)
    escaped_cleaned = redactor.redact_text(
        f"FileNotFoundError: {escaped}",
        sensitive_values=(multiline_secret,),
    )
    assert "private-line-one\\nprivate-line-two" not in escaped_cleaned


def test_sensitive_literal_redaction_preserves_leading_and_unicode_line_separators() -> None:
    """Opaque multiline values keep every separator at its original relative position."""
    leading_secret = "\nprivate-leading-value"
    unicode_secret = "private-unicode-one\u2028private-unicode-two"
    source = f"prefix{leading_secret} suffix\n{unicode_secret} tail"

    cleaned = redactor.redact_text(
        source,
        sensitive_values=(leading_secret, unicode_secret),
    )

    assert cleaned == (
        f"prefix\n{redactor.REDACTED} suffix\n"
        f"{redactor.REDACTED}\u2028 tail"
    )


def test_sensitive_log_redaction_preserves_all_supported_line_boundaries() -> None:
    """Line separators remain boundaries rather than unsafe inline controls."""
    source = "before\vafter\fnext\x1cunit\x85unicode\u2028paragraph\u2029last"

    assert redactor.redact_text(source) == source


def test_sensitive_literal_redaction_preserves_json_types_and_its_own_marker() -> None:
    """Opaque values redact string evidence without corrupting JSON or prior markers."""
    source = json.dumps(
        {
            "enabled": True,
            "literal": "true",
            "marker_word": "REDACTED",
            "opaque": "fixture-secret-long",
            "token_count": 512,
        }
    )

    cleaned_text = redactor.redact_text(
        source,
        sensitive_values=("fixture-secret-long", "REDACTED", "true"),
    )
    cleaned = json.loads(cleaned_text)

    assert cleaned["enabled"] is True
    assert cleaned["literal"] == redactor.REDACTED
    assert cleaned["marker_word"] == redactor.REDACTED
    assert cleaned["opaque"] == redactor.REDACTED
    assert cleaned["token_count"] == 512
    assert "[[REDACTED]]" not in cleaned_text


def test_sensitive_literal_redaction_does_not_rewrite_existing_markers() -> None:
    """Literal substrings inside an existing marker are never scanned as credentials."""
    source = "prior [REDACTED] evidence and plain REDACTED value"

    cleaned = redactor.redact_text(
        source,
        sensitive_values=("RED", "REDACTED"),
    )

    assert cleaned == "prior [REDACTED] evidence and plain [REDACTED] value"
    assert redactor.redact_text(
        "prior [REDACTED] evidence",
        sensitive_values=("[REDACTE",),
    ) == "prior [REDACTED] evidence"


def test_command_redaction_fails_closed_for_malformed_sensitive_quoting() -> None:
    """Malformed shell quoting hides sensitive option evidence but preserves benign text."""
    assert (
        redactor.redact_command_text("tool --token 'unterminated")
        == redactor.REDACTED
    )
    assert redactor.redact_command_text("tool 'unterminated") == "tool 'unterminated"


def test_sensitive_log_redaction_processes_long_key_like_diagnostics_within_budget() -> None:
    """A modest non-secret key-like line cannot trigger quadratic CI redaction work."""
    source = (
        "from scripts.ci.redact_sensitive_log import redact_text; "
        "value = 'a' * 10000; assert redact_text(value) == value"
    )

    subprocess.run(
        [sys.executable, "-c", source],
        cwd=REPO_ROOT,
        check=True,
        shell=False,
        timeout=5,
    )


def test_sensitive_log_redaction_processes_many_lines_and_values_within_budget() -> None:
    """Many opaque values cannot multiply work independently for every log line."""
    source = (
        "from scripts.ci.redact_sensitive_log import redact_text; "
        "text = 'ordinary diagnostic\\n' * 20000; "
        "values = tuple(f'opaque-{index:03d}-fixture-value' for index in range(100)); "
        "assert redact_text(text, sensitive_values=values) == text"
    )

    subprocess.run(
        [sys.executable, "-c", source],
        cwd=REPO_ROOT,
        check=True,
        shell=False,
        timeout=5,
    )


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("pytest -q tests", ["pytest", "-q", "tests"]),
        ("python3 -m pytest tests/unit", ["python3", "-m", "pytest", "tests/unit"]),
        ("coverage run -m pytest tests", ["coverage", "run", "-m", "pytest", "tests"]),
    ],
)
def test_safe_pytest_parser_accepts_supported_argv(command: str, expected: list[str]) -> None:
    """Legitimate pytest invocations are preserved as direct argv."""
    assert safe_pytest.parse_safe_pytest_command(command) == expected


def test_safe_pytest_argv_classifier_rejects_empty_argv() -> None:
    """The direct-execution classifier fails closed for an empty command."""
    assert safe_pytest._is_pytest_argv([]) is False


@pytest.mark.parametrize(
    "command",
    [
        'pytest ; printf PWNED > "$RUNNER_TEMP/injected"',
        "pytest && curl https://attacker.invalid",
        "bash -lc pytest",
        "curl pytest",
        "uv run pytest -q",
        "poetry run pytest -q",
        "pipenv run pytest -q",
        "pytest `id`",
        "pytest $(id)",
        "pytest 'unterminated",
        "",
    ],
)
def test_safe_pytest_parser_rejects_shell_and_non_pytest_execution(command: str) -> None:
    """PR-controlled shell syntax and unrelated executables are not accepted."""
    assert safe_pytest.parse_safe_pytest_command(command) is None


def test_safe_pytest_executor_never_uses_a_shell(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The realistic configured-command boundary executes validated argv with shell disabled."""
    observed: dict[str, object] = {}
    virtualenv_bin = tmp_path / ".venv" / "bin"
    virtualenv_bin.mkdir(parents=True)

    def fake_run(argv, *, cwd, env, shell, check):
        observed.update(argv=argv, cwd=cwd, env=env, shell=shell, check=check)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(safe_pytest.subprocess, "run", fake_run)
    assert safe_pytest.execute_command(tmp_path, ["pytest", "-q", "tests"]) == 0
    assert observed["argv"] == ["pytest", "-q", "tests"]
    assert observed["cwd"] == tmp_path
    assert observed["shell"] is False
    assert observed["check"] is False
    assert observed["env"]["PYTHONPATH"] == "."
    assert observed["env"]["PATH"].split(os.pathsep)[0] == str(virtualenv_bin)


def test_safe_pytest_executor_adds_src_layout_to_pythonpath(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A ``src``-layout project imports its package: ``src`` is prepended to PYTHONPATH."""
    observed: dict[str, object] = {}
    (tmp_path / "src").mkdir()

    def fake_run(argv, *, cwd, env, shell, check):
        observed.update(env=env)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(safe_pytest.subprocess, "run", fake_run)
    assert safe_pytest.execute_command(tmp_path, ["pytest", "tests"]) == 0
    assert observed["env"]["PYTHONPATH"] == os.pathsep.join(("src", "."))


def test_configured_pytest_discovery_drops_injected_workflow_command(tmp_path: Path) -> None:
    """Only supported one-line pytest argv are returned from a PR-controlled workflow file."""
    workflow_dir = tmp_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)
    (workflow_dir / "ci.yml").write_text(
        "steps:\n"
        "  - run: pytest -q tests\n"
        "  - run: pytest -q tests\n"
        "  - run: pytest ; printf PWNED > /tmp/injected\n"
        "  - run: curl pytest\n",
        encoding="utf-8",
    )

    assert safe_pytest.discover_commands(workflow_dir) == [["pytest", "-q", "tests"]]
    assert safe_pytest.discover_commands(tmp_path / "missing") == []


def test_safe_pytest_cli_paths_and_invalid_execution(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Discovery and execution CLI paths reject malformed or unsafe JSON."""
    workflow_dir = tmp_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)
    (workflow_dir / "ci.yml").write_text("run: python -m pytest -q\n", encoding="utf-8")

    assert safe_pytest.main(["discover", "--workflow-dir", str(workflow_dir)]) == 0
    assert json.loads(capsys.readouterr().out) == ["python", "-m", "pytest", "-q"]

    real_execute_command = safe_pytest.execute_command
    monkeypatch.setattr(safe_pytest, "execute_command", lambda project_dir, argv: 7)
    assert safe_pytest.main(
        ["execute", "--project-dir", str(tmp_path), "--command-json", '["pytest","-q"]']
    ) == 7
    assert "Executing configured pytest argv" in capsys.readouterr().out

    with pytest.raises(SystemExit, match="invalid --command-json"):
        safe_pytest.main(
            ["execute", "--project-dir", str(tmp_path), "--command-json", "not-json"]
        )
    with pytest.raises(SystemExit, match="array of strings"):
        safe_pytest.main(
            ["execute", "--project-dir", str(tmp_path), "--command-json", '{"pytest":true}']
        )
    with pytest.raises(ValueError, match="safe direct pytest"):
        real_execute_command(tmp_path, ["bash", "-lc", "pytest"])

    monkeypatch.setattr(
        sys,
        "argv",
        ["safe_pytest_command.py", "discover", "--workflow-dir", str(tmp_path / "missing")],
    )
    with pytest.raises(SystemExit) as exc:
        runpy.run_path("scripts/ci/safe_pytest_command.py", run_name="__main__")
    assert exc.value.code == 0


DISPATCH_SOURCE_LINES = (
    b"name: Required OpenCode Review",
    b"on:",
)


@pytest.fixture
def trusted_dispatch_status_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """Seal the source and changed-file evidence used by dispatch-status review validation."""
    runner_temp = tmp_path / "runner-temp"
    source_root = tmp_path / "source"
    source_path = source_root / ".github" / "workflows" / "opencode-review.yml"
    runner_temp.mkdir()
    source_path.parent.mkdir(parents=True)
    source_path.write_bytes(b"\n".join(DISPATCH_SOURCE_LINES) + b"\n")

    changed_files = runner_temp / "opencode-changed-files.txt"
    changed_files.write_text(".github/workflows/opencode-review.yml\n", encoding="utf-8")
    manifest = runner_temp / "opencode-artifact-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": 1,
                "artifacts": {
                    changed_files.name: hashlib.sha256(changed_files.read_bytes()).hexdigest()
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("RUNNER_TEMP", str(runner_temp))
    monkeypatch.setenv("OPENCODE_SOURCE_WORKDIR", str(source_root))
    monkeypatch.setenv("OPENCODE_CHANGED_FILES_FILE", str(changed_files))
    monkeypatch.setenv(
        "OPENCODE_ARTIFACT_MANIFEST_SHA256",
        hashlib.sha256(manifest.read_bytes()).hexdigest(),
    )
    normalizer.current_changed_files.cache_clear()
    yield
    normalizer.current_changed_files.cache_clear()


def approval_review(head_sha: str, **overrides: object) -> dict[str, object]:
    """Build one exact-current-head OpenCode approval review."""
    adversarial_validation = {
        "status": "passed",
        "probes": [
            {
                "path": ".github/workflows/opencode-review.yml",
                "line": line,
                "hypothesis": f"Approval bypass hypothesis {line}.",
                "attack_or_counterexample": f"Supply forged evidence variant {line}.",
                "evidence": (
                    f"Source trace at .github/workflows/opencode-review.yml:{line} "
                    "confirmed the gate rejected the forged evidence. "
                    f"source-line-sha256={hashlib.sha256(source_line).hexdigest()}"
                ),
                "outcome": "falsified",
            }
            for line, source_line in enumerate(DISPATCH_SOURCE_LINES, start=1)
        ],
        "residual_risk": "Hosted token permissions remain externally enforced.",
    }
    review: dict[str, object] = {
        "state": "APPROVED",
        "commit_id": head_sha,
        "user": {"login": "opencode-agent[bot]"},
        "body": "\n".join(
            (
                "## Pull request overview",
                "",
                "OpenCode reviewed the current-head bounded evidence and found no blocking issues.",
                "",
                "## Adversarial validation",
                "",
                "```json",
                json.dumps(adversarial_validation),
                "```",
                "",
                "- Result: APPROVE",
                f"- Head SHA: `{head_sha}`",
                "- Workflow run: 123",
                "- Workflow attempt: 2",
            )
        ),
    }
    review.update(overrides)
    return review


def test_dispatch_status_requires_live_current_head_approval_and_coverage(
    trusted_dispatch_status_artifacts: None,
) -> None:
    """A repository-dispatch status succeeds only for the validated approval boundary."""
    head = "a" * 40
    review = approval_review(head)
    assert (
        approval_gate.review_rejection_reason(
            review,
            head,
            approval_authors=approval_gate.OPENCODE_APP_APPROVAL_AUTHORS,
        )
        is None
    )
    decision = dispatch_status.decide_status(
        model_outcome="success",
        coverage_result="success",
        expected_head=head,
        pull_request={"head": {"sha": head}},
        reviews=[review],
    )

    assert decision["state"] == "success"
    assert "validated" in decision["description"].lower()


def test_dispatch_status_latest_current_head_decision_is_authoritative(
    trusted_dispatch_status_artifacts: None,
) -> None:
    """A later current-head change request supersedes an earlier approval."""
    head = "a" * 40
    reviews = [
        approval_review(head),
        approval_review(head, state="CHANGES_REQUESTED"),
    ]

    decision = dispatch_status.decide_status(
        model_outcome="success",
        coverage_result="success",
        expected_head=head,
        pull_request={"head": {"sha": head}},
        reviews=reviews,
    )

    assert decision["state"] == "failure"


def test_dispatch_status_reuses_verified_approval_after_current_pool_exhaustion(
    trusted_dispatch_status_artifacts: None,
) -> None:
    """A prior exact-head real-model approval remains authoritative across a retry outage."""
    head = "a" * 40

    decision = dispatch_status.decide_status(
        model_outcome="exhausted",
        coverage_result="success",
        expected_head=head,
        pull_request={"head": {"sha": head}},
        reviews=[approval_review(head)],
    )

    assert decision["state"] == "success"


@pytest.mark.parametrize(
    ("model_outcome", "coverage_result", "live_head", "review_overrides"),
    [
        ("exhausted", "success", "current", {"body": "Looks good"}),
        ("success", "failure", "current", {}),
        ("success", "success", "stale", {}),
        ("success", "success", "current", {"state": "CHANGES_REQUESTED"}),
        ("success", "success", "current", {"commit_id": "b" * 40}),
        ("success", "success", "current", {"user": {"login": "pull-request-author"}}),
        ("success", "success", "current", {"body": "Looks good"}),
    ],
)
def test_dispatch_status_fails_closed_without_validated_approval(
    model_outcome: str,
    coverage_result: str,
    live_head: str,
    review_overrides: dict[str, object],
    trusted_dispatch_status_artifacts: None,
) -> None:
    """Negative, exhausted, stale, untrusted, and incomplete evidence cannot publish success."""
    head = "a" * 40
    observed_head = head if live_head == "current" else "c" * 40
    decision = dispatch_status.decide_status(
        model_outcome=model_outcome,
        coverage_result=coverage_result,
        expected_head=head,
        pull_request={"head": {"sha": observed_head}},
        reviews=[approval_review(head, **review_overrides)],
    )

    assert decision["state"] == "failure"
    assert decision["description"]


def test_dispatch_status_cli_and_evidence_shape_validation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    trusted_dispatch_status_artifacts: None,
) -> None:
    """The workflow-facing CLI emits JSON and rejects malformed evidence shapes."""
    head = "a" * 40
    pr_file = tmp_path / "pr.json"
    reviews_file = tmp_path / "reviews.json"
    pr_file.write_text(json.dumps({"head": {"sha": head}}), encoding="utf-8")
    reviews_file.write_text(json.dumps([approval_review(head)]), encoding="utf-8")
    args = [
        "--model-outcome",
        "success",
        "--coverage-result",
        "success",
        "--expected-head",
        head,
        "--pull-request-file",
        str(pr_file),
        "--reviews-file",
        str(reviews_file),
    ]

    assert dispatch_status.main(args) == 0
    assert json.loads(capsys.readouterr().out)["state"] == "success"

    reviews_file.write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit, match="reviews evidence an array"):
        dispatch_status.main(args)

    reviews_file.write_text(json.dumps([approval_review(head)]), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["opencode_dispatch_status.py", *args])
    with pytest.raises(SystemExit) as exc:
        runpy.run_path("scripts/ci/opencode_dispatch_status.py", run_name="__main__")
    assert exc.value.code == 0
