"""Repository-level tests for the committed shared fallback manifest."""

from __future__ import annotations

import sys

from scripts.ci import contextual_fallback_policy as policy


def test_repository_manifest_uses_verified_vendor_for_all_three_agents() -> None:
    """The committed manifest and vendored module enforce one shared ordering."""
    for name in list(sys.modules):
        if name == "contextual_orchestrator" or name.startswith(
            "contextual_orchestrator."
        ):
            sys.modules.pop(name)

    noema_models = policy.plan_models(
        "noema",
        repository_visibility="public",
        configured_models=(
            "configured/noema-custom",
            "nvidia/nemotron-3-super-120b-a12b",
            "nvidia/nemotron-3-ultra-550b-a55b",
            "nvidia/llama-3.3-nemotron-super-49b-v1.5",
        ),
        required_capabilities=("structured_output",),
        environ={
            "NVIDIA_NIM_API_KEY": "configured",
            "NOEMA_CUSTOM_LLM_CONFIGURED": "configured",
        },
    )
    assert noema_models == (
        "nvidia/nemotron-3-ultra-550b-a55b",
        "nvidia/llama-3.3-nemotron-super-49b-v1.5",
        "nvidia/nemotron-3-super-120b-a12b",
        "configured/noema-custom",
    )

    opencode_models = policy.plan_models(
        "opencode-review",
        repository_visibility="private",
        configured_models=(
            "opencode/gpt-5.6-terra",
            "openai/gpt-5.6-luna",
            "github-models/openai/o3",
        ),
        required_capabilities=("code_review",),
        environ={
            "OPENCODE_API_KEY": "configured",
            "OPENAI_API_KEY": "configured",
        },
    )
    assert opencode_models == (
        "github-models/openai/o3",
        "opencode/gpt-5.6-terra",
        "openai/gpt-5.6-luna",
    )

    strix_models = policy.plan_models(
        "strix",
        repository_visibility="private",
        configured_models=(
            "configured/strix-paid-primary",
            "github_models/openai/o3",
        ),
        required_capabilities=("security_review",),
        environ={
            "STRIX_PRIMARY_KEY_CONFIGURED": "configured",
            "STRIX_GITHUB_MODELS_CONFIGURED": "configured",
        },
    )
    assert strix_models == (
        "github_models/openai/o3",
        "configured/strix-paid-primary",
    )
