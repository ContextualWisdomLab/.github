"""Regression contract for the gate script's generic API-base resolver.

`scripts/ci/strix_quick_gate.sh` implements a general-purpose model/API-base
resolver that can, in principle, route direct-provider models (NVIDIA NIM,
OpenRouter, GitHub Models, direct OpenAI). The central required workflow
(`strix.yml`) never invokes it with anything other than the local
contextual-orchestrator gateway's `orchestrator/auto` or `orchestrator/free`
virtual model — the resolved pool depends only on `free_family_diversity`
evidence (see docs/adr/0020-strix-orchestrator-free-pool.md), never on
external input. `STRIX_FALLBACK_MODELS: ""` and the dispatch-override
allowlist in `strix.yml`'s "Gate Strix secrets" step structurally prevent any
direct provider from being selected (see `WorkflowUsesContextualOrchestrator`
below).
This file pins the resolver's own correctness as defense in depth (were a
non-gateway model ever passed to it, a cross-provider fallback must never
silently inherit another provider's API base — e.g. routing an OpenAI model
through the NVIDIA NIM edge would yield a plain-text gateway 404 instead of
OpenAI responses), not a description of a live fallback chain Strix's
required path actually uses today.

The resolver must therefore prefer an explicit
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


def _resolve_child_model(model: str, api_base: str) -> tuple[int, str]:
    """Execute the production child-model qualifier for one gateway route."""

    gate_source = STRIX_GATE.read_text(encoding="utf-8")
    helper_sources = [
        _function_block(gate_source, "is_contextual_orchestrator_model"),
        _function_block(gate_source, "is_contextual_orchestrator_api_base"),
        _function_block(gate_source, "is_github_models_api_base"),
        _function_block(gate_source, "child_model_for_api_base"),
    ]
    with tempfile.TemporaryDirectory(prefix="strix-gateway-child-model-") as temp_dir:
        completed = subprocess.run(
            [
                "bash",
                "-c",
                "\n".join(
                    [
                        "set -euo pipefail",
                        *helper_sources,
                        'child_model_for_api_base "$1" "$2"',
                    ]
                ),
                "strix-child-model",
                model,
                api_base,
            ],
            check=False,
            capture_output=True,
            text=True,
            env={
                "PATH": "/usr/bin:/bin:/usr/local/bin",
                "HOME": temp_dir,
            },
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
        """Both gateway pools accept only the pinned process-local HTTP base.

        docs/adr/0020-strix-orchestrator-free-pool.md: orchestrator/auto is
        the permanent, evidence-gated fallback alongside orchestrator/free,
        not a retired route -- both must resolve identically here.
        """

        for model in (
            "orchestrator/free",
            "contextual-orchestrator/orchestrator/free",
            "orchestrator/auto",
            "contextual-orchestrator/orchestrator/auto",
        ):
            with self.subTest(model=model):
                rc, api_base = _resolve_api_base(
                    {"LLM_API_BASE_FILE": "http://127.0.0.1:18080/v1"},
                    model,
                )
                self.assertEqual(rc, 0)
                self.assertEqual(api_base, "http://127.0.0.1:18080/v1")

        rc, _ = _resolve_api_base(
            {"LLM_API_BASE_FILE": "http://127.0.0.1:18081/v1"},
            "orchestrator/free",
        )
        self.assertEqual(rc, 2)

        rc, _ = _resolve_api_base(
            {"LLM_API_BASE_FILE": "http://127.0.0.1:18081/v1"},
            "orchestrator/auto",
        )
        self.assertEqual(rc, 2)

        rc, _ = _resolve_api_base(
            {"LLM_API_BASE_FILE": "http://127.0.0.1:18080/v1"},
            "orchestrator/unknown",
        )
        self.assertEqual(rc, 2)

    def test_gateway_child_model_preserves_selected_virtual_pool(self) -> None:
        """LiteLLM qualification must not rewrite the selected free pool."""

        expected_child_models = {
            "orchestrator/free": "openai/orchestrator/free",
            "contextual-orchestrator/orchestrator/free": "openai/orchestrator/free",
            "orchestrator/auto": "openai/orchestrator/auto",
            "contextual-orchestrator/orchestrator/auto": "openai/orchestrator/auto",
        }
        for model, expected_child_model in expected_child_models.items():
            with self.subTest(model=model):
                rc, child_model = _resolve_child_model(
                    model,
                    "http://127.0.0.1:18080/v1",
                )
                self.assertEqual(rc, 0)
                self.assertEqual(child_model, expected_child_model)

    def test_manual_status_job_has_status_write_permission(self) -> None:
        """OIDC target-app exchange may request the target commit status scope."""

        workflow = STRIX_WORKFLOW.read_text(encoding="utf-8")
        job = workflow.split("  publish-manual-pr-evidence-status:", 1)[1]
        self.assertIn("      statuses: write", job.split("    steps:", 1)[0])


if __name__ == "__main__":
    unittest.main()
