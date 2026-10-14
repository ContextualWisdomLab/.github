"""End-to-end contract for OpenCode's fail-closed uncertainty transport."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "ci" / "run_opencode_review_model_pool.sh"
NORMALIZER = ROOT / "scripts" / "ci" / "opencode_review_normalize_output.py"
GATE = ROOT / "scripts" / "ci" / "opencode_review_approve_gate.sh"
HEAD_SHA = "1" * 40
RUN_ID = "424242"
RUN_ATTEMPT = "1"
MARKER = (
    f"<!-- opencode-review-needs-info head_sha={HEAD_SHA} "
    f"run_id={RUN_ID} run_attempt={RUN_ATTEMPT} -->"
)
SENTINEL = (
    f"<!-- opencode-review-gate head_sha={HEAD_SHA} "
    f"run_id={RUN_ID} run_attempt={RUN_ATTEMPT} -->"
)


def _bash() -> str:
    command = shutil.which("bash")
    if command is None:
        pytest.skip("bash is required for the OpenCode transport contract")
    return command


def test_needs_info_survives_model_pool_normalizer_and_terminal_gate(
    tmp_path: Path,
) -> None:
    """A valid current-run non-conclusion must not be retried or rewritten."""
    review_dir = tmp_path / "review"
    source_dir = tmp_path / "source"
    runner_temp = tmp_path / "runner-temp"
    fake_bin = tmp_path / "bin"
    for path in (review_dir, source_dir, runner_temp, fake_bin):
        path.mkdir()

    shutil.copy2(ROOT / "opencode.jsonc", review_dir / "opencode.jsonc")
    evidence = runner_temp / "opencode-review-evidence.md"
    evidence.write_text("bounded current-head evidence\n", encoding="utf-8")
    selected = tmp_path / "selected-output.md"
    github_output = tmp_path / "github-output.txt"
    model_output = f"{SENTINEL}\n{MARKER}\n"

    fake_opencode = fake_bin / "opencode"
    fake_opencode.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "if [ \"${1:-}\" = run ]; then\n"
        f"  printf '%s\\n' '{json.dumps({'type': 'step_start', 'sessionID': 'session-1'})}'\n"
        "  exit 0\n"
        "fi\n"
        "if [ \"${1:-}\" = export ]; then\n"
        "  printf '%s\\n' \"$FAKE_OPENCODE_EXPORT\"\n"
        "  exit 0\n"
        "fi\n"
        "exit 2\n",
        encoding="utf-8",
    )
    fake_opencode.chmod(0o755)
    export_payload = json.dumps(
        {
            "messages": [
                {
                    "info": {"role": "assistant"},
                    "parts": [{"type": "text", "text": model_output}],
                }
            ]
        }
    )

    env = os.environ.copy()
    env.update(
        {
            "FAKE_OPENCODE_EXPORT": export_payload,
            "GITHUB_OUTPUT": str(github_output),
            "GITHUB_WORKSPACE": str(ROOT),
            "HEAD_SHA": HEAD_SHA,
            "OPENCODE_EVIDENCE_FILE": str(evidence),
            "OPENCODE_MODEL_ATTEMPTS": "1",
            "OPENCODE_MODEL_CANDIDATES": "github-models/openai/gpt-5",
            "OPENCODE_OUTPUT_FILE": str(selected),
            "OPENCODE_POOL_MAX_CYCLES": "1",
            "OPENCODE_REVIEW_WORKDIR": str(review_dir),
            "OPENCODE_SOURCE_WORKDIR": str(source_dir),
            "PATH": f"{fake_bin}:{env['PATH']}",
            "PR_NUMBER": "1655",
            "RUNNER_TEMP": str(runner_temp),
            "RUN_ATTEMPT": RUN_ATTEMPT,
            "RUN_ID": RUN_ID,
        }
    )

    completed = subprocess.run(
        [_bash(), str(RUNNER)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    # ``jq -r`` (scripts/ci/run_opencode_review_model_pool.sh's extraction step)
    # always appends one trailing newline after printing the assistant text
    # value; since ``model_output`` itself already ends with ``\n``, the file
    # legitimately carries one extra trailing blank line. This is harmless —
    # both the bash pool's own ``is_current_run_needs_info_output`` check and
    # the Python normalizer below strip blank lines before comparing content.
    assert selected.read_text(encoding="utf-8") == model_output + "\n"
    outputs = github_output.read_text(encoding="utf-8")
    assert "review_status=no_conclusion" in outputs
    assert "review_status=success" not in outputs

    normalized = subprocess.run(
        [
            sys.executable,
            str(NORMALIZER),
            HEAD_SHA,
            RUN_ID,
            RUN_ATTEMPT,
            str(selected),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert normalized.returncode == 0, normalized.stdout + normalized.stderr
    # The Python normalizer's needs-info fast path (``main()`` in
    # opencode_review_normalize_output.py) returns before touching the file,
    # so the pre-existing jq trailing blank line (see above) survives here too.
    assert selected.read_text(encoding="utf-8") == model_output + "\n"

    gate = subprocess.run(
        [_bash(), str(GATE), HEAD_SHA, RUN_ID, RUN_ATTEMPT, str(selected)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert gate.returncode == 4
    assert gate.stdout.strip() == "NO_CONCLUSION"
