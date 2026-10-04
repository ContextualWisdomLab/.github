"""Bounded positive/negative report-identity controls for the scratch proposal."""
from pathlib import Path
import json
import pytest
from scripts.ci import strix_report_scope as scope

CHANGED = "scripts/ci/strix_quick_gate.sh"

@pytest.mark.parametrize("text", [
    "Reviewed `scripts/ci/strix_quick_gate.sh`.",
    "Reviewed scripts/ci/strix_quick_gate.sh.",
    "Scope: scripts/ci/. Reviewed strix_quick_gate.sh.",
    "Scope: `/workspace/strix-pr-scope.ABC123/scripts/ci/`.",
    "Scope: `/workspace/strix-pr-scope.ABC123/scripts/ci/strix_quick_gate.sh`.",
])
def test_valid_identity_controls(text, tmp_path):
    """Complete paths and scoped directories remain valid report identities."""
    validate_report(tmp_path, text)

@pytest.mark.parametrize("text", [
    "Reviewed scripts/ci/strix_quick_gate.sh@backup.",
    "Reviewed scripts/ci/strix_quick_gate.sh追加.",
    "Reviewed scripts/ci/strix_quick_gate.sh\\notes.",
    "Reviewed scripts/ci/strix_quick_gate.sh/notes.",
    "Reviewed scripts/ci/strix_quick_gate.sh.bak.",
    "Scope: scripts/ci@backup. Reviewed strix_quick_gate.sh.",
    "Scope: scripts/ci追加. Reviewed strix_quick_gate.sh.",
    "Scope: scripts/ci/../unrelated. Reviewed strix_quick_gate.sh.",
    "Scope: /workspace/strix-pr-scope.ABC123/scripts/ci/../unrelated.",
    "Scope: /workspace/strix-pr-scope.ABC123/scripts/ci/strix_quick_gate.sh/notes.",
])
def test_invalid_identity_controls(text, tmp_path):
    """Longer names, child paths and traversal do not inherit source identity."""
    with pytest.raises(ValueError, match="does not identify a changed source file"):
        validate_report(tmp_path, text)


def validate_report(tmp_path: Path, text: str) -> None:
    """Exercise the real validator with otherwise-valid completion metadata."""
    run = tmp_path / "current-scan"
    run.mkdir()
    (run / "run.json").write_text(json.dumps({
        "status": "completed",
        "scan_results": {"scan_completed": True, "success": True},
    }), encoding="utf-8")
    (run / "penetration_test_report.md").write_text(text, encoding="utf-8")
    scope.validate(tmp_path, [CHANGED])
