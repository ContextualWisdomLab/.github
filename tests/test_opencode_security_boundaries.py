"""Regression tests for privileged OpenCode workflow security boundaries."""

from __future__ import annotations

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


def _synthetic_jwt() -> str:
    """Build JWT-shaped fixture text without committing secret-looking literals."""
    return ".".join(("header", "payload", "signature"))


def test_sensitive_log_redaction_handles_json_credentials_and_jwts() -> None:
    """Structured credentials and provider-independent JWTs never survive evidence redaction."""
    jwt_fixture = _synthetic_jwt()
    secrets = {
        "token": jwt_fixture,
        "jwt": jwt_fixture,
        "oidc_token": jwt_fixture,
        "api_credential": "fixture-api-credential",
        "client_secret": "fixture-client-secret",
        "MY_SERVICE_TOKEN": "fixture-service-token",
    }
    cleaned = redactor.redact_text(json.dumps({"nested": secrets}))

    assert all(value not in cleaned for value in secrets.values())
    assert set(json.loads(cleaned)["nested"].values()) == {redactor.REDACTED}


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


def test_safe_pytest_executor_adds_trusted_monorepo_package_sources(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A service can import non-symlinked package sources from its repository."""
    observed: dict[str, object] = {}
    project_dir = tmp_path / "services" / "people-api"
    (project_dir / "src").mkdir(parents=True)
    package_root = tmp_path / "packages"
    hris_source = package_root / "hris-kernel" / "src"
    keyverse_source = package_root / "keyverse-adapter" / "src"
    hris_source.mkdir(parents=True)
    keyverse_source.mkdir(parents=True)
    (package_root / "not-a-package").write_text("fixture", encoding="utf-8")
    (package_root / "empty-package").mkdir()
    (package_root / "linked-package").symlink_to(package_root / "hris-kernel")
    (package_root / "linked-source").mkdir()
    (package_root / "linked-source" / "src").symlink_to(hris_source)

    def fake_run(argv, *, cwd, env, shell, check):
        observed.update(env=env)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(safe_pytest.subprocess, "run", fake_run)
    assert safe_pytest.execute_command(project_dir, ["pytest", "tests"]) == 0
    assert observed["env"]["PYTHONPATH"] == os.pathsep.join(
        ("src", ".", str(hris_source), str(keyverse_source))
    )


def test_safe_pytest_package_source_discovery_ignores_symlinked_packages(
    tmp_path: Path,
) -> None:
    """Symlinked ``packages`` roots are ignored during monorepo discovery."""
    project_dir = tmp_path / "linked-repository" / "services" / "people-api"
    project_dir.mkdir(parents=True)
    package_source = tmp_path / "real-packages" / "example" / "src"
    package_source.mkdir(parents=True)
    (tmp_path / "linked-repository" / "packages").symlink_to(tmp_path / "real-packages")

    assert safe_pytest._repository_package_python_paths(project_dir) == []


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
