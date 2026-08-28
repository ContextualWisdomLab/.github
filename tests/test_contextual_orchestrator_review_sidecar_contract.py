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


def test_sidecar_installs_only_hash_locked_vendored_dependencies() -> None:
    """The pinned source lock, not unconstrained project metadata, owns installs."""
    text = _read(SIDECAR)
    assert "--require-hashes" in text
    assert "--only-binary=:all:" in text
    assert "--no-deps" in text
    assert '-r "$ORCHESTRATOR_SOURCE/requirements.lock"' in text
    assert (
        'python3 -m pip install --quiet --disable-pip-version-check '
        '--no-cache-dir --target "$ORCHESTRATOR_SITE_PACKAGES" '
        '"$ORCHESTRATOR_SOURCE"'
    ) not in text


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


def test_launcher_forwards_private_source_zdr_requirement() -> None:
    """Private-repository scans fail closed unless every catalog route is ZDR."""
    text = _read(LAUNCHER)
    assert 'os.environ.get("ORCHESTRATOR_REQUIRE_ZDR", "false")' in text
    assert "require_zdr=require_zdr" in text


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
