"""Central review sidecar pool-boundary regression contracts."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "scripts" / "ci" / "contextual_orchestrator_review_launcher.py"
SIDECAR = ROOT / "scripts" / "ci" / "contextual_orchestrator_review_sidecar.sh"


def test_launcher_exposes_only_free_pool() -> None:
    """Noema/OpenCode/Strix cannot reactivate the retired paid-inclusive pool."""
    launcher = LAUNCHER.read_text(encoding="utf-8")
    assert 'parser.add_argument("--pool", choices=("free",), default="free")' in launcher
    assert 'choices=("free", "auto")' not in launcher


def test_sidecar_rejects_any_pool_other_than_free() -> None:
    """Environment configuration cannot reactivate orchestrator/auto centrally."""
    sidecar = SIDECAR.read_text(encoding="utf-8")
    assert 'if [ "$orchestrator_pool" != "free" ]; then' in sidecar
    assert 'fail "CONTEXTUAL_ORCHESTRATOR_POOL must be free"' in sidecar
    assert 'free|auto)' not in sidecar
