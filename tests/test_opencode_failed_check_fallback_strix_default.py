"""Regression tests for mapping the live visibility-aware Strix default."""

from __future__ import annotations

import subprocess
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FALLBACK_EMITTER = (
    REPOSITORY_ROOT
    / "scripts"
    / "ci"
    / "emit_opencode_failed_check_fallback_findings.sh"
)
LIVE_STRIX_DEFAULT = (
    "github.event.client_payload.strix_llm || "
    "(steps.target_visibility.outputs.is_private == 'false' && "
    "'nvidia_nim/nvidia/nemotron-3-super-120b-a12b' || 'gpt-5.4')"
)


def test_live_strix_visibility_default_maps_to_exact_workflow_line(
    tmp_path: Path,
) -> None:
    """Emit a source-backed finding for the exact live Strix default."""

    fixture_repo = tmp_path / "repo"
    workflow = fixture_repo / ".github" / "workflows" / "strix.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(f"STRIX_MODEL: ${{{{ {LIVE_STRIX_DEFAULT} }}}}\n", encoding="utf-8")
    evidence = tmp_path / "failed-check-evidence.md"
    evidence.write_text(
        "## Failed check: Strix Changed Path Quality CI/quality\n\n"
        f"Self-test Strix gate script failed: missing '{LIVE_STRIX_DEFAULT}'.\n",
        encoding="utf-8",
    )

    completed = subprocess.run(
        ["bash", str(FALLBACK_EMITTER), str(evidence), str(fixture_repo)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert ".github/workflows/strix.yml:1" in completed.stdout
    assert "Strix PR scans must default to NVIDIA NIM Nemotron" in completed.stdout
