"""Contract tests for the contextual-orchestrator OpenCode sidecar."""

import json
from pathlib import Path

from scripts.ci.assert_opencode_reasoning_effort import (
    strip_jsonc_comments,
    validate_candidate,
)

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/opencode-review-dispatch.yml"
RUNNER = ROOT / "scripts/ci/run_opencode_review_model_pool.sh"
OPENCODE_CONFIG = ROOT / "opencode.jsonc"
DOCTORING = ROOT / "docs/doctoring/contextual-orchestrator-opencode-gateway.md"
GATEWAY_COMMIT = "d3a27db0a69f09f245a19a189ec41d3aa2f6b2fc"
SPDX_MIT_LICENSE_BLOB_SHA = "591bbf197b355e60604618c8a8a50bc5a839b204"
GATEWAY_CANDIDATE = "contextual-orchestrator/contextual-orchestrator"


def load_generated_review_config() -> dict:
    """Extract the exact JSON object emitted into the isolated review workdir."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    config_body = workflow.split("          jq -n '{", 1)[1].split(
        "          }' >\"${OPENCODE_REVIEW_WORKDIR}/opencode.jsonc\"", 1
    )[0]
    return json.loads("{" + config_body + "          }")


def test_isolated_opencode_review_uses_pinned_contextual_gateway():
    """The trusted review job imports the gateway without replacing fallbacks."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    runner = RUNNER.read_text(encoding="utf-8")
    doctoring = DOCTORING.read_text(encoding="utf-8")

    assert "ContextualWisdomLab/contextual-orchestrator" in workflow
    assert GATEWAY_COMMIT in workflow
    assert "persist-credentials: false" in workflow
    assert "if: needs.validate-pr-metadata.outputs.is_private == 'false'" in workflow
    assert '"contextual-orchestrator"' in workflow
    assert '"baseURL": "{env:CONTEXTUAL_ORCHESTRATOR_BASE_URL}"' in workflow
    assert "CONTEXTUAL_ORCHESTRATOR_TOKEN" in workflow
    assert "CONTEXTUAL_ORCHESTRATOR_ENABLED" in workflow
    assert "review_gateway.py" in workflow
    assert 'Authorization: Bearer ${CONTEXTUAL_ORCHESTRATOR_TOKEN}' in workflow
    assert '"${CONTEXTUAL_ORCHESTRATOR_BASE_URL%/v1}/healthz"' in workflow
    assert '"${CONTEXTUAL_ORCHESTRATOR_BASE_URL}/models"' in workflow
    assert 'payload.get("data")' in workflow
    assert 'any(isinstance(model, dict) and str(model.get("id") or "").strip() for model in models)' in workflow
    assert "contextual-orchestrator/contextual-orchestrator" in workflow
    assert "OPENAI_API_KEY" in workflow
    assert "OPENROUTER_API_KEY" in workflow
    assert "NVIDIA_NIM_API_KEY" in workflow
    assert "NVIDIA_NIM_API_KEY_SUB" in workflow
    assert "BYTEZ_API_KEY" in workflow
    assert "is_contextual_orchestrator_candidate" in runner
    assert "CONTEXTUAL_ORCHESTRATOR_BASE_URL" in runner
    assert 'CONTEXTUAL_ORCHESTRATOR_BASE_URL: "http://127.0.0.1:18080/v1"' in workflow
    assert "nvidia-nim/nvidia/llama-3.3-nemotron-super-49b-v1.5" in workflow
    assert "openrouter/deepseek/deepseek-v3.2" in workflow
    assert "COPILOT_GITHUB_TOKEN" not in workflow
    assert GATEWAY_COMMIT in doctoring
    assert "127.0.0.1:18080" in doctoring
    assert "/healthz" in doctoring
    assert "/v1/models" in doctoring
    assert "Private repositories never start or select the gateway" in doctoring
    assert 'license_file="$GITHUB_WORKSPACE/trusted-contextual-orchestrator/LICENSE"' in workflow
    assert "SPDX-License-Identifier: MIT" in workflow
    assert "spdx_license_id=MIT" in workflow
    assert f"spdx_mit_license_blob_sha={SPDX_MIT_LICENSE_BLOB_SHA}" in workflow
    assert "SPDX-License-Identifier: MIT" in doctoring
    assert SPDX_MIT_LICENSE_BLOB_SHA in doctoring

    gateway_launch = workflow.rsplit("            env -i \\\n", 1)[1].split(
        "              python3 -m contextual_orchestrator.review_gateway \\\n", 1
    )[0]
    assert "PATH=\"$PATH\"" in gateway_launch
    assert "HOME=\"$HOME\"" in gateway_launch
    assert "PYTHONPATH=\"$PYTHONPATH\"" in gateway_launch
    assert "BYTEZ_API_KEY=\"${BYTEZ_API_KEY:-}\"" in gateway_launch
    assert "NVIDIA_NIM_API_KEY=\"${NVIDIA_NIM_API_KEY:-}\"" in gateway_launch
    assert "NVIDIA_NIM_API_KEY_SUB=\"${NVIDIA_NIM_API_KEY_SUB:-}\"" in gateway_launch
    assert "OPENROUTER_API_KEY=\"${OPENROUTER_API_KEY:-}\"" in gateway_launch
    assert "OPENAI_API_KEY=\"${OPENAI_API_KEY:-}\"" in gateway_launch
    assert "STRIX_GITHUB_MODELS_TOKEN" not in gateway_launch
    assert "OPENCODE_API_KEY" not in gateway_launch
    assert "GITHUB_TOKEN" not in gateway_launch
    assert "GITHUB_STATE=/dev/null" in gateway_launch


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
        '[ -f "$GITHUB_WORKSPACE/trusted-contextual-orchestrator/'
        'contextual_orchestrator/review_gateway.py" ]'
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


def test_contextual_gateway_is_a_high_effort_top_level_review_provider():
    """The enabled gateway must survive the pool's strict reasoning preflight."""
    static_config = json.loads(
        strip_jsonc_comments(OPENCODE_CONFIG.read_text(encoding="utf-8"))
    )
    generated_config = load_generated_review_config()

    for config in (static_config, generated_config):
        assert GATEWAY_CANDIDATE in {
            f"{provider}/{model}"
            for provider, provider_config in config["provider"].items()
            for model in provider_config.get("models", {})
        }
        assert validate_candidate(config, GATEWAY_CANDIDATE) == []
