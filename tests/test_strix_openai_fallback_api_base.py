"""Regression contract for direct-OpenAI fallback API-base routing.

When the Strix primary provider is NVIDIA NIM (or OpenRouter / GitHub Models),
the workflow's ``LLM_API_BASE_FILE`` points at that provider's endpoint. A
cross-provider fallback to ``openai-direct/gpt-5.4`` must never inherit that
base: routing an OpenAI model through the NVIDIA NIM edge yields a plain-text
gateway 404 ("404 page not found") instead of OpenAI responses, so the final
contracted fallback could never complete a scan.

The gate must therefore prefer an explicit
``STRIX_OPENAI_FALLBACK_API_BASE_FILE`` for explicit direct-OpenAI models, and
    fall back to a caller-supplied ``LLM_API_BASE_FILE`` for standalone custom
    endpoints, or to litellm's default OpenAI endpoint when no base is supplied.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
STRIX_GATE = REPOSITORY_ROOT / "scripts" / "ci" / "strix_quick_gate.sh"
STRIX_MODEL_UTILS = REPOSITORY_ROOT / "scripts" / "ci" / "strix_model_utils.sh"
STRIX_WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "strix.yml"
OPENAI_FALLBACK_BASE = "https://api.openai.com/v1"
OPENROUTER_FALLBACK_BASE = "https://openrouter.ai/api/v1"


def _function_block(source: str, function_name: str) -> str:
    """Return one top-level Bash function, including its closing brace."""

    match = re.search(
        rf"(?ms)^{re.escape(function_name)}\(\) \{{\n.*?^\}}\n",
        source,
    )
    if match is None:
        raise AssertionError(f"missing Bash function: {function_name}")
    return match.group(0)


def _resolver_helpers() -> list[str]:
    """Collect every helper the production API-base resolver depends on."""

    gate_source = STRIX_GATE.read_text(encoding="utf-8")
    utils_source = STRIX_MODEL_UTILS.read_text(encoding="utf-8")
    helper_names = (
        ("is_vertex_model", gate_source),
        ("is_contextual_orchestrator_model", gate_source),
        ("is_contextual_orchestrator_api_base", gate_source),
        ("is_github_models_model", gate_source),
        ("is_github_models_api_base", gate_source),
        ("is_known_foreign_provider_api_base", gate_source),
        ("is_github_models_api_compatible_model", gate_source),
        ("is_explicit_openai_model", gate_source),
        ("normalize_model", utils_source),
        ("resolve_trusted_input_file", gate_source),
        ("trim_whitespace", utils_source),
    )
    helpers: list[str] = []
    for name, source in helper_names:
        try:
            helpers.append(_function_block(source, name))
        except AssertionError as exc:  # pragma: no cover - shape drift guard
            raise AssertionError(f"resolver helper missing: {name}") from exc
    return helpers


def _resolve_api_base(env: dict[str, str], model: str) -> tuple[int, str]:
    """Execute the production API-base resolver for one model and env."""

    gate_source = STRIX_GATE.read_text(encoding="utf-8")
    resolver_source = _function_block(gate_source, "resolved_llm_api_base_for_model")
    helper_sources = _resolver_helpers()
    with tempfile.TemporaryDirectory(prefix="strix-openai-fallback-base-") as temp_dir:
        base_path = Path(temp_dir) / "primary_base.txt"
        if "LLM_API_BASE_FILE" in env:
            base_path.write_text(env["LLM_API_BASE_FILE"], encoding="utf-8")
            env = {**env, "LLM_API_BASE_FILE": str(base_path)}
        fallback_path = Path(temp_dir) / "openai_fallback_api_base.txt"
        if "STRIX_OPENAI_FALLBACK_API_BASE_FILE" in env:
            fallback_path.write_text(
                env["STRIX_OPENAI_FALLBACK_API_BASE_FILE"],
                encoding="utf-8",
            )
            env = {
                **env,
                "STRIX_OPENAI_FALLBACK_API_BASE_FILE": str(fallback_path),
            }
        openrouter_path = Path(temp_dir) / "openrouter_fallback_api_base.txt"
        if "STRIX_OPENROUTER_FALLBACK_API_BASE_FILE" in env:
            openrouter_path.write_text(
                env["STRIX_OPENROUTER_FALLBACK_API_BASE_FILE"], encoding="utf-8"
            )
            env = {
                **env,
                "STRIX_OPENROUTER_FALLBACK_API_BASE_FILE": str(openrouter_path),
            }
        github_models_path = Path(temp_dir) / "github_models_api_base.txt"
        if "STRIX_GITHUB_MODELS_API_BASE_FILE" in env:
            github_models_path.write_text(
                env["STRIX_GITHUB_MODELS_API_BASE_FILE"],
                encoding="utf-8",
            )
            env = {
                **env,
                "STRIX_GITHUB_MODELS_API_BASE_FILE": str(github_models_path),
            }
        script_lines = [
            "set -euo pipefail",
            f'STRIX_INPUT_FILE_ROOT="{temp_dir}"',
            *helper_sources,
            resolver_source,
        ]
        command_env = {
            key: value
            for key, value in env.items()
            if key in {
                "LLM_API_BASE_FILE",
                "STRIX_GITHUB_MODELS_API_BASE_FILE",
                "STRIX_OPENAI_FALLBACK_API_BASE_FILE",
                "STRIX_OPENROUTER_FALLBACK_API_BASE_FILE",
            }
        }
        completed = subprocess.run(
            [
                "bash",
                "-c",
                "\n".join([*script_lines, 'resolved_llm_api_base_for_model "$1"']),
                "strix-resolver",
                model,
            ],
            check=False,
            capture_output=True,
            text=True,
            env={
                "PATH": "/usr/bin:/bin:/usr/local/bin",
                "HOME": temp_dir,
                **command_env,
            },
        )
    return completed.returncode, completed.stdout.strip()


def _child_model(env_model: str, api_base: str) -> tuple[int, str]:
    """Execute the production child-model qualifier for one gateway model."""

    gate_source = STRIX_GATE.read_text(encoding="utf-8")
    helper_names = (
        "is_contextual_orchestrator_model",
        "is_contextual_orchestrator_api_base",
        "is_github_models_api_base",
    )
    helper_sources = [
        _function_block(gate_source, name)
        for name in helper_names
    ]
    child_source = _function_block(gate_source, "child_model_for_api_base")
    completed = subprocess.run(
        [
            "bash",
            "-c",
            "\n".join(
                [
                    "set -euo pipefail",
                    *helper_sources,
                    child_source,
                    'child_model_for_api_base "$1" "$2"',
                ]
            ),
            "strix-child-model",
            env_model,
            api_base,
        ],
        check=False,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin"},
    )
    return completed.returncode, completed.stdout.strip()


class ExplicitOpenAIFallbackRouting(unittest.TestCase):
    """Direct-OpenAI fallbacks must not inherit the primary provider base."""

    def test_nvidia_primary_with_override_routes_to_openai(self) -> None:
        """openai-direct/gpt-5.4 uses the explicit OpenAI API base file."""

        rc, api_base = _resolve_api_base(
            {
                "LLM_API_BASE_FILE": "https://integrate.api.nvidia.com/v1",
                "STRIX_OPENAI_FALLBACK_API_BASE_FILE": OPENAI_FALLBACK_BASE,
            },
            "openai-direct/gpt-5.4",
        )
        self.assertEqual(rc, 0)
        self.assertEqual(api_base, OPENAI_FALLBACK_BASE)

    def test_standalone_custom_base_is_honored_without_override(self) -> None:
        """A standalone caller's explicit custom endpoint remains effective."""

        rc, api_base = _resolve_api_base(
            {"LLM_API_BASE_FILE": "https://api.example.com/v1"},
            "openai-direct/gpt-5.4",
        )
        self.assertEqual(rc, 0)
        self.assertEqual(api_base, "https://api.example.com/v1")

    def test_nvidia_base_is_not_inherited_without_override(self) -> None:
        """A cross-provider fallback never inherits the NVIDIA NIM base."""

        rc, api_base = _resolve_api_base(
            {"LLM_API_BASE_FILE": "https://integrate.api.nvidia.com/v1"},
            "openai-direct/gpt-5.4",
        )
        self.assertEqual(rc, 0)
        self.assertEqual(api_base, "")

    def test_direct_openai_without_any_base_uses_default_openai(self) -> None:
        """With no base file, LiteLLM still selects the native OpenAI endpoint."""

        rc, api_base = _resolve_api_base({}, "openai-direct/gpt-5.4")
        self.assertEqual(rc, 0)
        self.assertEqual(api_base, "")

    def test_github_models_base_is_not_inherited_without_override(self) -> None:
        """A cross-provider fallback never inherits GitHub Models routing."""

        rc, api_base = _resolve_api_base(
            {"LLM_API_BASE_FILE": "https://models.github.ai/inference"},
            "openai-direct/gpt-5.4",
        )
        self.assertEqual(rc, 0)
        self.assertEqual(api_base, "")

    def test_primary_provider_models_keep_their_base(self) -> None:
        """NVIDIA NIM primary attempts still resolve through the NIM edge."""

        rc, api_base = _resolve_api_base(
            {"LLM_API_BASE_FILE": "https://integrate.api.nvidia.com/v1"},
            "nvidia_nim/nvidia/nemotron-3-super-120b-a12b",
        )
        self.assertEqual(rc, 0)
        self.assertEqual(api_base, "https://integrate.api.nvidia.com/v1")

    def test_nvidia_primary_routes_openrouter_fallback_to_openrouter(self) -> None:
        """OpenRouter fallback never inherits the NVIDIA NIM endpoint."""

        rc, api_base = _resolve_api_base(
            {
                "LLM_API_BASE_FILE": "https://integrate.api.nvidia.com/v1",
                "STRIX_OPENROUTER_FALLBACK_API_BASE_FILE": OPENROUTER_FALLBACK_BASE,
            },
            "openrouter/free",
        )
        self.assertEqual(rc, 0)
        self.assertEqual(api_base, OPENROUTER_FALLBACK_BASE)

    def test_github_models_fallback_keeps_github_models_base(self) -> None:
        """github_models/* fallbacks keep their dedicated inference endpoint."""

        rc, api_base = _resolve_api_base(
            {
                "LLM_API_BASE_FILE": "https://integrate.api.nvidia.com/v1",
                "STRIX_GITHUB_MODELS_API_BASE_FILE": "https://models.github.ai/inference",
            },
            "github_models/openai/gpt-5.4",
        )
        self.assertEqual(rc, 0)
        self.assertEqual(api_base, "https://models.github.ai/inference")

    def test_invalid_https_override_is_configuration_failure(self) -> None:
        """A non-https override fails configuration instead of scanning."""

        rc, _ = _resolve_api_base(
            {
                "LLM_API_BASE_FILE": "https://integrate.api.nvidia.com/v1",
                "STRIX_OPENAI_FALLBACK_API_BASE_FILE": "http://api.example.com/v1",
            },
            "openai-direct/gpt-5.4",
        )
        self.assertEqual(rc, 2)


class ContextualOrchestratorChildModel(unittest.TestCase):
    """Gateway child models must preserve the actual orchestrator pool name."""

    def test_provider_prefixed_gateway_model_is_not_double_qualified(self) -> None:
        """A provider-qualified model becomes exactly one OpenAI-qualified id."""

        for model, expected in (
            (
                "contextual-orchestrator/orchestrator/auto",
                "openai/orchestrator/auto",
            ),
            (
                "contextual-orchestrator/orchestrator/free",
                "openai/orchestrator/free",
            ),
        ):
            with self.subTest(model=model):
                rc, child_model = _child_model(
                    model,
                    "http://127.0.0.1:18080/v1",
                )
                self.assertEqual(rc, 0)
                self.assertEqual(child_model, expected)


class WorkflowUsesContextualOrchestrator(unittest.TestCase):
    """The required workflow must expose only the local gateway route."""

    def test_workflow_does_not_provision_direct_provider_fallbacks(self) -> None:
        workflow = STRIX_WORKFLOW.read_text(encoding="utf-8")
        self.assertEqual(workflow.count("secrets.OPENAI_API_KEY"), 1)
        self.assertEqual(workflow.count("secrets.OPENROUTER_API_KEY"), 1)
        self.assertNotIn("secrets.GCP_SA_KEY", workflow)
        self.assertNotIn("STRIX_OPENAI_FALLBACK_API_BASE_FILE", workflow)
        self.assertNotIn("STRIX_GITHUB_MODELS_KEY_FILE", workflow)

    def test_workflow_does_not_configure_an_external_fallback(self) -> None:
        """The gateway owns model discovery and provider failover."""

        workflow = STRIX_WORKFLOW.read_text(encoding="utf-8")
        fallback_expression = next(
            line for line in workflow.splitlines() if "STRIX_FALLBACK_MODELS:" in line
        )
        self.assertEqual(fallback_expression.strip(), 'STRIX_FALLBACK_MODELS: ""')
        self.assertIn("Provision contextual-orchestrator Strix sidecar", workflow)

    def test_workflow_gateway_base_is_the_only_http_exception(self) -> None:
        """The local sidecar is accepted without allowing arbitrary HTTP bases."""

        rc, api_base = _resolve_api_base(
            {"LLM_API_BASE_FILE": "http://127.0.0.1:18080/v1"},
            "orchestrator/free",
        )
        self.assertEqual(rc, 0)
        self.assertEqual(api_base, "http://127.0.0.1:18080/v1")

        rc, _ = _resolve_api_base(
            {"LLM_API_BASE_FILE": "http://127.0.0.1:18081/v1"},
            "orchestrator/free",
        )
        self.assertEqual(rc, 2)

    def test_workflow_gateway_base_accepts_auto_pool_model(self) -> None:
        """The auto pool (CONTEXTUAL_ORCHESTRATOR_POOL=auto) is a recognized
        contextual-orchestrator model, not just the legacy free pool.

        Regression for the #1401 rename (orchestrator/free -> orchestrator/auto
        in strix.yml) that left is_contextual_orchestrator_model() only
        recognizing the old free-pool spelling, which made every PR-scoped
        Strix scan fail its https-only LLM_API_BASE check against the pinned
        http://127.0.0.1:18080 loopback sidecar.
        """

        rc, api_base = _resolve_api_base(
            {"LLM_API_BASE_FILE": "http://127.0.0.1:18080/v1"},
            "orchestrator/auto",
        )
        self.assertEqual(rc, 0)
        self.assertEqual(api_base, "http://127.0.0.1:18080/v1")

        rc, _ = _resolve_api_base(
            {"LLM_API_BASE_FILE": "http://127.0.0.1:18081/v1"},
            "orchestrator/auto",
        )
        self.assertEqual(rc, 2)

    def test_manual_status_job_has_status_write_permission(self) -> None:
        """OIDC target-app exchange may request the target commit status scope."""

        workflow = STRIX_WORKFLOW.read_text(encoding="utf-8")
        job = workflow.split("  publish-manual-pr-evidence-status:", 1)[1]
        self.assertIn("      statuses: write", job.split("    steps:", 1)[0])


if __name__ == "__main__":
    unittest.main()
