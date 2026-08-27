#!/usr/bin/env python3
"""Contract tests for the read-only OpenCode gateway migration."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/opencode-review-dispatch.yml"


class ReadOnlyGatewayContractTests(unittest.TestCase):
    """Keep the read-only reviewer behind the central gateway only."""

    @classmethod
    def setUpClass(cls) -> None:
        """Load the workflow text once for focused assertions."""
        cls.text = WORKFLOW.read_text(encoding="utf-8")
        cls.pool_start = cls.text.index(
            "      - name: Run OpenCode PR Review model pool"
        )
        cls.pool_end = cls.text.index(
            "      - name: Exchange OpenCode app token for review writes",
            cls.pool_start,
        )
        cls.pool = cls.text[cls.pool_start : cls.pool_end]

    def test_sidecar_precedes_read_only_pool(self) -> None:
        """Provision the trusted gateway before the read-only model process."""
        sidecar = self.text.index(
            "      - name: Provision contextual-orchestrator read-only review gateway"
        )
        self.assertLess(sidecar, self.pool_start)
        sidecar_text = self.text[sidecar : self.pool_start]
        for secret in (
            "BYTEZ_API_KEY",
            "NVIDIA_NIM_API_KEY",
            "NVIDIA_NIM_API_KEY_SUB",
            "OPENROUTER_API_KEY",
            "OPENAI_API_KEY",
        ):
            self.assertIn(f"          {secret}:", sidecar_text)
        self.assertIn(
            "contextual_orchestrator_review_sidecar.sh", sidecar_text
        )

    def test_pool_consumes_only_gateway_model(self) -> None:
        """Do not expose provider credentials or pinned models to OpenCode."""
        self.assertIn(
            'OPENCODE_MODEL_CANDIDATES: "contextual-orchestrator/orchestrator/free"',
            self.pool,
        )
        for forbidden in (
            "STRIX_GITHUB_MODELS_TOKEN:",
            "OPENCODE_API_KEY:",
            "OPENAI_API_KEY:",
            "NVIDIA_API_KEY:",
            "NVIDIA_NIM_API_KEY:",
            "OPENROUTER_API_KEY:",
            "nvidia-nim/",
            "github-models/",
            "openrouter/",
            "openai/gpt-",
            "opencode/gpt-",
        ):
            self.assertNotIn(forbidden, self.pool)

    def test_isolated_config_is_reduced_to_gateway_provider(self) -> None:
        """Remove direct provider routes from the isolated OpenCode config."""
        self.assertIn(
            'config["enabled_providers"] = ["contextual-orchestrator"]',
            self.text,
        )
        self.assertIn(
            'config["provider"] = {"contextual-orchestrator": gateway_provider}',
            self.text,
        )
        self.assertIn(
            '"baseURL": "{env:CONTEXTUAL_ORCHESTRATOR_BASE_URL}"',
            self.text,
        )
        self.assertIn(
            '"apiKey": "{env:CONTEXTUAL_ORCHESTRATOR_TOKEN}"',
            self.text,
        )
        self.assertIn('"orchestrator/free": {', self.text)
        self.assertIn('"reasoningEffort": "high"', self.text)


if __name__ == "__main__":
    unittest.main()
