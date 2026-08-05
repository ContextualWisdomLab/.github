"""Cross-repository credential contracts for NVIDIA NIM PR maintenance."""

from __future__ import annotations

from pathlib import Path


SCHEDULER_WORKFLOW = Path(".github/workflows/nvidia-nim-pr-maintenance.yml")


def test_scheduler_exchanges_app_token_before_cross_repository_dispatch() -> None:
    """The scheduler should not require a leaf repository's token to write centrally."""

    workflow = SCHEDULER_WORKFLOW.read_text(encoding="utf-8")

    assert "Exchange OpenCode app token for scheduler writes" in workflow
    assert "OIDC_AUDIENCE: opencode-github-action" in workflow
    assert "https://api.opencode.ai/exchange_github_app_token" not in workflow
    assert '"${OPENCODE_API_BASE_URL}/exchange_github_app_token"' in workflow
    assert "steps.scheduler_app_token.outputs.token" in workflow
    assert (
        "steps.scheduler_app_token.outputs.token || secrets.PR_REVIEW_MERGE_TOKEN"
        in workflow
    )
    assert "secrets.OPENCODE_APPROVE_TOKEN || github.token" in workflow


def test_scheduler_keeps_inference_and_github_credentials_separate() -> None:
    """The scheduler may obtain GitHub transport credentials but no model API key."""

    workflow = SCHEDULER_WORKFLOW.read_text(encoding="utf-8")

    assert "NVIDIA_NIM_API_KEY" not in workflow
    assert "NVIDIA_API_KEY" not in workflow
    assert "COPILOT_GITHUB_TOKEN" not in workflow
    assert "STRIX_GITHUB_MODELS_TOKEN" not in workflow
