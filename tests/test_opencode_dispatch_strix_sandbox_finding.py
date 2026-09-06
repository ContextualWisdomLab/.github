"""The failed-check finding must name Strix sandbox when the gate named it.

`#1953` gave the Strix sandbox bootstrap failure its own verdict token,
`STRIX_SANDBOX_UNAVAILABLE`, precisely because reporting it as
`contextual-orchestrator/orchestrator/free exhausted` sent readers to a
component the run never reached. This consumer rendered one fixed finding for
every `STRIX_PROVIDER_UNAVAILABLE` line, so the corrected verdict was being
re-attributed to the gateway one step downstream, and no test covered the text
at all. These tests pin both directions.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from tests.test_opencode_workflow_shell_syntax import _extract_run_block

WORKFLOW = Path(".github/workflows/opencode-review-dispatch.yml")
STEP_NAME = "Publish OpenCode review outcome"
FUNCTION = "emit_strix_provider_failure_finding"


def _emitter_source() -> str:
    """Return the emitter function's shell source from the published run block."""
    script = _extract_run_block(WORKFLOW.read_text(encoding="utf-8"), STEP_NAME)
    start = script.index(f"{FUNCTION}() {{")
    # ``_extract_run_block`` dedents the YAML block scalar, leaving the
    # function body at two spaces and its closing brace on a line of its own.
    closing = "\n  }\n"
    end = script.index(closing, start) + len(closing)
    return script[start:end]


def _run_emitter(evidence: str, tmp_path: Path) -> str:
    """Run the production emitter against one evidence file and return its finding text."""
    evidence_file = tmp_path / "strix-evidence.txt"
    evidence_file.write_text(evidence, encoding="utf-8")
    harness = tmp_path / "harness.sh"
    harness.write_text(
        "set -euo pipefail\n"
        f'strix_evidence_file="{evidence_file}"\n'
        f'repo_root="{tmp_path}"\n'
        "finding_index=0\n"
        f"{_emitter_source()}\n"
        f"{FUNCTION}\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        ["bash", str(harness)], capture_output=True, text=True, check=True
    )
    return result.stdout


def test_sandbox_token_reports_the_sandbox_not_the_gateway(tmp_path: Path) -> None:
    """A `STRIX_SANDBOX_UNAVAILABLE` verdict never blames the gateway or its provider pool."""
    finding = _run_emitter(
        "STRIX_PROVIDER_UNAVAILABLE: STRIX_SANDBOX_UNAVAILABLE: the last Strix "
        "attempt ended in the sandbox bootstrap (Caido proxy on 127.0.0.1 "
        "unreachable through Strix's loginAsGuest attempts) after 1 "
        "sandbox-specific same-model retries (budget 1); this verdict names "
        "Strix's sandbox, not the LLM gateway.\n",
        tmp_path,
    )

    assert "Strix sandbox bootstrap blocked current-head security evidence" in finding
    assert "STRIX_SANDBOX_UNAVAILABLE" in finding
    assert "names Strix sandbox, not the contextual-orchestrator gateway" in finding
    assert "gateway or its discovered provider pool was unavailable" not in finding
    # The reader must not be sent to change gateway configuration.
    assert "Do not change gateway or provider configuration" in finding
    assert finding.startswith("### 1. HIGH .github/workflows/strix.yml:")


def test_gateway_failure_keeps_its_existing_finding(tmp_path: Path) -> None:
    """Without the sandbox token the previous gateway text is emitted unchanged."""
    finding = _run_emitter(
        "STRIX_PROVIDER_UNAVAILABLE: contextual-orchestrator/orchestrator/free "
        "exhausted; the gateway owns provider discovery and failover.\n",
        tmp_path,
    )

    assert (
        "Contextual-orchestrator provider availability blocked current-head security evidence"
        in finding
    )
    assert "gateway or its discovered provider pool was unavailable" in finding
    assert "STRIX_SANDBOX_UNAVAILABLE" not in finding
    assert "Strix sandbox bootstrap blocked" not in finding


def test_unrelated_evidence_emits_no_finding(tmp_path: Path) -> None:
    """Evidence with no provider-unavailable signal still produces nothing."""
    assert _run_emitter("Strix run succeeded for model 'x' in 12s.\n", tmp_path) == ""
