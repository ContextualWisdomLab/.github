"""Behavioral tests for bounded OpenCode model-pool failure diagnostics."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "ci" / "run_opencode_review_model_pool.sh"

CENTRAL_FALLBACK_ENV = {
    "CENTRAL_REVIEW_PROCESS_FALLBACK_ELIGIBLE",
    "CENTRAL_REVIEW_PROCESS_FALLBACK_SCOPE_LABEL",
    "OPENCODE_APPROVAL_REPAIR_EVIDENCE_FILE",
    "OPENCODE_ARTIFACT_MANIFEST_SHA256",
    "OPENCODE_DYNAMIC_REVIEW_CADENCE",
    "OPENCODE_EVIDENCE_FILE",
    "OPENCODE_REQUIRE_ADVERSARIAL_VALIDATION",
}
INHERITED_PROVIDER_CREDENTIAL_ENV = {
    "NVIDIA_API_KEY",
    "NVIDIA_NIM_API_KEY",
}


def bash_command() -> str:
    """Return a Bash executable that can run repository shell scripts locally."""
    if os.name == "nt":
        git_bash = Path("C:/Program Files/Git/bin/bash.exe")
        if git_bash.exists():
            return str(git_bash)
    found = shutil.which("bash")
    if found:
        return found
    raise RuntimeError("bash executable was not found")


def bash_path(path: Path) -> str:
    """Return a path string usable by the bash process under test."""
    if os.name != "nt":
        return str(path)
    resolved = path.resolve()
    drive = resolved.drive.rstrip(":").lower()
    posix_path = resolved.as_posix()
    if drive:
        return f"/{drive}{posix_path[2:]}"
    return posix_path


def seal_artifacts(
    runner_temp: Path,
    *,
    head_sha: str,
    run_id: str,
    run_attempt: str,
    paths: tuple[Path, ...],
) -> str:
    """Seal fixed runner artifacts with current-run identity and SHA-256 digests."""
    artifacts = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in paths
        if path.is_file()
    }
    manifest = runner_temp / "opencode-artifact-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": 1,
                "head_sha": head_sha,
                "run_id": run_id,
                "run_attempt": run_attempt,
                "artifacts": artifacts,
            }
        ),
        encoding="utf-8",
    )
    manifest.chmod(0o600)
    for path in paths:
        if path.exists():
            path.chmod(0o600)
    return hashlib.sha256(manifest.read_bytes()).hexdigest()


def skip_if_windows_bash_is_unresponsive(command: str) -> None:
    """Skip with a visible reason when local Git Bash cannot start on Windows."""
    if os.name != "nt":
        return
    try:
        result = subprocess.run(
            [command, "-lc", "printf bash-ok"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except subprocess.TimeoutExpired:
        pytest.skip(
            "Git Bash did not respond to a smoke command within 5 seconds on Windows"
        )
    if result.returncode != 0:
        pytest.skip(
            f"Git Bash smoke command failed on Windows: {result.stderr.strip()}"
        )


def run_failed_model(
    tmp_path: Path,
    *,
    json_line: str = "",
    stderr_line: str = "",
    evidence_excerpt: str = "",
    changed_files: list[str] | None = None,
    extra_env: dict[str, str] | None = None,
    model_candidates: str = "github-models/openai/gpt-5",
    prompt_capture: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run one fake provider failure through the real model-pool launcher."""
    command = bash_command()
    skip_if_windows_bash_is_unresponsive(command)
    review_dir = tmp_path / "review"
    source_dir = tmp_path / "source"
    runner_temp = tmp_path / "runner-temp"
    fake_bin = tmp_path / "bin"
    for path in (review_dir, source_dir, runner_temp, fake_bin):
        path.mkdir()
    shutil.copy2(ROOT / "opencode.jsonc", review_dir / "opencode.jsonc")
    evidence_file = runner_temp / "opencode-review-evidence.md"
    evidence_file.write_text("bounded current-head evidence\n", encoding="utf-8")
    changed_files_file = runner_temp / "opencode-changed-files.txt"
    if changed_files is not None:
        changed_files_file.write_text("\n".join(changed_files) + "\n", encoding="utf-8")
    manifest_digest = seal_artifacts(
        runner_temp,
        head_sha="1" * 40,
        run_id="29189945378",
        run_attempt="1",
        paths=(evidence_file, changed_files_file),
    )
    if evidence_excerpt:
        (review_dir / "bounded-review-evidence-excerpt.md").write_text(
            evidence_excerpt, encoding="utf-8"
        )
        (review_dir / "bounded-review-evidence.md").write_text(
            f"full evidence\n{evidence_excerpt}", encoding="utf-8"
        )
    fake_opencode = fake_bin / "opencode"
    fake_opencode.write_text(
        "#!/usr/bin/env bash\n"
        'if [ "${1:-}" = run ]; then\n'
        '  [ -z "${FAKE_OPENCODE_PROMPT_CAPTURE:-}" ] || printf \'%s\\n\' "$2" > "$FAKE_OPENCODE_PROMPT_CAPTURE"\n'
        '  [ -z "${FAKE_OPENCODE_JSON:-}" ] || printf \'%s\\n\' "$FAKE_OPENCODE_JSON"\n'
        '  [ -z "${FAKE_OPENCODE_STDERR:-}" ] || printf \'%s\\n\' "$FAKE_OPENCODE_STDERR" >&2\n'
        '  sleep "${FAKE_OPENCODE_HANG_SECONDS:-0}"\n'
        '  exit "${FAKE_OPENCODE_RUN_EXIT:-1}"\n'
        "fi\n"
        'if [ "${1:-}" = export ]; then\n'
        '  [ -z "${FAKE_OPENCODE_EXPORT:-}" ] || printf \'%s\\n\' "$FAKE_OPENCODE_EXPORT"\n'
        '  exit "${FAKE_OPENCODE_EXPORT_EXIT:-0}"\n'
        "fi\n"
        "printf 'unexpected fake opencode command: %s\\n' \"$*\" >&2\n"
        "exit 2\n",
        encoding="utf-8",
    )
    fake_opencode.chmod(0o755)
    github_output = tmp_path / "github-output.txt"
    env = os.environ.copy()
    for name in CENTRAL_FALLBACK_ENV | INHERITED_PROVIDER_CREDENTIAL_ENV:
        env.pop(name, None)
    env.update(
        {
            "FAKE_OPENCODE_JSON": json_line,
            "FAKE_OPENCODE_PROMPT_CAPTURE": bash_path(prompt_capture)
            if prompt_capture
            else "",
            "FAKE_OPENCODE_STDERR": stderr_line,
            "GITHUB_OUTPUT": bash_path(github_output),
            "GITHUB_WORKSPACE": bash_path(ROOT),
            "HEAD_SHA": "1" * 40,
            "OPENCODE_ARTIFACT_MANIFEST_SHA256": manifest_digest,
            "OPENCODE_CHANGED_FILES_FILE": bash_path(changed_files_file),
            "OPENCODE_EVIDENCE_FILE": bash_path(evidence_file),
            "OPENCODE_FATAL_ERROR_POLL_SECONDS": "1",
            "OPENCODE_MODEL_ATTEMPTS": "1",
            "OPENCODE_MODEL_CANDIDATES": model_candidates,
            "OPENCODE_OUTPUT_FILE": bash_path(tmp_path / "selected-output.md"),
            "OPENCODE_POOL_MAX_CYCLES": "1",
            "OPENCODE_REVIEW_WORKDIR": bash_path(review_dir),
            "OPENCODE_RUN_TIMEOUT_SECONDS": "10",
            "OPENCODE_SOURCE_WORKDIR": bash_path(source_dir),
            "OPENCODE_TOTAL_RETRY_BUDGET_SECONDS": "30",
            "PATH": f"{bash_path(fake_bin)}:{env['PATH']}",
            "PR_NUMBER": "635",
            "RUNNER_TEMP": bash_path(runner_temp),
            "RUN_ATTEMPT": "1",
            "RUN_ID": "29189945378",
        }
    )
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [command, bash_path(RUNNER)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def run_central_fallback(
    tmp_path: Path,
    *,
    changed_files: list[str] | None = None,
) -> tuple[subprocess.CompletedProcess[str], Path, Path, Path]:
    """Run the bounded central fallback with deterministic local command fixtures."""
    command = bash_command()
    skip_if_windows_bash_is_unresponsive(command)
    source_dir = tmp_path / "source"
    review_dir = tmp_path / "review"
    runner_temp = tmp_path / "runner-temp"
    fake_bin = tmp_path / "bin"
    for path in (
        source_dir / ".codegraph",
        source_dir / "scripts" / "ci",
        source_dir / "tests",
        review_dir,
        runner_temp,
        fake_bin,
    ):
        path.mkdir(parents=True, exist_ok=True)

    (source_dir / ".codegraph" / "codegraph.db").write_bytes(b"indexed")
    (source_dir / "scripts" / "ci" / "run_opencode_review_model_pool.sh").write_text(
        "#!/usr/bin/env bash\ncap_model_run_timeout() { :; }\n",
        encoding="utf-8",
    )
    (source_dir / "scripts" / "ci" / "javascript_coverage_gate.py").write_text(
        "def normalize_coverage_path():\n    return None\n",
        encoding="utf-8",
    )
    (source_dir / "scripts" / "ci" / "strix_quick_gate.sh").write_text(
        "#!/usr/bin/env bash\nmode=160000\n",
        encoding="utf-8",
    )
    strix_test = source_dir / "scripts" / "ci" / "test_strix_quick_gate.sh"
    strix_test.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'test "${STRIX_TEST_CASE_FILTER:-}" = '
        "pull-request-target-gitlink-is-explicitly-skipped\n"
        "printf 'pull-request-target-gitlink-is-explicitly-skipped: PASS\\n'\n",
        encoding="utf-8",
    )
    strix_test.chmod(0o755)

    uv_log = tmp_path / "uv.log"
    fake_uv = fake_bin / "uv"
    fake_uv.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'printf \'%s\\n\' "$*" > "${FAKE_UV_LOG:?}"\n'
        "printf 'focused pytest: PASS\\n'\n",
        encoding="utf-8",
    )
    fake_uv.chmod(0o755)

    required_paths = [
        "scripts/ci/run_opencode_review_model_pool.sh",
        "scripts/ci/javascript_coverage_gate.py",
        "scripts/ci/strix_quick_gate.sh",
    ]
    changed_files_file = runner_temp / "opencode-changed-files.txt"
    changed_files_file.write_text(
        "\n".join(required_paths if changed_files is None else changed_files) + "\n",
        encoding="utf-8",
    )
    manifest_digest = seal_artifacts(
        runner_temp,
        head_sha="2" * 40,
        run_id="central-fallback-test",
        run_attempt="1",
        paths=(changed_files_file,),
    )
    output_file = tmp_path / "selected-output.json"
    github_output = tmp_path / "github-output.txt"
    env = os.environ.copy()
    for name in CENTRAL_FALLBACK_ENV:
        env.pop(name, None)
    env.update(
        {
            "CENTRAL_REVIEW_PROCESS_FALLBACK_ELIGIBLE": "true",
            "CENTRAL_REVIEW_PROCESS_FALLBACK_SCOPE_LABEL": "central-review-process",
            "FAKE_UV_LOG": bash_path(uv_log),
            "GITHUB_OUTPUT": bash_path(github_output),
            "GITHUB_WORKSPACE": bash_path(ROOT),
            "HEAD_SHA": "2" * 40,
            "OPENCODE_ARTIFACT_MANIFEST_SHA256": manifest_digest,
            "OPENCODE_CHANGED_FILES_FILE": bash_path(changed_files_file),
            "OPENCODE_MODEL_CANDIDATES": "",
            "OPENCODE_OUTPUT_FILE": bash_path(output_file),
            "OPENCODE_REQUIRE_ADVERSARIAL_VALIDATION": "true",
            "OPENCODE_REVIEW_WORKDIR": bash_path(review_dir),
            "OPENCODE_SOURCE_WORKDIR": bash_path(source_dir),
            "PATH": f"{bash_path(fake_bin)}:{env['PATH']}",
            "RUNNER_TEMP": bash_path(runner_temp),
            "RUN_ATTEMPT": "1",
            "RUN_ID": "central-fallback-test",
        }
    )
    result = subprocess.run(
        [command, bash_path(RUNNER)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    return result, output_file, github_output, uv_log


def test_central_fallback_cannot_approve_without_model_evidence(tmp_path: Path) -> None:
    """Passing PR-controlled probes cannot become a synthetic approval."""
    result, output_file, github_output, uv_log = run_central_fallback(tmp_path)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "model pool exhausted" in result.stdout.casefold()
    assert "review_status=exhausted" in github_output.read_text(encoding="utf-8")
    assert "review_status=success" not in github_output.read_text(encoding="utf-8")
    assert output_file.read_text(encoding="utf-8") == ""
    assert not uv_log.exists()


def test_central_fallback_fails_closed_when_required_scope_is_missing(
    tmp_path: Path,
) -> None:
    """A central-looking change cannot use the harness without every reviewed core path."""
    result, output_file, github_output, uv_log = run_central_fallback(
        tmp_path,
        changed_files=["scripts/ci/run_opencode_review_model_pool.sh"],
    )

    assert result.returncode == 1
    assert "model pool exhausted" in result.stdout.casefold()
    assert "review_status=exhausted" in github_output.read_text(encoding="utf-8")
    assert output_file.read_text(encoding="utf-8") == ""
    assert not uv_log.exists()


def test_failed_provider_logs_bounded_reason_and_redacts_credentials(
    tmp_path: Path,
) -> None:
    """Provider failures expose only a fixed class and bounded byte counts."""
    fake_bearer_token = "secret" + "-value"
    fake_openai_token = "sk" + "-dangerous123456"
    fake_github_token = "github" + "_pat_" + "ABCDEFGHIJKLMNOPQRSTUVWXYZ123456"
    result = run_failed_model(
        tmp_path,
        json_line=(
            '{"type":"error","error":{"name":"ProviderAuthError","data":'
            f'{{"message":"HTTP 401 authorization Bearer {fake_bearer_token}; '
            f'api_key={fake_openai_token}"' + "}}}"
        ),
        stderr_line=(
            f"request failed token={fake_github_token} because provider "
            "authentication was denied"
        ),
    )

    assert result.returncode == 1
    assert (
        "OpenCode provider failure metadata: class=authentication-or-permission"
        in result.stdout
    )
    assert "json-bytes=" in result.stdout
    assert "stderr-bytes=" in result.stdout
    assert "provider-controlled content suppressed" in result.stdout
    assert "ProviderAuthError" not in result.stdout
    assert "request failed" not in result.stdout
    assert fake_bearer_token not in result.stdout
    assert fake_openai_token not in result.stdout
    assert fake_github_token not in result.stdout
    assert fake_bearer_token not in result.stderr


def test_failed_provider_without_reason_logs_explicit_absence(tmp_path: Path) -> None:
    """An empty provider failure still states why no deeper reason is available."""
    result = run_failed_model(tmp_path)

    assert result.returncode == 1
    assert (
        "OpenCode provider failure metadata: class=no-provider-detail "
        "json-bytes=0 stderr-bytes=0; provider-controlled content suppressed."
    ) in result.stdout


def test_backoff_environment_rejects_recursive_arithmetic_injection(
    tmp_path: Path,
) -> None:
    """Do not evaluate attacker-controlled backoff text as Bash arithmetic."""
    marker = tmp_path / "arithmetic-injection-ran"
    result = run_failed_model(
        tmp_path,
        stderr_line="provider unavailable",
        extra_env={
            "OPENCODE_MODEL_ATTEMPTS": "2",
            "OPENCODE_BACKOFF_INITIAL_SECONDS": f"SECONDS[$(touch {marker})]",
            "OPENCODE_BACKOFF_MAX_SECONDS": "0",
        },
    )

    assert result.returncode != 0
    assert not marker.exists()


def test_configured_provider_retry_uses_bounded_backoff(tmp_path: Path) -> None:
    """A normal provider failure reaches the second configured attempt after backoff."""
    result = run_failed_model(
        tmp_path,
        stderr_line="provider unavailable",
        extra_env={
            "OPENCODE_MODEL_ATTEMPTS": "2",
            "OPENCODE_BACKOFF_INITIAL_SECONDS": "1",
            "OPENCODE_BACKOFF_MAX_SECONDS": "1",
        },
    )

    assert result.returncode == 1
    assert "Retrying OpenCode after exponential backoff of 1s." in result.stdout
    assert "attempt 2/2" in result.stdout
    assert "syntax error" not in result.stderr.casefold()


def secret_payload() -> tuple[str, tuple[str, ...]]:
    """Return a fake credential plus fragments used to detect partial disclosure."""
    parts = ("github", "_pat_", "THISMUSTNEVERLEAK123456789")
    return "".join(parts), parts


def assert_secret_absent(result: subprocess.CompletedProcess[str], secret: str) -> None:
    """Assert that raw, fragmented, and encoded credentials are absent from logs."""
    combined = result.stdout + result.stderr
    encoded = base64.b64encode(secret.encode()).decode()
    assert secret not in combined
    assert encoded not in combined
    for part in ("github_pat_", "THISMUSTNEVERLEAK123456789"):
        assert part not in combined


def test_success_without_session_suppresses_provider_artifact_content(
    tmp_path: Path,
) -> None:
    """A malformed successful run logs metadata without replaying its JSON stream."""
    secret, parts = secret_payload()
    encoded = base64.b64encode(secret.encode()).decode()
    result = run_failed_model(
        tmp_path,
        json_line=json.dumps(
            {"type": "text", "text": f"{parts[0]}{parts[1]}{parts[2]} {encoded}"}
        ),
        extra_env={"FAKE_OPENCODE_RUN_EXIT": "0"},
    )

    assert result.returncode == 1
    assert "JSON output did not include a session id" in result.stdout
    assert "kind=sessionless-json" in result.stdout
    assert "provider-controlled content suppressed" in result.stdout
    assert_secret_absent(result, secret)


def test_empty_assistant_export_suppresses_provider_artifact_content(
    tmp_path: Path,
) -> None:
    """An empty assistant export cannot echo arbitrary provider-controlled fields."""
    secret, _ = secret_payload()
    encoded = base64.b64encode(secret.encode()).decode()
    result = run_failed_model(
        tmp_path,
        json_line='{"type":"step_start","sessionID":"session-1"}',
        extra_env={
            "FAKE_OPENCODE_RUN_EXIT": "0",
            "FAKE_OPENCODE_EXPORT": json.dumps(
                {"messages": [], "provider_debug": f"{secret} {encoded}"}
            ),
        },
    )

    assert result.returncode == 1
    assert "session export did not include assistant text" in result.stdout
    assert "kind=assistant-empty-export" in result.stdout
    assert_secret_absent(result, secret)


def test_invalid_control_output_suppresses_assistant_content(tmp_path: Path) -> None:
    """Rejected assistant text is summarized without writing it to Actions logs."""
    secret, _ = secret_payload()
    encoded = base64.b64encode(secret.encode()).decode()
    result = run_failed_model(
        tmp_path,
        json_line='{"type":"step_start","sessionID":"session-1"}',
        extra_env={
            "FAKE_OPENCODE_RUN_EXIT": "0",
            "FAKE_OPENCODE_EXPORT": json.dumps(
                {
                    "messages": [
                        {
                            "info": {"role": "assistant"},
                            "parts": [
                                {
                                    "type": "text",
                                    "text": f"invalid control {secret} {encoded}",
                                }
                            ],
                        }
                    ]
                }
            ),
        },
    )

    assert result.returncode == 1
    assert "output did not include a valid control conclusion" in result.stdout
    assert "kind=invalid-control-output" in result.stdout
    assert_secret_absent(result, secret)


def test_runner_never_cats_rejected_provider_artifacts() -> None:
    """Provider-controlled rejection files are never replayed with direct cat calls."""
    runner = RUNNER.read_text(encoding="utf-8")
    for variable in (
        "opencode_json_file",
        "opencode_stderr_file",
        "opencode_export_file",
        "candidate_output_file",
    ):
        assert f'cat "${variable}"' not in runner


@pytest.mark.parametrize(
    "json_line",
    [
        (
            '{"type":"error","error":{"name":"ContextOverflowError","data":'
            '{"message":"Request body too large for gpt-5 model. Max size: 4000 tokens."}}}'
        ),
        (
            '{"type":"error","error":{"name":"ProviderQuotaError","data":'
            '{"message":"insufficient_quota: request rejected"}}}'
        ),
    ],
    ids=["context-overflow", "insufficient-quota"],
)
def test_fatal_provider_error_kills_hung_opencode_run_early(
    tmp_path: Path, json_line: str
) -> None:
    """A hung opencode process dies seconds after logging a fatal provider error."""
    start = time.monotonic()
    result = run_failed_model(
        tmp_path,
        json_line=json_line,
        extra_env={
            "FAKE_OPENCODE_HANG_SECONDS": "120",
            "OPENCODE_RUN_TIMEOUT_SECONDS": "120",
            "OPENCODE_TOTAL_RETRY_BUDGET_SECONDS": "240",
        },
    )
    elapsed = time.monotonic() - start

    assert result.returncode == 1
    assert "logged a fatal provider error while still running" in result.stdout
    assert "skipping remaining attempts for this model" in result.stdout
    assert elapsed < 25


def test_model_text_quoting_error_signatures_does_not_kill_run(tmp_path: Path) -> None:
    """Model prose mentioning fatal signatures never kills a healthy streaming run."""
    result = run_failed_model(
        tmp_path,
        json_line=(
            '{"type":"text","text":"This PR hardens ContextOverflowError and '
            'context window handling in the model pool."}'
        ),
        extra_env={"FAKE_OPENCODE_HANG_SECONDS": "4"},
    )

    assert result.returncode == 1
    assert "logged a fatal provider error while still running" not in result.stdout


def test_delisted_openrouter_model_error_kills_hung_run_early(tmp_path: Path) -> None:
    """A delisted pinned OpenRouter model dies seconds after a model-unavailable error."""
    start = time.monotonic()
    result = run_failed_model(
        tmp_path,
        json_line=(
            '{"type":"error","error":{"name":"ProviderModelNotFoundError","data":'
            '{"message":"No endpoints found for nvidia/nemotron-3-ultra-550b-a55b:free."}}}'
        ),
        model_candidates="openrouter/nvidia/nemotron-3-ultra-550b-a55b:free",
        extra_env={
            "OPENROUTER_API_KEY": "fake-openrouter-key",
            "FAKE_OPENCODE_HANG_SECONDS": "120",
            "OPENCODE_RUN_TIMEOUT_SECONDS": "120",
            "OPENCODE_TOTAL_RETRY_BUDGET_SECONDS": "240",
        },
    )
    elapsed = time.monotonic() - start

    assert result.returncode == 1
    assert "logged a fatal provider error while still running" in result.stdout
    assert "skipping remaining attempts for this model" in result.stdout
    assert "class=model-unavailable" in result.stdout
    assert elapsed < 25


def test_credit_exhausted_402_ends_pool_without_further_spend(tmp_path: Path) -> None:
    """A paid candidate hitting HTTP 402 is dead for the run instead of cycling."""
    start = time.monotonic()
    result = run_failed_model(
        tmp_path,
        json_line=(
            '{"type":"error","error":{"name":"AI_APICallError","data":'
            '{"message":"Insufficient credits. Add more using '
            'https://openrouter.ai/settings/credits","statusCode":402}}}'
        ),
        model_candidates="openrouter/deepseek/deepseek-v3.2",
        extra_env={
            "OPENROUTER_API_KEY": "fake-openrouter-key",
            "OPENCODE_POOL_MAX_CYCLES": "0",
        },
    )
    elapsed = time.monotonic() - start

    assert result.returncode == 1
    assert "provider credits are exhausted" in result.stdout
    assert "marking this candidate failed for the rest of the run" in result.stdout
    assert "Every OpenCode model candidate is marked failed for this run" in result.stdout
    assert "class=credit-exhausted" in result.stdout
    assert "Restarting OpenCode model pool" not in result.stdout
    assert elapsed < 20


def test_invalid_control_output_cap_marks_candidate_failed(tmp_path: Path) -> None:
    """Repeated control-rejected output stops retrying at the cap, not the budget."""
    result = run_failed_model(
        tmp_path,
        json_line='{"type":"step_start","sessionID":"session-1"}',
        extra_env={
            "FAKE_OPENCODE_RUN_EXIT": "0",
            "FAKE_OPENCODE_EXPORT": json.dumps(
                {
                    "messages": [
                        {
                            "info": {"role": "assistant"},
                            "parts": [
                                {"type": "text", "text": "not a control conclusion"}
                            ],
                        }
                    ]
                }
            ),
            "OPENCODE_MODEL_ATTEMPTS": "3",
            "OPENCODE_INVALID_CONTROL_OUTPUT_CAP": "2",
            "OPENCODE_BACKOFF_INITIAL_SECONDS": "1",
            "OPENCODE_POOL_MAX_CYCLES": "0",
        },
    )

    assert result.returncode == 1
    assert "produced 2 control-rejected outputs" in result.stdout
    assert "marking this candidate failed for the rest of the run" in result.stdout
    assert "Every OpenCode model candidate is marked failed for this run" in result.stdout
    assert "attempt 3/3" not in result.stdout


def test_attempt_ceiling_bounds_provider_spend(tmp_path: Path) -> None:
    """The per-run attempt ceiling ends the pool before the retry budget elapses."""
    result = run_failed_model(
        tmp_path,
        extra_env={
            "OPENCODE_MODEL_ATTEMPTS": "3",
            "OPENCODE_POOL_MAX_TOTAL_ATTEMPTS": "2",
            "OPENCODE_BACKOFF_INITIAL_SECONDS": "1",
            "OPENCODE_POOL_MAX_CYCLES": "0",
        },
    )

    assert result.returncode == 1
    assert (
        "reached the per-run provider attempt ceiling of 2 attempts" in result.stdout
    )
    assert "attempt 3/3" not in result.stdout


def test_dynamic_review_cadence_uses_small_change_timeout(tmp_path: Path) -> None:
    """Small PRs fail through hung/unavailable providers quickly with a visible budget reason."""
    result = run_failed_model(
        tmp_path,
        changed_files=["pyproject.toml", "uv.lock"],
        extra_env={
            "OPENCODE_DYNAMIC_REVIEW_CADENCE": "true",
            "OPENCODE_RUN_TIMEOUT_SECONDS": "99",
            "OPENCODE_TOTAL_RETRY_BUDGET_SECONDS": "99",
            "OPENCODE_SMALL_CHANGE_RUN_TIMEOUT_SECONDS": "7",
            "OPENCODE_SMALL_CHANGE_TOTAL_BUDGET_SECONDS": "11",
            "OPENCODE_DYNAMIC_MAX_CYCLES": "1",
        },
    )

    assert result.returncode == 1
    assert (
        "OpenCode dynamic review cadence selected 7s per attempt and 11s total budget "
        "for 2 changed file(s); max-cycles=1."
    ) in result.stdout
    attempt_budget = re.search(
        r"OpenCode github-models/openai/gpt-5 attempt 1/1 using (\d+)s run timeout "
        r"with (\d+)s retry budget remaining\.",
        result.stdout,
    )
    assert attempt_budget is not None
    run_timeout, remaining_budget = map(int, attempt_budget.groups())
    assert 1 <= run_timeout <= 7
    assert run_timeout <= remaining_budget <= 11
    assert "retry budget remaining." in result.stdout


def test_dynamic_review_cadence_caps_large_change_queue_budget(tmp_path: Path) -> None:
    """Large PR cadence caps queue time without converting unlimited cycles to one cycle."""
    changed_files = [f"backend/changed_{index}.py" for index in range(21)]
    result = run_failed_model(
        tmp_path,
        changed_files=changed_files,
        extra_env={
            "OPENCODE_DYNAMIC_REVIEW_CADENCE": "true",
            "OPENCODE_DYNAMIC_MAX_CYCLES": "0",
            "OPENCODE_DYNAMIC_TOTAL_BUDGET_CAP_SECONDS": "1",
            "OPENCODE_LARGE_CHANGE_RUN_TIMEOUT_SECONDS": "3600",
            "OPENCODE_LARGE_CHANGE_TOTAL_BUDGET_SECONDS": "7200",
            "OPENCODE_POOL_CYCLE_SLEEP_SECONDS": "0",
        },
        model_candidates="github-models/deepseek/deepseek-v3-0324",
    )

    assert result.returncode == 1
    # Default dynamic timeout cap is now 7200s (two-hour NIM allowance),
    # so per-attempt 3600s is not reduced; only the total budget cap (1s) applies.
    assert (
        "OpenCode dynamic review cadence queue cap applied: per-attempt 3600s -> 3600s, "
        "total budget 7200s -> 1s, max-cycles 0 -> 0"
    ) in result.stdout or (
        "total budget 7200s -> 1s" in result.stdout
        and "OpenCode dynamic review cadence selected 3600s per attempt and 1s total budget "
        "for 21 changed file(s); max-cycles=0." in result.stdout
    )
    assert (
        "OpenCode dynamic review cadence selected 3600s per attempt and 1s total budget "
        "for 21 changed file(s); max-cycles=0."
    ) in result.stdout
    assert "OpenCode model pool reached configured max cycle count" not in result.stdout
    assert (
        "OpenCode model pool exhausted before producing a valid control conclusion."
        in result.stdout
    )


def test_github_gpt5_runtime_cap_preserves_queue_budget(tmp_path: Path) -> None:
    """Known constrained GitHub GPT-5 endpoints cannot consume a full cadence slot."""
    result = run_failed_model(
        tmp_path,
        extra_env={
            "OPENCODE_GITHUB_GPT5_RUN_TIMEOUT_SECONDS": "3",
            "OPENCODE_RUN_TIMEOUT_SECONDS": "9",
        },
    )

    assert result.returncode == 1
    assert (
        "OpenCode github-models/openai/gpt-5 runtime cap selected 3s instead of 9s "
        "because this provider has a bounded failover window."
    ) in result.stdout
    attempt_budget = re.search(
        r"OpenCode github-models/openai/gpt-5 attempt 1/1 using (\d+)s run timeout "
        r"with (\d+)s retry budget remaining\.",
        result.stdout,
    )
    assert attempt_budget is not None
    run_timeout, remaining_budget = map(int, attempt_budget.groups())
    assert run_timeout == 3
    assert run_timeout <= remaining_budget <= 30


def test_free_provider_runtime_cap_preserves_queue_budget(tmp_path: Path) -> None:
    """A stalled free provider cannot consume a full paid-provider cadence slot."""
    result = run_failed_model(
        tmp_path,
        extra_env={
            "OPENCODE_FREE_RUN_TIMEOUT_SECONDS": "3",
            "OPENCODE_RUN_TIMEOUT_SECONDS": "9",
        },
        model_candidates="opencode-free/nemotron-3-ultra-free",
    )

    assert result.returncode == 1
    assert (
        "OpenCode opencode-free/nemotron-3-ultra-free runtime cap selected 3s "
        "instead of 9s because this provider has a bounded failover window."
    ) in result.stdout


def test_nvidia_nim_candidate_requires_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """NVIDIA NIM is skipped cleanly when its scoped credential is unavailable."""
    monkeypatch.setenv("NVIDIA_NIM_API_KEY", "ambient-scoped-key")
    monkeypatch.setenv("NVIDIA_API_KEY", "ambient-provider-key")
    result = run_failed_model(
        tmp_path,
        extra_env={"NVIDIA_API_KEY": "legacy-provider-key"},
        model_candidates="nvidia-nim/nvidia/nemotron-3-ultra-550b-a55b",
    )

    assert result.returncode == 1
    assert "scoped NVIDIA_NIM_API_KEY is not configured" in result.stdout
    assert "attempt 1/1" not in result.stdout


def test_nvidia_nim_runtime_cap_preserves_queue_budget(tmp_path: Path) -> None:
    """A stalled hosted NIM cannot consume a full paid-provider cadence slot."""
    result = run_failed_model(
        tmp_path,
        extra_env={
            "NVIDIA_NIM_API_KEY": "fake-nvidia-key",
            "OPENCODE_NVIDIA_NIM_RUN_TIMEOUT_SECONDS": "3",
            "OPENCODE_RUN_TIMEOUT_SECONDS": "9",
        },
        model_candidates="nvidia-nim/nvidia/nemotron-3-ultra-550b-a55b",
    )

    assert result.returncode == 1
    assert (
        "OpenCode nvidia-nim/nvidia/nemotron-3-ultra-550b-a55b runtime cap "
        "selected 3s instead of 9s because this provider has a bounded failover window."
    ) in result.stdout


def test_nvidia_nim_combined_budget_preserves_fallback_attempt(
    tmp_path: Path,
) -> None:
    """Timed-out NIM candidates cannot consume the fallback provider budget."""
    result = run_failed_model(
        tmp_path,
        extra_env={
            "FAKE_OPENCODE_HANG_SECONDS": "2",
            "NVIDIA_NIM_API_KEY": "fake-nvidia-key",
            "OPENCODE_FREE_RUN_TIMEOUT_SECONDS": "1",
            "OPENCODE_NVIDIA_NIM_RUN_TIMEOUT_SECONDS": "1",
            "OPENCODE_NVIDIA_NIM_TOTAL_BUDGET_SECONDS": "1",
            "OPENCODE_RUN_TIMEOUT_SECONDS": "5",
            # Keep the outer pool deadline well above the three one-second
            # attempt caps so scheduler load cannot turn this into a
            # global-deadline boundary test.
            "OPENCODE_TOTAL_RETRY_BUDGET_SECONDS": "15",
        },
        model_candidates=(
            "nvidia-nim/nvidia/nemotron-3-ultra-550b-a55b "
            "nvidia-nim/nvidia/nemotron-3-super-120b-a12b "
            "opencode-free/nemotron-3-ultra-free"
        ),
    )

    assert result.returncode == 1
    assert "OpenCode NVIDIA NIM combined runtime used" in result.stdout
    assert (
        "Skipping OpenCode nvidia-nim/nvidia/nemotron-3-super-120b-a12b "
        "because the NVIDIA NIM combined runtime budget of 1s is exhausted"
        in result.stdout
    )
    assert "OpenCode opencode-free/nemotron-3-ultra-free attempt 1/2" in result.stdout
    assert "schema-repair attempt 2/2" not in result.stdout


def test_github_models_openai_prompt_references_evidence_without_inlining(
    tmp_path: Path,
) -> None:
    """Small-request GitHub Models OpenAI candidates keep evidence as files."""
    prompt_capture = tmp_path / "captured-prompt.md"
    evidence_excerpt = "UNIQUE_CURRENT_HEAD_EVIDENCE_PACKET"

    result = run_failed_model(
        tmp_path,
        evidence_excerpt=evidence_excerpt,
        prompt_capture=prompt_capture,
    )

    assert result.returncode == 1
    prompt = prompt_capture.read_text(encoding="utf-8")
    assert evidence_excerpt not in prompt
    assert "Evidence excerpt omitted for `github-models/openai/gpt-5`" in prompt
    assert "bounded-review-evidence.md" in prompt
    assert "bounded-review-evidence-excerpt.md" in prompt


def test_deepseek_prompt_still_inlines_bounded_evidence_excerpt(tmp_path: Path) -> None:
    """Large-context DeepSeek candidates retain the current-head prompt packet."""
    prompt_capture = tmp_path / "captured-prompt.md"
    evidence_excerpt = "UNIQUE_DEEPSEEK_INLINE_EVIDENCE_PACKET"

    result = run_failed_model(
        tmp_path,
        evidence_excerpt=evidence_excerpt,
        model_candidates="github-models/deepseek/deepseek-v3-0324",
        prompt_capture=prompt_capture,
    )

    assert result.returncode == 1
    prompt = prompt_capture.read_text(encoding="utf-8")
    assert evidence_excerpt in prompt
    assert "Evidence excerpt omitted" not in prompt
    assert f'{{"head_sha":"{"1" * 40}"' not in prompt
    assert "Do not quote, repeat, or emit a schema example" in prompt


def test_free_provider_gets_one_bounded_schema_repair_attempt(
    tmp_path: Path,
) -> None:
    """A responsive free model can correct schema once without increasing paid retries."""
    prompt_capture = tmp_path / "captured-repair-prompt.md"
    result = run_failed_model(
        tmp_path,
        json_line='{"type":"step_start","sessionID":"session-1"}',
        prompt_capture=prompt_capture,
        model_candidates="opencode-free/nemotron-3-ultra-free",
        extra_env={
            "FAKE_OPENCODE_RUN_EXIT": "0",
            "FAKE_OPENCODE_EXPORT": json.dumps(
                {
                    "messages": [
                        {
                            "info": {"role": "assistant"},
                            "parts": [
                                {"type": "text", "text": "not a control conclusion"}
                            ],
                        }
                    ]
                }
            ),
            "OPENCODE_BACKOFF_INITIAL_SECONDS": "9",
        },
    )

    assert result.returncode == 1
    assert "attempt 1/2" in result.stdout
    assert "schema-repair attempt 2/2" in result.stdout
    assert "attempt 2/2" in result.stdout
    assert "exponential backoff" not in result.stdout
    repair_prompt = prompt_capture.read_text(encoding="utf-8")
    assert "failed the control schema" in repair_prompt
    assert "exactly one sentinel and exactly one current-run JSON control object" in repair_prompt


def test_paid_provider_does_not_gain_an_implicit_schema_repair_attempt(
    tmp_path: Path,
) -> None:
    """The free-model correction path cannot double paid-provider requests."""
    result = run_failed_model(
        tmp_path,
        json_line='{"type":"step_start","sessionID":"session-1"}',
        model_candidates="openrouter/deepseek/deepseek-v3.2",
        extra_env={
            "FAKE_OPENCODE_RUN_EXIT": "0",
            "FAKE_OPENCODE_EXPORT": json.dumps(
                {
                    "messages": [
                        {
                            "info": {"role": "assistant"},
                            "parts": [
                                {"type": "text", "text": "not a control conclusion"}
                            ],
                        }
                    ]
                }
            ),
            "OPENROUTER_API_KEY": "fake-openrouter-key",
        },
    )

    assert result.returncode == 1
    assert "attempt 1/1" in result.stdout
    assert "schema-repair attempt" not in result.stdout
    assert "attempt 2/" not in result.stdout
