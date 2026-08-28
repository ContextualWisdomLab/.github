"""Noema review now uses the vendored orchestrator sidecar, not NVIDIA NIM."""

from __future__ import annotations

import os
import shutil
import subprocess
import textwrap
from pathlib import Path

from tests.test_required_workflow_queue_contract import workflow_step, workflow_text


def test_noema_review_credentials_and_llm_use_orchestrator_free() -> None:
    """Require reviewer credentials and the sidecar; the public NIM hardcode is gone."""
    workflow = workflow_text("noema-review.yml")

    assert "fail_unavailable()" in workflow
    assert 'echo "::error::$message"' in workflow
    assert "vars.NOEMA_TOKEN_EXCHANGE_URL || vars.NOEMA_EXCHANGE_URL || ''" in workflow
    assert (
        "Noema reviewer credential is unconfigured: set NOEMA_GITHUB_APP_CLIENT_ID with "
        "NOEMA_GITHUB_APP_PRIVATE_KEY, NOEMA_REVIEW_TOKEN, or NOEMA_TOKEN_EXCHANGE_URL. "
        "Review cannot be skipped."
    ) in workflow
    assert (
        "Noema reviewer credential selection succeeded but no token was minted"
        in workflow
    )
    assert "https://integrate.api.nvidia.com/v1/chat/completions" not in workflow
    assert "nvidia/nemotron-3-ultra-550b-a55b" not in workflow
    assert "Resolve Noema target repository visibility" in workflow
    assert "target_visibility.outputs.require_zdr" in workflow
    assert "CONTEXTUAL_ORCHESTRATOR_REQUIRE_ZDR" in workflow
    assert (
        "NOEMA_LLM_API_KEY: ${{ secrets.NOEMA_LLM_API_KEY || secrets.OPENAI_API_KEY || '' }}"
        not in workflow
    )
    assert "contextual_orchestrator_review_sidecar.sh" in workflow
    assert "BYTEZ_API_KEY: ${{ secrets.BYTEZ_API_KEY }}" in workflow
    assert "NVIDIA_NIM_API_KEY: ${{ secrets.NVIDIA_NIM_API_KEY }}" in workflow
    assert "NVIDIA_NIM_API_KEY_SUB: ${{ secrets.NVIDIA_NIM_API_KEY_SUB }}" in workflow
    assert "OPENROUTER_API_KEY: ${{ secrets.OPENROUTER_API_KEY }}" in workflow
    assert "OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}" in workflow
    assert 'export NOEMA_LLM_MODEL="orchestrator/free"' in workflow
    assert (
        "contextual-orchestrator review sidecar must be provisioned before Noema LLM review."
        in workflow
    )
    assert "mark_unconfigured()" not in workflow
    assert "review skipped until Noema is deployed" not in workflow
    assert "Noema app token is unavailable; review skipped." not in workflow
    assert "COPILOT_GITHUB_TOKEN" not in workflow
    assert "secrets: inherit" not in workflow


def test_strix_nim_defaults_and_noema_sidecar_fail_closed(tmp_path: Path) -> None:
    """Keep the Strix NIM empty-output contract; Noema now fails closed without the sidecar."""
    bash_executable = shutil.which("bash") or "/bin/bash"
    strix_output = tmp_path / "strix-output"
    strix = subprocess.run(  # noqa: S603, S607
        [
            bash_executable,
            "-c",
            textwrap.dedent(
                workflow_step(
                    workflow_text("strix.yml"),
                    "Resolve live NVIDIA NIM Strix models",
                )
                .split("        run: |\n", 1)[1]
            ),
        ],
        env={
            **os.environ,
            "GITHUB_OUTPUT": str(strix_output),
            "STRIX_MODEL_REQUESTED": "",
            "NVIDIA_API_KEY": "",
            "TARGET_REPOSITORY_PRIVATE": "false",
            "STRIX_NVIDIA_PRIMARY_CANDIDATES": "nvidia/primary",
            "STRIX_NVIDIA_FALLBACK_CANDIDATES": "nvidia/fallback",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert strix.returncode == 0, strix.stderr
    assert {"primary=", "fallback="} <= set(strix_output.read_text().splitlines())
    assert (
        "steps.resolve_nvidia_models.outputs.primary || 'gpt-5.4'"
        in workflow_text("strix.yml")
    )
    assert (
        "STRIX_MODEL: ${{ steps.gate.outputs.strix_model }}"
        in workflow_text("strix.yml")
    )

    noema_script = textwrap.dedent(
        workflow_step(
            workflow_text("noema-review.yml"),
            "Run Noema LLM review and submit verdict",
        ).split("        run: |\n", 1)[1]
    )
    noema_env = {
        **os.environ,
        "PR_NUMBER": "1",
        "GH_TOKEN": "synthetic-review-token",
    }
    for key in (
        "CONTEXTUAL_ORCHESTRATOR_BASE_URL",
        "CONTEXTUAL_ORCHESTRATOR_TOKEN",
        "NOEMA_LLM_VIA_ORCHESTRATOR",
        "NOEMA_LLM_API_KEY",
    ):
        noema_env.pop(key, None)
    noema = subprocess.run(  # noqa: S603, S607
        [bash_executable, "-c", noema_script],
        env=noema_env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert noema.returncode == 1
    assert "sidecar must be provisioned before Noema LLM review" in noema.stdout
