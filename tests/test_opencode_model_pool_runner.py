"""Behavioral tests for bounded OpenCode model-pool failure diagnostics."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "ci" / "run_opencode_review_model_pool.sh"


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
        pytest.skip("Git Bash did not respond to a smoke command within 5 seconds on Windows")
    if result.returncode != 0:
        pytest.skip(f"Git Bash smoke command failed on Windows: {result.stderr.strip()}")


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
    evidence_file = tmp_path / "evidence.md"
    evidence_file.write_text("bounded current-head evidence\n", encoding="utf-8")
    changed_files_file = tmp_path / "changed-files.txt"
    if changed_files is not None:
        changed_files_file.write_text("\n".join(changed_files) + "\n", encoding="utf-8")
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
        "if [ \"${1:-}\" = run ]; then\n"
        "  [ -z \"${FAKE_OPENCODE_PROMPT_CAPTURE:-}\" ] || printf '%s\\n' \"$2\" > \"$FAKE_OPENCODE_PROMPT_CAPTURE\"\n"
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
            "FAKE_OPENCODE_PROMPT_CAPTURE": bash_path(prompt_capture) if prompt_capture else "",
            "FAKE_OPENCODE_STDERR": stderr_line,
            "GITHUB_OUTPUT": bash_path(github_output),
            "GITHUB_WORKSPACE": bash_path(ROOT),
            "HEAD_SHA": "1" * 40,
            "OPENCODE_CHANGED_FILES_FILE": bash_path(changed_files_file),
            "OPENCODE_EVIDENCE_FILE": bash_path(evidence_file),
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


def test_failed_provider_logs_bounded_reason_and_redacts_credentials(tmp_path: Path) -> None:
    """Provider JSON/stderr reasons remain useful without leaking credentials."""
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
    assert "OpenCode provider failure detail: json: ProviderAuthError: HTTP 401" in result.stdout
    assert "OpenCode provider failure detail: stderr: request failed" in result.stdout
    assert result.stdout.count("[REDACTED]") >= 3
    assert fake_bearer_token not in result.stdout
    assert fake_openai_token not in result.stdout
    assert fake_github_token not in result.stdout
    assert fake_bearer_token not in result.stderr


def test_failed_provider_without_reason_logs_explicit_absence(tmp_path: Path) -> None:
    """An empty provider failure still states why no deeper reason is available."""
    result = run_failed_model(tmp_path)

    assert result.returncode == 1
    assert (
        "OpenCode provider failure supplied no structured JSON or stderr reason "
        "(json-bytes=0, stderr-bytes=0)."
    ) in result.stdout


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


def test_github_models_openai_prompt_references_evidence_without_inlining(tmp_path: Path) -> None:
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
