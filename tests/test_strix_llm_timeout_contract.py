"""Regression contract for Strix model preflight through contextual-orchestrator."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/strix.yml"
TOKEN_LOADER = ROOT / "scripts/ci/load_contextual_orchestrator_token.sh"
INSTALLER = ROOT / "scripts/ci/install_strix_timeout_compat.py"
LAUNCHER = ROOT / "scripts/ci/strix_timeout_compat.py"


def test_zero_timeout_policy_has_a_version_gated_strix_compatibility_launcher() -> None:
    """Keep unbounded inference while preventing Strix 1.5.3 warm-up cancellation."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    token_loader = TOKEN_LOADER.read_text(encoding="utf-8")

    assert "export LLM_TIMEOUT=0" in workflow
    assert "export LLM_TIMEOUT=300" not in workflow
    assert "install_strix_timeout_compat.py" in token_loader
    assert INSTALLER.is_file()
    assert LAUNCHER.is_file()
    launcher = LAUNCHER.read_text(encoding="utf-8")
    assert 'SUPPORTED_VERSION = "1.5.3"' in launcher
    assert '"strix.interface.scan_setup"' in launcher
    assert '"strix.interface.main"' in launcher
