"""Contracts for routing default Strix scans through contextual-orchestrator."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/strix.yml"
SIDECAR = ROOT / "scripts/ci/contextual_orchestrator_review_sidecar.sh"
TOKEN_LOADER = ROOT / "scripts/ci/load_contextual_orchestrator_token.sh"
SMOKE = ROOT / "scripts/ci/strix_required_workflow_smoke.sh"


class StrixContextualOrchestratorContract(unittest.TestCase):
    """Pin the protected-main gateway-only Strix contract."""

    def setUp(self) -> None:
        """Load the tracked workflow and helper contracts."""
        self.workflow = WORKFLOW.read_text(encoding="utf-8")
        self.sidecar = SIDECAR.read_text(encoding="utf-8")
        self.smoke = SMOKE.read_text(encoding="utf-8")

    def test_default_scan_provisions_the_existing_gateway_sidecar(self) -> None:
        """Every scan uses the five-provider gateway, never a direct pool."""
        self.assertIn("Provision contextual-orchestrator Strix sidecar", self.workflow)
        self.assertIn("STRIX_MODEL: contextual-orchestrator/orchestrator/free", self.workflow)
        self.assertIn("provider_mode=contextual_orchestrator", self.workflow)
        self.assertIn("STRIX_FALLBACK_MODELS: \"\"", self.workflow)
        self.assertNotIn(
            "steps.resolve_nvidia_models.outputs.primary || 'gpt-5.4'",
            self.workflow,
        )

    def test_gateway_is_openai_compatible_and_loopback_bound(self) -> None:
        """Strix calls the local OpenAI-compatible route with a bearer token."""
        self.assertIn("CONTEXTUAL_ORCHESTRATOR_BASE_URL", self.workflow)
        self.assertIn("CONTEXTUAL_ORCHESTRATOR_TOKEN", self.workflow)
        self.assertIn(
            'if [ "$sidecar_base" != "http://127.0.0.1:18080" ]; then',
            self.workflow,
        )
        self.assertIn("printf '%s/v1' \"${sidecar_base%/}\"", self.workflow)

    def test_model_override_cannot_escape_the_gateway(self) -> None:
        """A dispatch payload cannot select a direct provider route."""
        self.assertIn("github.event.client_payload.strix_llm", self.workflow)
        self.assertIn(
            "Strix model overrides are limited to contextual-orchestrator/orchestrator/free",
            self.workflow,
        )
        for direct_route in ("nvidia_nim/*)", "openrouter/free", "openai-direct/gpt-5.4"):
            self.assertNotIn(direct_route, self.workflow)

    def test_private_gateway_scans_require_zdr_only_routing(self) -> None:
        """Private source never enters the gateway's non-ZDR fallback tier."""
        self.assertIn(
            "CONTEXTUAL_ORCHESTRATOR_REQUIRE_ZDR: ${{ steps.target_visibility.outputs.is_private }}",
            self.workflow,
        )

    def test_gateway_install_is_hash_locked_and_token_is_masked(self) -> None:
        """The vendored dependencies are hash locked and bearer logs are masked."""
        self.assertIn("--require-hashes", self.sidecar)
        self.assertIn(
            'requirements_lock="$ORCHESTRATOR_SOURCE/requirements.lock"',
            self.sidecar,
        )
        self.assertIn("::add-mask::%s", self.sidecar)

    def test_required_smoke_pins_the_gateway_default(self) -> None:
        """The bounded required-path smoke rejects a future direct-default regression."""
        self.assertIn("contextual-orchestrator Strix sidecar", self.smoke)
        self.assertIn("active_strix_models=", self.smoke)
        self.assertIn(
            '"$active_strix_models" = "contextual-orchestrator/orchestrator/free"',
            self.smoke,
        )
        self.assertIn("Strix does not resolve a direct provider outside the gateway", self.smoke)

    def test_required_smoke_rejects_invalid_sidecar_syntax(self) -> None:
        """Every shell input is parsed, not passed as an argument to one parse."""
        with self.subTest("malformed sidecar"):
            import tempfile

            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                (root / "scripts/ci").mkdir(parents=True)
                (root / ".github/workflows").mkdir(parents=True)
                (root / "docs/adr").mkdir(parents=True)
                for source in (
                    ROOT / "scripts/ci/strix_required_workflow_smoke.sh",
                    ROOT / "scripts/ci/strix_quick_gate.sh",
                    ROOT / "scripts/ci/test_strix_quick_gate.sh",
                    SIDECAR,
                    TOKEN_LOADER,
                ):
                    shutil.copy2(source, root / source.relative_to(ROOT))
                shutil.copy2(WORKFLOW, root / WORKFLOW.relative_to(ROOT))
                shutil.copy2(ROOT / "AGENTS.md", root / "AGENTS.md")
                decision_record = (
                    ROOT / "docs/adr/0003-contextual-orchestrator-vendored-free-zdr.md"
                )
                shutil.copy2(decision_record, root / decision_record.relative_to(ROOT))
                copied_sidecar = root / SIDECAR.relative_to(ROOT)
                copied_sidecar.write_text(
                    copied_sidecar.read_text(encoding="utf-8") + "\nif broken; then\n",
                    encoding="utf-8",
                )

                result = subprocess.run(
                    ["bash", str(root / "scripts/ci/strix_required_workflow_smoke.sh")],
                    cwd=root,
                    text=True,
                    capture_output=True,
                    check=False,
                )

        output = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0, output)
        self.assertIn("Strix gate script must pass bash syntax checks", output)
        self.assertIn("contextual_orchestrator_review_sidecar.sh", output)
        self.assertNotIn("load_contextual_orchestrator_token.sh", output)


if __name__ == "__main__":
    unittest.main()
