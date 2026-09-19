"""Central review sidecar pool-boundary regression contracts."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.ci import contextual_orchestrator_review_launcher as launcher


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "scripts" / "ci" / "contextual_orchestrator_review_launcher.py"
SIDECAR = ROOT / "scripts" / "ci" / "contextual_orchestrator_review_sidecar.sh"


def test_launcher_rejects_paid_inclusive_pool_at_argument_boundary(capsys) -> None:
    """Noema/OpenCode/Strix reject ``auto`` before provider bootstrap can run."""
    argv = [
        "--discovery-out",
        "discovery.json",
        "--catalog-out",
        "catalog.json",
        "--report-out",
        "report.json",
        "--preflight-out",
        "preflight.json",
        "--pool",
        "auto",
    ]

    with pytest.raises(SystemExit) as exc_info:
        launcher.main(argv)

    assert exc_info.value.code == 2
    stderr = capsys.readouterr().err
    assert "--pool" in stderr
    assert "invalid choice" in stderr
    assert "auto" in stderr


def test_launcher_source_does_not_restore_paid_inclusive_choice() -> None:
    """Source review also guards against silently widening the central parser."""
    launcher_source = LAUNCHER.read_text(encoding="utf-8")
    assert 'parser.add_argument("--pool", choices=("free",), default="free")' in launcher_source
    assert 'choices=("free", "auto")' not in launcher_source


def test_sidecar_rejects_any_pool_other_than_free() -> None:
    """Environment configuration cannot reactivate orchestrator/auto centrally."""
    sidecar = SIDECAR.read_text(encoding="utf-8")
    assert 'case "$orchestrator_pool" in' in sidecar
    assert 'fail "CONTEXTUAL_ORCHESTRATOR_POOL must be free"' in sidecar
    assert 'free|auto)' not in sidecar
