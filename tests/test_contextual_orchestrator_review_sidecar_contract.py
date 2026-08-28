"""Contract tests for the vendored contextual-orchestrator review sidecar.

These static contracts pin the org policy: every central CI review path routes
through the vendored ``contextual-orchestrator`` gateway, all five provider
secrets (``BYTEZ_API_KEY``, ``NVIDIA_NIM_API_KEY``, ``NVIDIA_NIM_API_KEY_SUB``,
``OPENROUTER_API_KEY``, ``OPENAI_API_KEY``) enter its process-local KV as
bootstrap transport, models are auto-discovered, and the ``orchestrator/free``
fail-closed zero-cost pool (prioritized by the ZDR policy in
``scripts/ci/zdr_policy.py``) is the review model.
"""

from __future__ import annotations

from pathlib import Path

_ORG_REPO_ROOT = Path(__file__).resolve().parents[1]

SIDECAR = _ORG_REPO_ROOT / "scripts/ci/contextual_orchestrator_review_sidecar.sh"
LAUNCHER = _ORG_REPO_ROOT / "scripts/ci/contextual_orchestrator_review_launcher.py"
AUTOFIX_WORKFLOW = _ORG_REPO_ROOT / ".github/workflows/pr-review-autofix.yml"
NOEMA_WORKFLOW = _ORG_REPO_ROOT / ".github/workflows/noema-review.yml"
OPENCODE_DISPATCH_WORKFLOW = _ORG_REPO_ROOT / ".github/workflows/opencode-review-dispatch.yml"
STRIX_WORKFLOW = _ORG_REPO_ROOT / ".github/workflows/strix.yml"
OPENCODE_CONFIG = _ORG_REPO_ROOT / "opencode.jsonc"

FIVE_SECRETS = (
    "BYTEZ_API_KEY",
    "NVIDIA_NIM_API_KEY",
    "NVIDIA_NIM_API_KEY_SUB",
    "OPENROUTER_API_KEY",
    "OPENAI_API_KEY",
)

GATEWAY_MODEL = "contextual-orchestrator/orchestrator/free"
ORCH_PIN_SHA = "c60ec889bdd1b8dd0b2be53e60d7b758a4ece6b7"


def _read(path: Path) -> str:
    """Return one tracked contract file as UTF-8 text."""
    return path.read_text(encoding="utf-8")


def test_sidecar_pins_the_vendored_orchestrator_revision() -> None:
    """The vendoring script must pin exact SHA evidence, never a moving ref."""
    text = _read(SIDECAR)
    assert f"ORCHESTRATOR_PIN_SHA=\"${{ORCHESTRATOR_PIN_SHA:-{ORCH_PIN_SHA}}}\"" in text
    assert "git clone" in text
    assert "checkout --quiet \"$ORCHESTRATOR_PIN_SHA\"" in text
    assert 'checked_out="$(git -C "$ORCHESTRATOR_SOURCE" rev-parse HEAD)"' in text
    assert 'if [ "$checked_out" != "$ORCHESTRATOR_PIN_SHA" ]; then' in text
    assert "--filter=blob:none" in text or "--depth" in text
    assert "--no-cache-dir" in text
    assert 'requirements_lock="$ORCHESTRATOR_SOURCE/requirements.lock"' in text
    assert "--require-hashes" in text
    assert 'PYTHONPATH="$ORCHESTRATOR_SOURCE:$ORG_REPO_ROOT"' in text
    assert "from contextual_orchestrator.review_gateway import register_review_credentials" in text
    assert 'ORCHESTRATOR_PORT="18080"' in text
    assert 'ORCHESTRATOR_HOST="127.0.0.1"' in text


def test_sidecar_requires_the_five_provider_secrets() -> None:
    """At least one of the five secrets must be present as bootstrap transport."""
    text = _read(SIDECAR)
    assert '"$provider_secret_count" -lt 1 ]; then' in text
    for secret in FIVE_SECRETS:
        assert secret in text


def test_sidecar_feeds_discovery_and_policy_artifacts_to_the_launcher() -> None:
    """In-process discovery evidence and the ZDR catalog are explicit outputs."""
    text = _read(SIDECAR)
    for arg in (
        "--discovery-out \"$discovery_report\"",
        "--catalog-out \"$catalog_file\"",
        "--report-out \"$policy_report\"",
        "--zdr-endpoints \"$zdr_feed\"",
    ):
        assert arg in text
    assert "https://openrouter.ai/api/v1/endpoints/zdr" in text


def test_sidecar_exports_gateway_env_for_review_steps() -> None:
    """The gateway address and bearer token land in GITHUB_ENV for later steps."""
    text = _read(SIDECAR)
    assert "CONTEXTUAL_ORCHESTRATOR_BASE_URL=http://%s:%s\\n' \"$ORCHESTRATOR_HOST\" \"$ORCHESTRATOR_PORT\"" in text
    assert "CONTEXTUAL_ORCHESTRATOR_TOKEN=%s\\n' \"$ORCHESTRATOR_TOKEN\"" in text
    assert "CONTEXTUAL_ORCHESTRATOR_EVIDENCE=%s\\n' \"$policy_report\"" in text
    assert '>> "$ORCHESTRATOR_GITHUB_ENV"' in text


def test_sidecar_masks_gateway_token_before_startup_can_emit_logs() -> None:
    """The bearer is masked before clone, install, launch, or health output."""
    text = _read(SIDECAR)
    mask = "printf '::add-mask::%s\\n' \"$ORCHESTRATOR_TOKEN\""
    assert "ORCHESTRATOR_TOKEN must not contain CR or LF" in text
    assert mask in text
    mask_index = text.index(mask)
    for later_operation in (
        "git clone",
        "python3 -m pip install",
        '"$ORCHESTRATOR_WORK/launch_sidecar.py"',
        "healthz",
    ):
        assert mask_index < text.index(later_operation)


def test_launcher_registers_secrets_into_the_kv_once() -> None:
    """Secrets enter the KV in the same process that serves — never os.getenv later."""
    text = _read(LAUNCHER)
    assert "from contextual_orchestrator.review_gateway import (" in text
    assert "register_review_credentials," in text
    assert "REVIEW_AUTH_CREDENTIAL_NAME," in text
    assert "register_review_credentials(os.environ)" in text
    assert "get_credential(REVIEW_AUTH_CREDENTIAL_NAME)" in text


def test_launcher_uses_orchestrator_discovery_and_free_pool() -> None:
    """Discovery, free filtering, and serving come from the vendored library."""
    text = _read(LAUNCHER)
    assert "from contextual_orchestrator.model_discovery import discover_all_models, free_discovered_models" in text
    assert "free_discovered_models(discovered)" in text
    assert "from contextual_orchestrator.orchestrator import ModelClient, TaskOrchestrator, load_agents" in text
    assert "from contextual_orchestrator.server import SecurityConfig, serve" in text
    assert "orchestrator/free would fail closed" in text
    assert "scripts.ci.contextual_orchestrator_review_policy" in text
    assert "from scripts.ci import zdr_policy" in text


def test_launcher_requires_gateway_token_and_a_provider_credential() -> None:
    """The sidecar never boots without an auth token and a provider credential."""
    text = _read(LAUNCHER)
    assert "requires an explicit --auth-token" in text
    assert "requires at least one provider credential in the KV" in text


def test_autofix_workflow_provisions_sidecar_with_all_five_secrets() -> None:
    """The write-capable autofix path bootstraps the gateway with the five keys."""
    workflow = _read(AUTOFIX_WORKFLOW)
    assert "contextual_orchestrator_review_sidecar.sh" in workflow
    for secret in FIVE_SECRETS:
        assert f"{secret}: ${{{{ secrets.{secret} }}}}" in workflow
    assert GATEWAY_MODEL in workflow
    assert workflow.count(f"MODEL: {GATEWAY_MODEL}") == 2
    assert "https://integrate.api.nvidia.com/v1" not in workflow


def test_opencode_config_defaults_to_the_contextual_gateway() -> None:
    """OpenCode's default review route is orchestrator/free through the gateway."""
    config = _read(OPENCODE_CONFIG)
    assert f'"model": "{GATEWAY_MODEL}"' in config
    assert f'"small_model": "{GATEWAY_MODEL}"' in config
    assert '"enabled_providers": ["contextual-orchestrator"' in config
    assert '"baseURL": "{env:CONTEXTUAL_ORCHESTRATOR_BASE_URL}"' in config
    assert '"apiKey": "{env:CONTEXTUAL_ORCHESTRATOR_TOKEN}"' in config
    assert '"orchestrator/free": {' in config


def test_sidecar_trap_keeps_the_gateway_alive_after_provisioning() -> None:
    """Provisioning is a separate GHA step; EXIT must not kill a healthy sidecar."""
    text = _read(SIDECAR)
    assert "cleanup_sidecar_on_error" in text
    assert "trap cleanup_sidecar_on_error EXIT" in text
    assert 'trap \'log "stopping sidecar (pid $sidecar_pid)"; kill "$sidecar_pid"' not in text


def test_noema_review_workflow_provisions_sidecar_with_all_five_secrets() -> None:
    """Required Noema review uses the gateway; the public NIM hardcode is gone."""
    workflow = _read(NOEMA_WORKFLOW)
    assert "contextual_orchestrator_review_sidecar.sh" in workflow
    for secret in FIVE_SECRETS:
        assert f"{secret}: ${{{{ secrets.{secret} }}}}" in workflow
    assert 'export NOEMA_LLM_MODEL="orchestrator/free"' in workflow
    assert "NOEMA_LLM_VIA_ORCHESTRATOR=1" in workflow
    assert "${CONTEXTUAL_ORCHESTRATOR_BASE_URL%/}/v1/chat/completions" in workflow
    assert "${CONTEXTUAL_ORCHESTRATOR_TOKEN}" in workflow
    assert "https://integrate.api.nvidia.com" not in workflow
    assert "nvidia/nemotron-3-ultra-550b-a55b" not in workflow
    assert "COPILOT_GITHUB_TOKEN" not in workflow
    assert "secrets: inherit" not in workflow
    assert "NOEMA_REVIEW_TOKEN: ${{ secrets.NOEMA_REVIEW_TOKEN }}" in workflow


def test_noema_private_targets_require_zdr_only_sidecar_routing() -> None:
    """Repository visibility binds private review content to an attested ZDR-only pool."""
    workflow = _read(NOEMA_WORKFLOW)
    sidecar = _read(SIDECAR)
    launcher = _read(LAUNCHER)

    assert "Resolve Noema target repository visibility" in workflow
    assert "target_visibility.outputs.require_zdr" in workflow
    assert "CONTEXTUAL_ORCHESTRATOR_REQUIRE_ZDR" in workflow
    assert "CONTEXTUAL_ORCHESTRATOR_REQUIRE_ZDR" in sidecar
    assert "--require-zdr" in sidecar
    assert 'parser.add_argument("--require-zdr", action="store_true")' in launcher
    assert "require_zdr=args.require_zdr" in launcher


def test_required_opencode_dispatch_uses_the_gateway_for_model_pool_and_diagnosis() -> None:
    """The privileged Required OpenCode path has no direct-provider model route."""
    workflow = _read(OPENCODE_DISPATCH_WORKFLOW)
    assert "Provision contextual-orchestrator review sidecar" in workflow
    assert workflow.index("Validate pull request head repository trust") < workflow.index(
        "Provision contextual-orchestrator review sidecar"
    )
    assert 'OPENCODE_MODEL_CANDIDATES: "contextual-orchestrator/orchestrator/free"' in workflow
    assert 'MODEL: contextual-orchestrator/orchestrator/free' in workflow
    assert '.enabled_providers = ["contextual-orchestrator"]' in workflow
    assert '.model = "contextual-orchestrator/orchestrator/free"' in workflow
    assert 'CONTEXTUAL_ORCHESTRATOR_TOKEN:-' in workflow
    assert 'STRIX_GITHUB_MODELS_TOKEN:-' not in workflow
    assert 'MODEL: github-models/' not in workflow


def test_required_strix_uses_the_gateway_and_zdr_visibility_contract() -> None:
    """Strix accepts only the gateway route and binds private scans to ZDR."""
    workflow = _read(STRIX_WORKFLOW)
    assert "Provision contextual-orchestrator Strix sidecar" in workflow
    assert "CONTEXTUAL_ORCHESTRATOR_REQUIRE_ZDR" in workflow
    assert 'STRIX_MODEL: contextual-orchestrator/orchestrator/free' in workflow
    assert "provider_mode=contextual_orchestrator" in workflow
    assert "STRIX_LLM_DEFAULT_PROVIDER: contextual_orchestrator" in workflow
    assert workflow.index("Resolve target repository visibility") < workflow.index(
        "Provision contextual-orchestrator Strix sidecar"
    )
    assert workflow.index("Validate repository dispatch against live pull request metadata") < workflow.index(
        "Provision contextual-orchestrator Strix sidecar"
    )
    assert workflow.index("Gate Strix secrets") < workflow.index(
        "Provision contextual-orchestrator Strix sidecar"
    )
    assert "STRIX_FALLBACK_MODELS: \"\"" in workflow
