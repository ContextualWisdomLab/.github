"""Behaviour contract for the `python-security.yml` pip-audit hard gate.

Issue #2158: the step folded every non-zero pip-audit exit into one message
that asserted "known-vulnerable Python dependencies", so a PyPI transport
failure (`ConnectionResetError` from the advisory query, no findings at all)
read like a security finding and misdirected triage. The gate must stay
closed on every failure, but the printed evidence has to say which of the
two things happened. pip-audit 2.10.1 (the pinned version) prints
`Found N known vulnerabilit(y|ies) ... in N package(s)` to stderr when it has
findings (`pip_audit/_cli.py`), so that line is the discriminator.

The tests execute the real step body with a fake `pip-audit` on PATH, the
same technique as `test_workflow_file_detection_pipefail_regression.py`.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import stat
import subprocess

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPO_ROOT / ".github/workflows/python-security.yml"
STEP_MARKER = "      - name: Run pip-audit (hard gate on any known vulnerability)\n"


def _extract_pip_audit_script(workflow_text: str) -> str:
    """Return the step's `run:` body with the YAML block indentation removed."""
    start = workflow_text.index(STEP_MARKER)
    run_start = workflow_text.index("        run: |\n", start) + len("        run: |\n")
    rest = workflow_text[run_start:]
    # The body ends at the next step (`      - name:`) or the next top-level
    # job key (two spaces then a non-space); blank lines inside the script are
    # followed by ten-space indentation and must not terminate it.
    boundary = re.search(r"\n(?:      - name:|\n  \S)", rest)
    block = rest[: boundary.start()] if boundary else rest
    return "\n".join(line[10:] for line in block.splitlines())


def _fake_pip_audit(bin_dir: Path, body: str) -> None:
    """Install a `pip-audit` shim whose behaviour is the given shell body."""
    shim = bin_dir / "pip-audit"
    shim.write_text("#!/usr/bin/env bash\n" + body + "\n", encoding="utf-8")
    shim.chmod(shim.stat().st_mode | stat.S_IXUSR)


def _run_step(tmp_path: Path, shim_body: str) -> subprocess.CompletedProcess[str]:
    """Run the extracted step in a repo holding one requirements file."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "requirements-demo-ci.txt").write_text("requests==2.32.0\n", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_pip_audit(bin_dir, shim_body)
    script = _extract_pip_audit_script(WORKFLOW.read_text(encoding="utf-8"))
    return subprocess.run(
        ["bash", "-c", script],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"},
    )


def test_genuine_findings_fail_closed_and_are_reported_as_findings(tmp_path):
    """A real advisory hit still fails the job and names the vulnerable input."""
    result = _run_step(
        tmp_path,
        'echo "Found 2 known vulnerabilities in 1 package" >&2; exit 1',
    )
    assert result.returncode == 1
    assert "::error::pip-audit found known-vulnerable Python dependencies in -r ./requirements-demo-ci.txt" in result.stdout
    assert "could not complete" not in result.stdout


def test_transport_failure_fails_closed_but_is_not_called_a_vulnerability(tmp_path):
    """The #2158 shape: no findings, then an unhandled PyPI connection error."""
    result = _run_step(
        tmp_path,
        'echo "No known vulnerabilities found" >&2; '
        'echo "Traceback (most recent call last):" >&2; '
        'echo "ConnectionResetError: [Errno 104] Connection reset by peer" >&2; exit 1',
    )
    assert result.returncode == 1
    assert "known-vulnerable" not in result.stdout
    assert (
        "::error::pip-audit could not complete for -r ./requirements-demo-ci.txt: "
        "ConnectionResetError: [Errno 104] Connection reset by peer"
    ) in result.stdout
    assert "not a vulnerability finding" in result.stdout


def test_clean_audit_passes_without_error_annotations(tmp_path):
    """A clean run exits 0 and prints no `::error::` line."""
    result = _run_step(tmp_path, 'echo "No known vulnerabilities found" >&2; exit 0')
    assert result.returncode == 0, result.stderr
    assert "::error::" not in result.stdout


def test_step_no_longer_asserts_a_finding_for_every_failure():
    """The single catch-all message must be gone from the workflow text."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "::error::pip-audit reported known-vulnerable Python dependencies." not in workflow
    assert "Found [0-9]+ known vulnerabilit" in workflow
