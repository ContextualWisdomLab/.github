"""Contracts for the privileged OpenCode pull-request autofix worker."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
AUTOFIX_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "pr-review-autofix.yml"


def test_pr_review_autofix_uses_only_nvidia_nim_for_llm_inference() -> None:
    """Require the write-capable autofix agent to use the approved NVIDIA NIM secret."""
    workflow = AUTOFIX_WORKFLOW.read_text(encoding="utf-8")

    assert '"model": "nvidia-nim/nvidia/llama-3.3-nemotron-super-49b-v1.5"' in workflow
    assert '"small_model": "nvidia-nim/meta/llama-3.3-70b-instruct"' in workflow
    assert '"enabled_providers": ["nvidia-nim"]' in workflow
    assert '"nvidia-nim": {' in workflow
    assert '"baseURL": "https://integrate.api.nvidia.com/v1"' in workflow
    assert '"apiKey": "{env:NVIDIA_API_KEY}"' in workflow
    assert "NVIDIA_API_KEY: ${{ secrets.NVIDIA_NIM_API_KEY }}" in workflow
    assert "MODEL: nvidia-nim/nvidia/llama-3.3-nemotron-super-49b-v1.5" in workflow

    assert "STRIX_GITHUB_MODELS_TOKEN" not in workflow
    assert '"github-models"' not in workflow
    assert "models.github.ai" not in workflow


def test_pr_review_autofix_preserves_existing_github_write_identity_chain() -> None:
    """Keep repository-write credentials separate from the NVIDIA model credential."""
    workflow = AUTOFIX_WORKFLOW.read_text(encoding="utf-8")

    existing_write_chain = (
        "secrets.PR_REVIEW_MERGE_TOKEN || secrets.OPENCODE_APPROVE_TOKEN || "
        "steps.target_app_token.outputs.token || github.token"
    )
    assert workflow.count(existing_write_chain) >= 2
    assert "GITHUB_TOKEN: ${{ secrets.PR_REVIEW_MERGE_TOKEN || secrets.OPENCODE_APPROVE_TOKEN || steps.target_app_token.outputs.token || github.token }}" in workflow
    assert "NVIDIA_NIM_API_KEY" not in existing_write_chain
