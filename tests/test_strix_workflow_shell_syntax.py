"""Validate Strix workflow run blocks as the shell Actions will execute."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
STRIX_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "strix.yml"


def _extract_run_block(workflow_text: str, step_name: str) -> str:
    """Return one dedented ``run: |`` script, matching GitHub Actions stripping."""

    lines = workflow_text.splitlines()
    step_index = next(
        index
        for index, line in enumerate(lines)
        if line.strip() == f"- name: {step_name}"
    )
    run_index = next(
        index
        for index in range(step_index + 1, len(lines))
        if lines[index].strip() == "run: |"
    )
    run_indent = len(lines[run_index]) - len(lines[run_index].lstrip())
    block_lines = []
    for line in lines[run_index + 1 :]:
        if line.strip() and len(line) - len(line.lstrip()) <= run_indent:
            break
        block_lines.append(line[run_indent + 2 :] if len(line) >= run_indent + 2 else "")
    return "\n".join(block_lines) + "\n"


def _python_c_source(run_block: str) -> str:
    """Return the first ``python3 -c`` program from a run block."""

    marker = "python3 -c '\n"
    start = run_block.index(marker) + len(marker)
    end = run_block.index("\n'", start)
    return run_block[start:end]


def test_strix_workflow_has_no_indented_python_heredoc() -> None:
    """Keep inline Python in quoted -c programs so raw bash -n is not a false fail."""

    workflow = STRIX_WORKFLOW.read_text(encoding="utf-8")
    assert "<<'PY'" not in workflow
    assert '<<"PY"' not in workflow
    assert "<<PY" not in workflow


def test_strix_inline_python_run_blocks_are_valid_bash() -> None:
    """bash -n the Actions-stripped scripts that used to be unclosed heredocs."""

    if sys.platform == "win32":
        return
    bash = shutil.which("bash")
    if bash is None:
        return

    workflow = STRIX_WORKFLOW.read_text(encoding="utf-8")
    for step_name in (
        "Resolve trusted Strix source ref",
        "Install Strix",
        "Prepare Vertex AI credentials",
        "Run Strix (quick)",
    ):
        script = _extract_run_block(workflow, step_name)
        result = subprocess.run(
            [bash, "-n"],
            input=script,
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, f"{step_name}: {result.stderr}"


def test_strix_trusted_source_resolver_emits_workflow_repository_and_ref() -> None:
    """Execute the production trusted-source -c program against live-shaped context."""

    workflow = STRIX_WORKFLOW.read_text(encoding="utf-8")
    script = _extract_run_block(workflow, "Resolve trusted Strix source ref")
    source = _python_c_source(script)
    env = os.environ.copy()
    env["JOB_CONTEXT_JSON"] = json.dumps(
        {
            "workflow_repository": "ContextualWisdomLab/.github",
            "workflow_sha": "0123456789abcdef0123456789abcdef01234567",
        }
    )
    env["GITHUB_CONTEXT_JSON"] = "{}"
    completed = subprocess.run(
        [sys.executable, "-c", source],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert completed.returncode == 0, completed.stderr
    assert "repository=ContextualWisdomLab/.github" in completed.stdout
    assert "ref=0123456789abcdef0123456789abcdef01234567" in completed.stdout


def test_strix_executable_hash_snippet_matches_sha256_of_real_bytes() -> None:
    """Hash a real file with the production Install Strix python3 -c snippet."""

    workflow = STRIX_WORKFLOW.read_text(encoding="utf-8")
    script = _extract_run_block(workflow, "Install Strix")
    source = _python_c_source(script)
    payload = b"strix-executable-identity\n"
    with tempfile.NamedTemporaryFile(prefix="strix-exe-", delete=False) as handle:
        handle.write(payload)
        path = handle.name
    try:
        completed = subprocess.run(
            [sys.executable, "-c", source, path],
            check=False,
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0, completed.stderr
        assert completed.stdout.strip() == hashlib.sha256(payload).hexdigest()
    finally:
        os.unlink(path)


def test_strix_vertex_credential_snippet_exports_project_id() -> None:
    """Parse a real service-account JSON object with the production -c snippet."""

    workflow = STRIX_WORKFLOW.read_text(encoding="utf-8")
    script = _extract_run_block(workflow, "Prepare Vertex AI credentials")
    source = _python_c_source(script)
    with tempfile.NamedTemporaryFile(
        prefix="gcp-sa-",
        suffix=".json",
        delete=False,
        mode="w",
        encoding="utf-8",
    ) as handle:
        json.dump({"project_id": "vertex_scan_project", "type": "service_account"}, handle)
        path = handle.name
    try:
        completed = subprocess.run(
            [sys.executable, "-c", source, path],
            check=False,
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0, completed.stderr
        assert f"GOOGLE_APPLICATION_CREDENTIALS={path}" in completed.stdout
        assert "VERTEXAI_PROJECT=vertex_scan_project" in completed.stdout
    finally:
        os.unlink(path)
