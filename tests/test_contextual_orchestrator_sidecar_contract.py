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


def test_noema_auto_sidecar_is_public_repository_only() -> None:
    """Private repositories require explicit Noema provider configuration."""
    text = NOEMA_WORKFLOW.read_text(encoding="utf-8")
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
