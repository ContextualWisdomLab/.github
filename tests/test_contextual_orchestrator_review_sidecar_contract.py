"""Regression tests for the vendored contextual-orchestrator review sidecar."""

from __future__ import annotations

import json
import os
import re
import runpy
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
SIDECAR = ROOT / "scripts" / "ci" / "contextual_orchestrator_review_sidecar.sh"
LAUNCHER = ROOT / "scripts" / "ci" / "contextual_orchestrator_review_launcher.py"
POLICY = ROOT / "scripts" / "ci" / "contextual_orchestrator_review_policy.py"
NOEMA = ROOT / ".github" / "workflows" / "noema-review.yml"
STRIX = ROOT / ".github" / "workflows" / "strix.yml"
AUTOFIX = ROOT / ".github" / "workflows" / "pr-review-autofix.yml"
REQUIRED_OPENCODE = ROOT / ".github" / "workflows" / "required-opencode-review.yml"
OPENCODE_DISPATCH = ROOT / ".github" / "workflows" / "opencode-review-dispatch.yml"
OPENCODE_CONFIG = ROOT / "opencode.jsonc"


def _read(path: Path) -> str:
    """Return one UTF-8 repository file."""
    return path.read_text(encoding="utf-8")


def test_sidecar_registers_all_five_provider_secrets() -> None:
    """The launcher receives the complete org credential inventory."""
    text = _read(LAUNCHER)
    for name in (
        "BYTEZ_API_KEY",
        "NVIDIA_NIM_API_KEY",
        "NVIDIA_NIM_API_KEY_SUB",
        "OPENROUTER_API_KEY",
        "OPENAI_API_KEY",
    ):
        assert name in text
    assert "register_review_credentials" in text


def test_sidecar_shell_requires_at_least_one_provider_secret() -> None:
    """The shell wrapper does not boot an empty provider inventory."""
    text = _read(SIDECAR)
    for name in (
        "BYTEZ_API_KEY",
        "NVIDIA_NIM_API_KEY",
        "NVIDIA_NIM_API_KEY_SUB",
        "OPENROUTER_API_KEY",
        "OPENAI_API_KEY",
    ):
        assert name in text
    assert "at least one of BYTEZ_API_KEY" in text


def test_sidecar_uses_pinned_orchestrator_and_hashed_requirements() -> None:
    """The review runtime is a pinned, hash-verified vendored dependency."""
    text = _read(SIDECAR)
    assert 'ORCHESTRATOR_PIN_SHA="${ORCHESTRATOR_PIN_SHA:-' in text
    assert 'requirements_lock="$ORCHESTRATOR_SOURCE/requirements.lock"' in text
    assert "--require-hashes" in text
    assert "--no-deps" in text
    assert 'git -C "$ORCHESTRATOR_SOURCE" rev-parse HEAD' in text


def test_sidecar_routes_through_local_bearer_gateway() -> None:
    """Review consumers receive only the loopback gateway and bearer file."""
    text = _read(SIDECAR)
    assert 'ORCHESTRATOR_HOST="127.0.0.1"' in text
    assert 'ORCHESTRATOR_PORT="18080"' in text
    assert "CONTEXTUAL_ORCHESTRATOR_BASE_URL" in text
    assert "CONTEXTUAL_ORCHESTRATOR_TOKEN_FILE" in text
    assert "bearer.token" in text


def test_sidecar_masks_bearer_before_runner_work() -> None:
    """The raw bearer is masked before clone/install/startup can log it."""
    text = _read(SIDECAR)
    mask_index = text.index("::add-mask::%s")
    clone_index = text.index("git clone")
    assert mask_index < clone_index


def test_sidecar_gateway_body_limit_is_explicit() -> None:
    """The launcher has an explicit evidence-backed request envelope ceiling."""
    text = _read(LAUNCHER)
    assert "REVIEW_MAX_BODY_BYTES" in text
    assert "512 * 1024 * 1024" in text
    assert "max_body_bytes=REVIEW_MAX_BODY_BYTES" in text


def test_sidecar_startup_probe_checks_body_boundary() -> None:
    """The shell exercises over-limit and large legal requests before launch."""
    text = _read(SIDECAR)
    assert "accepted_size = 64 * 1024 + 1" in text
    assert '"Content-Length": str(REVIEW_MAX_BODY_BYTES + 1)' in text
    assert "assert response.status == 413" in text
    assert '"content": "x" * accepted_size' in text
    assert "assert large_status == 200" in text


def test_sidecar_preserves_long_tool_descriptions() -> None:
    """The startup contract forbids silent tool-description truncation."""
    text = _read(SIDECAR)
    assert "for description_length in (1025, 1026, 2000):" in text
    assert 'forwarded.encode("utf-8") == description.encode("utf-8")' in text


def test_sidecar_redacts_and_publishes_audit_evidence() -> None:
    """Discovery/policy/preflight evidence is retained without raw secrets."""
    text = _read(SIDECAR)
    assert "sanitize_contextual_orchestrator_sidecar_stream.py" in text
    assert "contextual-orchestrator-discovery.json" in text
    assert "contextual-orchestrator-agents.json" in text
    assert "contextual-orchestrator-policy.json" in text
    assert "contextual-orchestrator-preflight.json" in text
    assert "CONTEXTUAL_ORCHESTRATOR_EVIDENCE" in text


def test_sidecar_private_targets_require_zdr() -> None:
    """Private/internal workflow callers force the ZDR admission boundary."""
    text = _read(SIDECAR)
    assert "CONTEXTUAL_ORCHESTRATOR_REQUIRE_ZDR" in text
    assert "--require-zdr" in text


def test_required_workflows_use_free_gateway_model() -> None:
    """Noema, Strix, and required OpenCode all request orchestrator/free."""
    for path in (NOEMA, STRIX, REQUIRED_OPENCODE, OPENCODE_DISPATCH, AUTOFIX):
        text = _read(path)
        if "contextual_orchestrator_review_sidecar.sh" in text or "CONTEXTUAL_ORCHESTRATOR" in text:
            assert "orchestrator/free" in text


def test_shared_opencode_config_uses_gateway_default() -> None:
    """The repository-level OpenCode model defaults to the gateway route."""
    text = _read(OPENCODE_CONFIG)
    assert '"model": "contextual-orchestrator/orchestrator/free"' in text
    assert '"small_model": "contextual-orchestrator/orchestrator/free"' in text


def test_policy_is_importable_without_vendored_runtime() -> None:
    """The stdlib-only admission policy remains offline-testable."""
    namespace = runpy.run_path(str(POLICY))
    assert callable(namespace["build_zdr_prioritized_catalog"])


def test_launcher_uses_orchestrator_discovery_and_governed_pools() -> None:
    """Discovery, price evidence, and serving come from the vendored library."""
    text = _read(LAUNCHER)
    assert "from contextual_orchestrator.chat_capability import is_general_chat_agent_model_id" in text
    assert "from contextual_orchestrator.model_discovery import discover_all_models, free_discovered_models" in text
    assert "routable_discovered = _routable_discovered_models(discovered)" in text
    assert "free_discovered_models(routable_discovered)" in text
    assert 'getattr(model, "evidence_only", False)' in text
    assert 'getattr(model, "output_modalities", None)' in text
    assert 'isinstance(modalities, str)' in text
    assert '"text" in {str(modality).casefold() for modality in modalities}' in text
    assert "not _has_text_output(model)" in text
    assert 'model_id = getattr(model, "model_id", "")' in text

    launcher = runpy.run_path(str(LAUNCHER))
    has_text_output = launcher["_has_text_output"]
    assert has_text_output(SimpleNamespace(output_modalities="text"))
    assert has_text_output(SimpleNamespace(output_modalities=("text", "image")))
    assert not has_text_output(SimpleNamespace(output_modalities=("video",)))
    assert not has_text_output(SimpleNamespace())
    report_rows = launcher["_report_rows"]
    free = SimpleNamespace(
        provider_name="openrouter",
        model_id="free/model",
        agent_id="openrouter_free_model",
        output_modalities=("text",),
    )
    priced = SimpleNamespace(
        provider_name="openai",
        model_id="priced-model",
        agent_id="openai_priced_model",
        output_modalities=("text",),
        prompt_price_per_1k=0.002,
        completion_price_per_1k=0.008,
        currency_code="USD",
    )
    rows = report_rows([free, priced], frozenset({("openrouter", "free/model")}))
    assert [row["is_free"] for row in rows] == [True, False]
    assert rows[1]["prompt_price_per_1k"] == 0.002
    assert "from contextual_orchestrator.orchestrator import ModelClient, TaskOrchestrator, load_agents" in text
    assert "from contextual_orchestrator.server import SecurityConfig, serve" in text
    assert 'parser.add_argument("--pool", choices=("free",), default="free")' in text
    assert "orchestrator/{args.pool} would fail closed" in text
    assert "scripts.ci.contextual_orchestrator_review_policy" in text
    assert "from scripts.ci import zdr_policy" in text


def test_launcher_wraps_catalog_for_vendored_load_agents() -> None:
    """Persist the catalog envelope expected by the pinned orchestrator loader."""
    text = _read(LAUNCHER)
    assert 'json.dumps({"agents": result["agents"]}' in text
    assert 'json.dumps(result["agents"]' not in text


def test_launcher_requires_gateway_token_and_a_provider_credential() -> None:
    """The sidecar never boots without an auth token and a provider credential."""
    text = _read(LAUNCHER)
    assert "CONTEXTUAL_ORCHESTRATOR_TOKEN" in text
    assert "register_review_credentials" in text


def test_sidecar_exports_gateway_after_health_and_preflight() -> None:
    """The wrapper exports consumers only after sidecar readiness evidence."""
    text = _read(SIDECAR)
    health_index = text.index("/healthz")
    evidence_index = text.index("CONTEXTUAL_ORCHESTRATOR_EVIDENCE")
    assert health_index < evidence_index


def test_sidecar_has_no_fixed_model_inference_timeout() -> None:
    """The central wrapper does not invent a wall-clock inference deadline."""
    text = _read(SIDECAR)
    lowered = text.casefold()
    assert "timeout " not in lowered
    assert "curl --max-time" not in lowered


def test_no_direct_provider_api_model_in_required_workflows() -> None:
    """Required central review workflows cannot call a provider model directly."""
    direct_provider_patterns = (
        r"nvidia-nim/",
        r"openrouter/",
        r"openai/gpt",
        r"bytez/",
    )
    for path in (NOEMA, STRIX, REQUIRED_OPENCODE, OPENCODE_DISPATCH, AUTOFIX):
        text = _read(path)
        for pattern in direct_provider_patterns:
            assert re.search(pattern, text, re.IGNORECASE) is None, (path, pattern)


def test_sidecar_does_not_export_provider_secrets_to_consumers() -> None:
    """Provider keys remain bootstrap-only rather than downstream environment."""
    text = _read(SIDECAR)
    export_lines = [line for line in text.splitlines() if line.strip().startswith("export ")]
    exported = "\n".join(export_lines)
    for name in (
        "BYTEZ_API_KEY",
        "NVIDIA_NIM_API_KEY",
        "NVIDIA_NIM_API_KEY_SUB",
        "OPENROUTER_API_KEY",
        "OPENAI_API_KEY",
    ):
        assert name not in exported


def test_sidecar_shell_syntax() -> None:
    """The sidecar wrapper remains valid bash."""
    subprocess.run(["bash", "-n", str(SIDECAR)], check=True)


def test_launcher_python_syntax() -> None:
    """The launcher remains syntactically valid Python."""
    subprocess.run([sys.executable, "-m", "py_compile", str(LAUNCHER)], check=True)


def test_policy_python_syntax() -> None:
    """The policy remains syntactically valid Python."""
    subprocess.run([sys.executable, "-m", "py_compile", str(POLICY)], check=True)


def test_sidecar_shell_does_not_leak_bearer_to_github_env() -> None:
    """The raw bearer itself is never persisted to the runner environment."""
    text = _read(SIDECAR)
    assert 'printf "CONTEXTUAL_ORCHESTRATOR_TOKEN=' not in text
    assert 'printf \'CONTEXTUAL_ORCHESTRATOR_TOKEN=' not in text


def test_policy_reports_auditable_selected_routes() -> None:
    """The policy report carries selected-route evidence rather than secrets."""
    text = _read(POLICY)
    assert '"selected_routes"' in text
    assert '"credential_key"' in text
    assert '"api_key"' not in text


def test_launcher_does_not_read_provider_env_at_request_time() -> None:
    """Provider env variables are bootstrap-only in the sidecar process."""
    text = _read(LAUNCHER)
    assert "register_review_credentials" in text
    serving_section = text[text.index("serve(") :]
    for name in (
        "BYTEZ_API_KEY",
        "NVIDIA_NIM_API_KEY",
        "NVIDIA_NIM_API_KEY_SUB",
        "OPENROUTER_API_KEY",
        "OPENAI_API_KEY",
    ):
        assert name not in serving_section


def test_required_workflow_tokens_are_not_model_credentials() -> None:
    """GitHub reviewer/mutation identities stay separate from provider secrets."""
    for path in (NOEMA, STRIX, REQUIRED_OPENCODE, OPENCODE_DISPATCH, AUTOFIX):
        text = _read(path)
        assert "NOEMA_REVIEW_TOKEN" not in _read(SIDECAR)
        assert "PR_REVIEW_MERGE_TOKEN" not in _read(LAUNCHER)
        assert "OPENCODE_APPROVE_TOKEN" not in _read(LAUNCHER)
        # The workflow can own these identities without placing them in provider config.
        if path == NOEMA:
            assert "NOEMA_REVIEW_TOKEN" in text or "id-token: write" in text


def test_sidecar_diagnostics_sentinel_is_shared() -> None:
    """Shell/launcher agree on the deterministic discovery completion marker."""
    shell = _read(SIDECAR)
    launcher = _read(LAUNCHER)
    assert 'SIDECAR_DISCOVERY_DIAGNOSTICS_SENTINEL="discovery_diagnostics_complete"' in shell
    assert '_DISCOVERY_DIAGNOSTICS_COMPLETE_SENTINEL = "discovery_diagnostics_complete"' in launcher
