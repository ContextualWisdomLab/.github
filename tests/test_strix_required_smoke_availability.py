"""Regression tests for bounded Strix required-smoke availability."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SMOKE = ROOT / "scripts/ci/strix_required_workflow_smoke.sh"
WORKFLOW = ROOT / ".github/workflows/strix.yml"
SIDECAR = ROOT / "scripts/ci/contextual_orchestrator_review_sidecar.sh"
TOKEN_LOADER = ROOT / "scripts/ci/load_contextual_orchestrator_token.sh"
GATE = ROOT / "scripts/ci/strix_quick_gate.sh"
GATE_TEST = ROOT / "scripts/ci/test_strix_quick_gate.sh"
DECISION_RECORD = ROOT / "docs/adr/0003-contextual-orchestrator-vendored-free-zdr.md"
AGENT_POLICY = ROOT / "AGENTS.md"


class StrixRequiredSmokeAvailabilityTest(unittest.TestCase):
    """Keep consumer scans independent from non-executable guidance wording."""

    @staticmethod
    def _copy_smoke_fixture(root: Path) -> None:
        """Copy real smoke dependencies plus the separately checked guidance."""
        for source in (
            SMOKE,
            WORKFLOW,
            SIDECAR,
            TOKEN_LOADER,
            GATE,
            GATE_TEST,
            DECISION_RECORD,
            AGENT_POLICY,
        ):
            destination = root / source.relative_to(ROOT)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)

    def test_agent_guidance_prose_cannot_block_consumer_scans(self) -> None:
        """Changing AGENTS prose must not stop an otherwise valid Strix scan."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._copy_smoke_fixture(root)
            (root / "AGENTS.md").write_text(
                "# Agent guidance\n\nThis prose is not an executable Strix contract.\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                ["bash", str(root / SMOKE.relative_to(ROOT))],
                cwd=root,
                text=True,
                capture_output=True,
                check=False,
                timeout=10,
            )

        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("Strix required workflow smoke test passed.", output)

    def test_repository_guidance_still_documents_the_free_route(self) -> None:
        """Central quality tests, not consumer runtime, keep guidance aligned."""
        paragraphs = (
            " ".join(paragraph.split())
            for paragraph in AGENT_POLICY.read_text(encoding="utf-8").split("\n\n")
        )
        self.assertTrue(
            any(
                "Strix" in paragraph
                and "zero-cost" in paragraph
                and "`orchestrator/free`" in paragraph
                for paragraph in paragraphs
            ),
            "AGENTS.md must document Strix on the zero-cost orchestrator/free route",
        )


if __name__ == "__main__":
    unittest.main()
