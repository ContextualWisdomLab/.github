"""Contract tests for the contextual-orchestrator OpenCode sidecar."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/opencode-review-dispatch.yml"
RUNNER = ROOT / "scripts/ci/run_opencode_review_model_pool.sh"
GATEWAY_COMMIT = "0071751782ae535721e71785c3037989d2d27b77"


def test_isolated_opencode_review_uses_pinned_contextual_gateway():
    """The trusted review job imports the gateway without replacing fallbacks."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    runner = RUNNER.read_text(encoding="utf-8")

    assert "ContextualWisdomLab/contextual-orchestrator" in workflow
    assert GATEWAY_COMMIT in workflow
    assert "persist-credentials: false" in workflow
    assert '"contextual-orchestrator"' in workflow
    assert '"baseURL": "{env:CONTEXTUAL_ORCHESTRATOR_BASE_URL}"' in workflow
    assert "CONTEXTUAL_ORCHESTRATOR_TOKEN" in workflow
    assert "CONTEXTUAL_ORCHESTRATOR_ENABLED" in workflow
    assert "contextual-orchestrator/contextual-orchestrator" in workflow
    assert "OPENAI_API_KEY" in workflow
    assert "OPENROUTER_API_KEY" in workflow
    assert "NVIDIA_NIM_API_KEY" in workflow
    assert "NVIDIA_NIM_API_KEY_SUB" in workflow
    assert "BYTEZ_API_KEY" in workflow
    assert "is_contextual_orchestrator_candidate" in runner
    assert "CONTEXTUAL_ORCHESTRATOR_BASE_URL" in runner
    assert "nvidia-nim/nvidia/llama-3.3-nemotron-super-49b-v1.5" in workflow
    assert "openrouter/deepseek/deepseek-v3.2" in workflow
    assert "COPILOT_GITHUB_TOKEN" not in workflow


def test_contextual_gateway_review_job_stays_loopback_only():
    """The sidecar is started on loopback and does not broaden bind authority."""
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "--host 127.0.0.1" in workflow
    assert "--auth-token" not in workflow
    assert "--allow-public-bind" not in workflow


def test_gateway_checkout_failure_preserves_existing_review_provider_pool():
    """A missing pinned gateway must not fail the required review job."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    checkout = workflow.split(
        "      - name: Checkout pinned contextual-orchestrator review gateway\n", 1
    )[1].split("      - name:", 1)[0]
    model_step = workflow.split("      - name: Run OpenCode PR Review model pool\n", 1)[
        1
    ].split("      - name:", 1)[0]

    assert "id: contextual_orchestrator_checkout" in checkout
    assert "continue-on-error: true" in checkout
    assert (
        "CONTEXTUAL_ORCHESTRATOR_CHECKOUT_SUCCEEDED: "
        "${{ steps.contextual_orchestrator_checkout.outcome == 'success' "
        "&& 'true' || 'false' }}"
    ) in model_step
    assert (
        'if [ "$CONTEXTUAL_ORCHESTRATOR_CHECKOUT_SUCCEEDED" = "true" ] &&'
        in model_step
    )
    assert (
        '[ -d "$GITHUB_WORKSPACE/trusted-contextual-orchestrator/'
        'contextual_orchestrator" ]'
        in model_step
    )


def test_private_repository_never_starts_or_selects_contextual_gateway():
    """Keep private source out of the gateway's broader provider catalog."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    model_step = workflow.split("      - name: Run OpenCode PR Review model pool\n", 1)[
        1
    ].split("      - name:", 1)[0]

    assert (
        "REPOSITORY_IS_PRIVATE: "
        "${{ needs.validate-pr-metadata.outputs.is_private }}"
    ) in model_step
    assert (
        "OPENCODE_MODEL_CANDIDATES: \"${{ "
        "needs.validate-pr-metadata.outputs.is_private == 'false' && "
        "'contextual-orchestrator/contextual-orchestrator "
        in model_step
    )
    assert 'if [ "$REPOSITORY_IS_PRIVATE" = "false" ]; then' in model_step
