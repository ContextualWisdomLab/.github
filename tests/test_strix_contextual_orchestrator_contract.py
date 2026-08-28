"""Contracts for routing default Strix scans through contextual-orchestrator."""

from __future__ import annotations

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/strix.yml"
SIDECAR = ROOT / "scripts/ci/contextual_orchestrator_review_sidecar.sh"
SMOKE = ROOT / "scripts/ci/strix_required_workflow_smoke.sh"


class StrixContextualOrchestratorContract(unittest.TestCase):
    """Pin the gateway-first default while retaining explicit diagnostics."""

    def setUp(self) -> None:
        """Load the tracked workflow and helper contracts."""
        self.workflow = WORKFLOW.read_text(encoding="utf-8")
        self.sidecar = SIDECAR.read_text(encoding="utf-8")
        self.smoke = SMOKE.read_text(encoding="utf-8")

    def test_default_scan_provisions_the_existing_gateway_sidecar(self) -> None:
        """Normal scans use the five-provider gateway, not a direct pool."""
        self.assertIn("Provision contextual-orchestrator Strix sidecar", self.workflow)
        self.assertIn(
            "STRIX_MODEL: ${{ github.event.client_payload.strix_llm || 'contextual-orchestrator/orchestrator/free' }}",
            self.workflow,
        )
        self.assertIn("provider_mode=contextual_orchestrator", self.workflow)
        self.assertNotIn(
            "steps.resolve_nvidia_models.outputs.primary || 'gpt-5.4'",
            self.workflow,
        )

    def test_gateway_is_openai_compatible_and_loopback_bound(self) -> None:
        """Strix calls the local OpenAI-compatible route with a bearer token."""
        self.assertIn("openai/orchestrator/free", self.workflow)
        self.assertIn("CONTEXTUAL_ORCHESTRATOR_BASE_URL", self.workflow)
        self.assertIn("CONTEXTUAL_ORCHESTRATOR_TOKEN", self.workflow)
        self.assertIn("^http://127\\.0\\.0\\.1:[0-9]{1,5}$", self.workflow)
        self.assertIn("${CONTEXTUAL_ORCHESTRATOR_BASE_URL}/v1", self.workflow)

    def test_explicit_direct_provider_diagnostics_remain_available(self) -> None:
        """A caller-selected diagnostic model preserves existing direct modes."""
        self.assertIn("github.event.client_payload.strix_llm", self.workflow)
        self.assertIn("nvidia_nim/*)", self.workflow)
        self.assertIn("openrouter/free", self.workflow)
        self.assertIn("openai-direct/gpt-5.4", self.workflow)

    def test_explicit_gateway_dispatch_provisions_the_sidecar(self) -> None:
        """An explicit gateway request must start the same sidecar as the default."""
        self.assertIn(
            "github.event.client_payload.strix_llm == 'contextual-orchestrator/orchestrator/free'",
            self.workflow,
        )

    def test_nvidia_resolution_is_scoped_to_nvidia_diagnostics(self) -> None:
        """Unrelated explicit diagnostics cannot be failed by NVIDIA discovery."""
        self.assertIn('case "$STRIX_MODEL_REQUESTED" in', self.workflow)
        self.assertIn('nvidia_nim/*) ;;', self.workflow)
        self.assertIn("Skipping NVIDIA model resolution for non-NVIDIA Strix request", self.workflow)

    def test_private_gateway_scans_require_zdr_only_routing(self) -> None:
        """Private source never enters the gateway's non-ZDR fallback tier."""
        self.assertIn(
            "ORCHESTRATOR_REQUIRE_ZDR: ${{ steps.target_visibility.outputs.is_private }}",
            self.workflow,
        )

    def test_gateway_install_is_isolated_and_token_is_masked(self) -> None:
        """The sidecar cannot overwrite Strix's hash-locked Python runtime."""
        self.assertIn('--target "$ORCHESTRATOR_SITE_PACKAGES"', self.sidecar)
        self.assertIn("--require-hashes", self.sidecar)
        self.assertIn("--only-binary=:all:", self.sidecar)
        self.assertIn('-r "$ORCHESTRATOR_SOURCE/requirements.lock"', self.sidecar)
        self.assertIn(
            'PYTHONPATH="$ORCHESTRATOR_SITE_PACKAGES:$ORCHESTRATOR_SOURCE:$ORG_REPO_ROOT"',
            self.sidecar,
        )
        self.assertIn("::add-mask::%s", self.sidecar)

    def test_required_smoke_pins_the_gateway_default(self) -> None:
        """The bounded required-path smoke rejects a future direct-default regression."""
        self.assertIn("contextual-orchestrator Strix sidecar", self.smoke)
        self.assertIn("openai/orchestrator/free", self.smoke)
        self.assertIn("direct-provider models only as explicit diagnostics", self.smoke)


if __name__ == "__main__":
    unittest.main()
