"""Contracts for the central contextual-orchestrator reviewer sidecar."""

from __future__ import annotations

from pathlib import Path
import re


NOEMA_WORKFLOW = Path(".github/workflows/noema-review.yml")
OPENCODE_WORKFLOW = Path(".github/workflows/opencode-review-dispatch.yml")
SIDECAR_SCRIPT = Path("scripts/ci/start_contextual_orchestrator_sidecar.sh")


def test_sidecar_source_is_immutable_and_readiness_is_bounded() -> None:
    """Privileged sidecar code must be commit-pinned and health probes bounded."""
    text = SIDECAR_SCRIPT.read_text(encoding="utf-8")
    assert 'CONTEXTUAL_ORCHESTRATOR_REF:=7eb459ee72c37dead5d25f284dfa4546f149fbe1' in text
    assert '^[0-9a-fA-F]{40}$' in text
    assert '--connect-timeout 1 --max-time 2' in text
    assert 'validate_contextual_orchestrator_licenses.py' in text
    assert text.index('validate_contextual_orchestrator_licenses.py') < text.index('python3 -m venv')


def test_sidecar_license_policy_is_explicit_and_fail_closed() -> None:
    """Only a bounded permissive SPDX set may reach the sidecar install."""
    validator = Path("scripts/ci/validate_contextual_orchestrator_licenses.py").read_text(
        encoding="utf-8"
    )
    assert '"MIT"' in validator
    assert '"Apache-2.0"' in validator
    assert '"LGPL-3.0-only"' not in validator
    assert "LICENSE_VALIDATION_FAILED" in validator


def test_noema_auto_sidecar_is_public_repository_only() -> None:
    """Private repositories require explicit Noema provider configuration."""
    text = NOEMA_WORKFLOW.read_text(encoding="utf-8")
    assert (
        "if: env.PR_NUMBER != '' && steps.target_visibility.outputs.is_private == 'false'"
        in text
    )
    sidecar_condition = re.search(
        r'if \[ "\$TARGET_REPOSITORY_PRIVATE" = "false" \].{0,240}CONTEXTUAL_ORCHESTRATOR_BASE_URL',
        text,
    )
    assert sidecar_condition is not None


def test_generated_opencode_config_allows_contextual_orchestrator_provider() -> None:
    """The generated provider definition must also be present in its allowlist."""
    text = OPENCODE_WORKFLOW.read_text(encoding="utf-8")
    matches = re.findall(r'"enabled_providers"\s*:\s*\[([^\]]+)\]', text)
    assert matches
    assert any(
        '"contextual-orchestrator"' in allowlist and '"nvidia-nim"' in allowlist
        for allowlist in matches
    )


def test_sidecar_keeps_credential_registration_discovery_and_server_in_one_process() -> None:
    """Process-local credentials must survive through discovery and serving."""
    text = SIDECAR_SCRIPT.read_text(encoding="utf-8")
    assert "python -m contextual_orchestrator register-credential" not in text
    assert "python -m contextual_orchestrator discover-models" not in text
    assert "os.environ.pop(credential_name" in text
    assert "discover_all_models()" in text
    assert "TaskOrchestrator(" in text
    assert "serve(" in text


def test_sidecar_does_not_execute_an_editable_build_and_cleans_failed_startup() -> None:
    """The pinned source runs via PYTHONPATH and failed readiness kills the child."""
    text = SIDECAR_SCRIPT.read_text(encoding="utf-8")
    assert "pip install --quiet --no-deps -e" not in text
    assert 'PYTHONPATH="$RUNTIME_DIR"' in text
    assert 'sidecar_pid="$!"' in text
    assert 'kill "$sidecar_pid"' in text
    assert text.index('echo "contextual-orchestrator sidecar ready') < text.index("trap - EXIT")
