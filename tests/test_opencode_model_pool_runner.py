"""Behavioral tests for bounded OpenCode model-pool failure diagnostics."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "ci" / "run_opencode_review_model_pool.sh"


def run_failed_model(
    tmp_path: Path,
    *,
    json_line: str = "",
    stderr_line: str = "",
) -> subprocess.CompletedProcess[str]:
    """Run one fake provider failure through the real model-pool launcher."""
    review_dir = tmp_path / "review"
    source_dir = tmp_path / "source"
    runner_temp = tmp_path / "runner-temp"
    fake_bin = tmp_path / "bin"
    for path in (review_dir, source_dir, runner_temp, fake_bin):
        path.mkdir()
    shutil.copy2(ROOT / "opencode.jsonc", review_dir / "opencode.jsonc")
    evidence_file = tmp_path / "evidence.md"
    evidence_file.write_text("bounded current-head evidence\n", encoding="utf-8")
    fake_opencode = fake_bin / "opencode"
    fake_opencode.write_text(
        "#!/usr/bin/env bash\n"
        "if [ \"${1:-}\" = run ]; then\n"
        "  [ -z \"${FAKE_OPENCODE_JSON:-}\" ] || printf '%s\\n' \"$FAKE_OPENCODE_JSON\"\n"
        "  [ -z \"${FAKE_OPENCODE_STDERR:-}\" ] || printf '%s\\n' \"$FAKE_OPENCODE_STDERR\" >&2\n"
        "  exit 1\n"
        "fi\n"
        "printf 'unexpected fake opencode command: %s\\n' \"$*\" >&2\n"
        "exit 2\n",
        encoding="utf-8",
    )
    fake_opencode.chmod(0o755)
    github_output = tmp_path / "github-output.txt"
    env = os.environ.copy()
    env.update(
        {
            "FAKE_OPENCODE_JSON": json_line,
            "FAKE_OPENCODE_STDERR": stderr_line,
            "GITHUB_OUTPUT": str(github_output),
            "GITHUB_WORKSPACE": str(ROOT),
            "HEAD_SHA": "1" * 40,
            "OPENCODE_EVIDENCE_FILE": str(evidence_file),
            "OPENCODE_MODEL_ATTEMPTS": "1",
            "OPENCODE_MODEL_CANDIDATES": "github-models/openai/gpt-5",
            "OPENCODE_OUTPUT_FILE": str(tmp_path / "selected-output.md"),
            "OPENCODE_POOL_MAX_CYCLES": "1",
            "OPENCODE_REVIEW_WORKDIR": str(review_dir),
            "OPENCODE_RUN_TIMEOUT_SECONDS": "3",
            "OPENCODE_SOURCE_WORKDIR": str(source_dir),
            "OPENCODE_TOTAL_RETRY_BUDGET_SECONDS": "3",
            "PATH": f"{fake_bin}{os.pathsep}{env['PATH']}",
            "PR_NUMBER": "635",
            "RUNNER_TEMP": str(runner_temp),
            "RUN_ATTEMPT": "1",
            "RUN_ID": "29189945378",
        }
    )
    return subprocess.run(
        ["bash", str(RUNNER)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )


def test_failed_provider_logs_bounded_reason_and_redacts_credentials(tmp_path: Path) -> None:
    """Provider JSON/stderr reasons remain useful without leaking credentials."""
    result = run_failed_model(
        tmp_path,
        json_line=(
            '{"type":"error","error":{"name":"ProviderAuthError","data":'
            '{"message":"HTTP 401 authorization Bearer secret-value; '
            'api_key=sk-dangerous123456"}}}'
        ),
        stderr_line=(
            "request failed token=github_pat_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456 "
            "because provider authentication was denied"
        ),
    )

    assert result.returncode == 1
    assert "OpenCode provider failure detail: json: ProviderAuthError: HTTP 401" in result.stdout
    assert "OpenCode provider failure detail: stderr: request failed" in result.stdout
    assert result.stdout.count("[REDACTED]") >= 3
    assert "secret-value" not in result.stdout
    assert "sk-dangerous123456" not in result.stdout
    assert "github_pat_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456" not in result.stdout
    assert "secret-value" not in result.stderr


def test_failed_provider_without_reason_logs_explicit_absence(tmp_path: Path) -> None:
    """An empty provider failure still states why no deeper reason is available."""
    result = run_failed_model(tmp_path)

    assert result.returncode == 1
    assert (
        "OpenCode provider failure supplied no structured JSON or stderr reason "
        "(json-bytes=0, stderr-bytes=0)."
    ) in result.stdout
