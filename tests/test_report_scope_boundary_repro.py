"""Offline negative report identities against retained exact-head source.

This diagnostic loads the already preserved helper, changes no canonical source,
and uses synthetic unit-test reports, not substituted hosted scanner evidence.
"""
from pathlib import Path
import importlib.util
import json
import pytest

SOURCE = Path(__file__).resolve().parents[1] / "scripts/ci/strix_report_scope.py"
spec = importlib.util.spec_from_file_location("retained_report_scope", SOURCE)
report_scope = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report_scope)

@pytest.mark.parametrize("report_text", [
    "Assessed `/workspace/strix-pr-scope.ABC123/scripts/ci/strix_quick_gate.sh@backup`; no findings.",
    "Assessed `/workspace/strix-pr-scope.ABC123/scripts/ci/strix_quick_gate.sh追加`; no findings.",
    "Scope: `scripts/ci/../unrelated`. Reviewed `strix_quick_gate.sh`; no findings.",
])
def test_unrelated_report_path_must_not_bind_changed_file(tmp_path, report_text):
    """Reject partial scope-prefix tokens and directory traversal identities."""
    run = tmp_path / "current-scan"
    run.mkdir()
    (run / "run.json").write_text(json.dumps({
        "status": "completed",
        "scan_results": {"scan_completed": True, "success": True},
    }), encoding="utf-8")
    (run / "penetration_test_report.md").write_text(report_text, encoding="utf-8")
    with pytest.raises(ValueError, match="does not identify a changed source file"):
        report_scope.validate(tmp_path, ["scripts/ci/strix_quick_gate.sh"])
