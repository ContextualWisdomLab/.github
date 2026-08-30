"""Contracts for routing default Strix scans through contextual-orchestrator."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import textwrap
import unittest

from tests.test_required_workflow_queue_contract import workflow_step, workflow_text

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
        self.assertIn("STRIX_MODEL: contextual-orchestrator/orchestrator/auto", self.workflow)
        self.assertIn("provider_mode=contextual_orchestrator", self.workflow)
        self.assertIn("STRIX_FALLBACK_MODELS: \"\"", self.workflow)
        self.assertNotIn(
            "steps.resolve_nvidia_models.outputs.primary || 'gpt-5.4'",
            self.workflow,
        )

    def test_sidecar_boots_the_auto_catalog_regardless_of_resolved_model(self) -> None:
        """The sidecar always loads the richer auto catalog (real fallback capacity).

        docs/adr/0020-strix-orchestrator-free-pool.md: if the sidecar booted
        "free"-only, no priced agents would ever be loaded, and a later
        request for "orchestrator/auto" would silently resolve to the exact
        same single-family free catalog under a different name -- a fake
        fallback that would defeat the diversity gate entirely.
        """
        self.assertIn("CONTEXTUAL_ORCHESTRATOR_POOL: auto", self.workflow)
        self.assertNotIn("CONTEXTUAL_ORCHESTRATOR_POOL: free", self.workflow)

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
            "Strix model overrides are limited to contextual-orchestrator/orchestrator/auto",
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

    def _run_resolve_model_step(
        self, *, evidence: object | None, evidence_missing: bool = False
    ) -> subprocess.CompletedProcess[str]:
        """Execute the workflow's own "Resolve Strix model" step in isolation.

        Extracts the step's ``run:`` block directly out of the tracked
        ``strix.yml`` text (no reimplementation to drift from the real
        gate) and runs it as bash, the same behavioral-testing pattern
        ``test_noema_orchestrator_workflow_contract.py`` and
        ``test_required_workflow_queue_contract.py`` already use for the
        neighboring "Gate Strix secrets" step.

        Args:
            evidence: JSON-serializable payload written as the sidecar's
                policy report, or ``None`` to write literally malformed JSON.
            evidence_missing: If True, point ``CONTEXTUAL_ORCHESTRATOR_EVIDENCE``
                at a nonexistent path instead of writing any file.

        Returns:
            The completed bash subprocess, with ``$GITHUB_OUTPUT`` captured
            in ``.github_output`` (an added attribute) as parsed key/value
            lines for convenience.
        """
        bash_executable = shutil.which("bash") or "/bin/bash"
        script = textwrap.dedent(
            workflow_step(
                workflow_text("strix.yml"),
                "Resolve Strix model from free-route diversity evidence",
            ).split("        run: |\n", 1)[1]
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "github_output"
            output_path.write_text("", encoding="utf-8")
            if evidence_missing:
                evidence_path = Path(temp_dir) / "does-not-exist.json"
            else:
                evidence_path = Path(temp_dir) / "policy-report.json"
                if evidence is None:
                    evidence_path.write_text("not valid json", encoding="utf-8")
                else:
                    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
            env = {
                **os.environ,
                "GITHUB_OUTPUT": str(output_path),
                "GATE_STRIX_MODEL": "contextual-orchestrator/orchestrator/auto",
                "CONTEXTUAL_ORCHESTRATOR_EVIDENCE": str(evidence_path),
            }
            result = subprocess.run(  # noqa: S603
                [bash_executable, "-c", script],
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            result.github_output = dict(  # type: ignore[attr-defined]
                line.split("=", 1)
                for line in output_path.read_text(encoding="utf-8").splitlines()
                if "=" in line
            )
        return result

    def test_diversity_of_zero_or_one_stays_on_orchestrator_auto(self) -> None:
        """Negative fixture: low diversity must never weaken Strix to the free pool.

        This is the exact regression the human review on #1437 required:
        "a negative fixture proves diversity 0/1 retains orchestrator/auto
        rather than weakening availability." Diversity 0 (no free routes at
        all) and 1 (the 2026-08-29 single-family finding recorded in
        ADR-0003) must both resolve to orchestrator/auto, never
        orchestrator/free.
        """
        for diversity in (0, 1):
            with self.subTest(free_family_diversity=diversity):
                result = self._run_resolve_model_step(
                    evidence={"free_family_diversity": diversity}
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(
                    result.github_output["strix_model"],  # type: ignore[attr-defined]
                    "contextual-orchestrator/orchestrator/auto",
                )
                self.assertEqual(
                    result.github_output["free_family_diversity"],  # type: ignore[attr-defined]
                    str(diversity),
                )

    def test_diversity_of_two_or_more_upgrades_to_orchestrator_free(self) -> None:
        """At least two independent families is exactly the ADR-0020 threshold."""
        for diversity in (2, 3, 5):
            with self.subTest(free_family_diversity=diversity):
                result = self._run_resolve_model_step(
                    evidence={"free_family_diversity": diversity}
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(
                    result.github_output["strix_model"],  # type: ignore[attr-defined]
                    "contextual-orchestrator/orchestrator/free",
                )

    def test_missing_or_malformed_evidence_fails_closed_to_auto(self) -> None:
        """Any uncertainty about the evidence must never upgrade to the free pool."""
        cases = {
            "missing_file": {"evidence": {}, "evidence_missing": True},
            "malformed_json": {"evidence": None},
            "missing_field": {"evidence": {"other_field": 4}},
            "non_integer": {"evidence": {"free_family_diversity": "many"}},
            "negative_integer": {"evidence": {"free_family_diversity": -1}},
            "boolean": {"evidence": {"free_family_diversity": True}},
        }
        for case_name, kwargs in cases.items():
            with self.subTest(case=case_name):
                result = self._run_resolve_model_step(**kwargs)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(
                    result.github_output["strix_model"],  # type: ignore[attr-defined]
                    "contextual-orchestrator/orchestrator/auto",
                )
                self.assertEqual(
                    result.github_output["free_family_diversity"],  # type: ignore[attr-defined]
                    "0",
                )
                self.assertIn("::warning::", result.stderr)

    def test_required_smoke_pins_the_gateway_default(self) -> None:
        """The bounded required-path smoke rejects a future direct-default regression."""
        self.assertIn("contextual-orchestrator Strix sidecar", self.smoke)
        self.assertIn("active_strix_models=", self.smoke)
        self.assertIn(
            '"$active_strix_models" = "contextual-orchestrator/orchestrator/auto"',
            self.smoke,
        )
        self.assertIn("Strix does not resolve a direct provider outside the gateway", self.smoke)

    def test_required_smoke_asserts_the_evidence_gated_conditional_structurally(self) -> None:
        """The smoke test verifies the diversity gate's structure, not just a string.

        This is the "extend, never weaken" contract the human review on
        #1437 required: the old bare-pin assertions
        ("must define exactly one active provider-diverse auto default
        model" / "must not retain the free default route") are gone because
        they assumed a static, unconditional pin, but they are replaced with
        an equivalent-or-stronger structural check on the new conditional
        mechanism -- never simply deleted to get a green run.
        """
        self.assertIn("assert_free_pool_gated_by_diversity", self.smoke)
        self.assertIn(
            "CONTEXTUAL_ORCHESTRATOR_POOL: auto",
            self.smoke,
        )
        self.assertIn(
            "Strix sidecar must not boot free-only",
            self.smoke,
        )
        self.assertIn("free_family_diversity", self.smoke)
        # The exact regressions this task forbade: a bare unconditional
        # free pin, and deleting the safety net without an equivalent
        # replacement.
        self.assertNotIn(
            '"$active_strix_models" = "contextual-orchestrator/orchestrator/free"',
            self.smoke,
        )

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
