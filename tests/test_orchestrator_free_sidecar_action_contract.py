"""Contract tests for the central orchestrator/free composite action."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACTION = ROOT / ".github/actions/orchestrator-free-sidecar/action.yml"


def test_action_uses_only_immutable_central_sidecar_source() -> None:
    source = ACTION.read_text(encoding="utf-8")
    assert "using: composite" in source
    assert "repository: ContextualWisdomLab/.github" in source
    assert "ref: ${{ github.action_ref }}" in source
    assert "persist-credentials: false" in source
    assert "contextual_orchestrator_review_sidecar.sh" in source
    assert "orchestrator/free" in source
    assert "anomalyco/opencode" not in source
    assert "integrate.api.nvidia.com" not in source
    assert "nvidia/" not in source


def test_action_keeps_provider_bootstrap_and_gateway_boundaries_separate() -> None:
    source = ACTION.read_text(encoding="utf-8")
    assert "CONTEXTUAL_ORCHESTRATOR_REQUIRE_ZDR" in source
    assert "ORCHESTRATOR_CATALOG_LIMIT" in source
    assert "ORCHESTRATOR_CATALOG_ACCOUNT_CAP" in source
    assert "github.action_ref" in source
    assert "GITHUB_TOKEN" not in source
    assert "OPENROUTER_API_KEY" not in source
    assert "NVIDIA_NIM_API_KEY" not in source
