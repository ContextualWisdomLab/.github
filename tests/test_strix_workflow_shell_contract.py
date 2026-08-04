"""Executable contracts for the Strix GitHub Actions shell wrapper."""

from __future__ import annotations

import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
BASH = shutil.which("bash")


def _workflow_text(name: str) -> str:
    """Return one repository workflow as UTF-8 text."""
    return (REPO_ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")


def _workflow_step(workflow: str, name: str) -> str:
    """Extract one named workflow step without interpreting its YAML body."""
    marker = f"      - name: {name}\n"
    start = workflow.index(marker)
    try:
        end = workflow.index("\n      - name:", start + len(marker))
    except ValueError:
        end = len(workflow)
    return workflow[start:end]


def _run_script(step: str) -> str:
    """Extract and dedent the literal run block from a workflow step."""
    lines = step.splitlines()
    run_index = next(
        (index for index, line in enumerate(lines) if line.lstrip() == "run: |"),
        None,
    )
    assert run_index is not None, "workflow step must contain a literal run block"

    run_line = lines[run_index]
    body_indent = f"{run_line[: len(run_line) - len(run_line.lstrip())]}  "
    body = lines[run_index + 1 :]
    assert body, "workflow run block must not be empty"
    assert all(not line or line.startswith(body_indent) for line in body)
    return textwrap.dedent("\n".join(body))


@pytest.mark.skipif(BASH is None, reason="bash is required for workflow shell contracts")
def test_strix_wrapper_propagates_exact_nonzero_gate_status(tmp_path: Path) -> None:
    """Preserve PIPESTATUS[0] under the same bash flags used by Actions."""
    assert BASH is not None
    workflow = _workflow_text("strix.yml")
    script = _run_script(_workflow_step(workflow, "Run Strix (quick)"))

    fake_gate = tmp_path / "fake-strix-gate.sh"
    fake_gate.write_text(
        "#!/usr/bin/env bash\n"
        "echo 'openai.RateLimitError: exceeded your current quota'\n"
        "echo 'Configured model and fallback models were unavailable.'\n"
        "exit 17\n",
        encoding="utf-8",
    )
    fake_gate.chmod(0o700)

    result = subprocess.run(
        [BASH, "--noprofile", "--norc", "-eo", "pipefail"],
        input=script,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "RUNNER_TEMP": str(tmp_path),
            "TRUSTED_STRIX_GATE": str(fake_gate),
        },
        check=False,
    )

    assert result.returncode == 17
    assert "Strix returned exit 17" in result.stdout
    assert "not converted to success" in result.stdout
    assert (tmp_path / "strix_gate_console.log").read_text(encoding="utf-8") == (
        "openai.RateLimitError: exceeded your current quota\n"
        "Configured model and fallback models were unavailable.\n"
    )
