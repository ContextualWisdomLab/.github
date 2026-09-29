"""A completed Strix report must name the PR source it assessed."""

import json
import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/ci/strix_report_scope.py"


def test_report_scope_rejects_unrelated_success_and_accepts_scoped_success(tmp_path: Path) -> None:
    run = tmp_path / "current-scan"
    run.mkdir()
    (run / "run.json").write_text(
        json.dumps({"status": "completed", "scan_results": {"scan_completed": True, "success": True}}),
        encoding="utf-8",
    )
    report = run / "penetration_test_report.md"
    report.write_text("Python OpenSSH client RCE vulnerability.\n", encoding="utf-8")
    command = [sys.executable, str(SCRIPT), str(tmp_path), "python/fast_mlsirm/report.py"]
    assert subprocess.run(command, capture_output=True).returncode == 1

    report.write_text("Assessed python/fast_mlsirm/report.py; no vulnerabilities found.\n", encoding="utf-8")
    assert subprocess.run(command, capture_output=True).returncode == 0
    assert subprocess.run(command[:-1], capture_output=True).returncode == 1

def test_validate_exceptions(tmp_path: Path) -> None:
    import scripts.ci.strix_report_scope as strix_report_scope
    import pytest

    with pytest.raises(ValueError, match="scan output directory is missing"):
        strix_report_scope.validate(tmp_path / "nonexistent", [])

    run = tmp_path / "current-scan"
    run.mkdir()

    with pytest.raises(ValueError, match="scan report files are missing or linked"):
        strix_report_scope.validate(tmp_path, [])

    (run / "run.json").write_text("[]", encoding="utf-8")
    (run / "penetration_test_report.md").write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="scan metadata is not an object"):
        strix_report_scope.validate(tmp_path, [])

    (run / "run.json").write_text(json.dumps({"status": "completed", "scan_results": "[]"}), encoding="utf-8")
    with pytest.raises(ValueError, match="scan results are not an object"):
        strix_report_scope.validate(tmp_path, [])

    (run / "run.json").write_text(json.dumps({"scan_results": {}}), encoding="utf-8")
    with pytest.raises(ValueError, match="scan report is incomplete"):
        strix_report_scope.validate(tmp_path, [])

    (run / "run.json").write_text(json.dumps({"status": "completed"}), encoding="utf-8")
    with pytest.raises(ValueError, match="scan report is incomplete"):
        strix_report_scope.validate(tmp_path, [])

    (run / "run.json").write_text(json.dumps({"status": "completed", "scan_results": {"scan_completed": True, "success": False}}), encoding="utf-8")
    with pytest.raises(ValueError, match="scan report is incomplete"):
        strix_report_scope.validate(tmp_path, [])

    (run / "run.json").write_text(json.dumps({"status": "completed", "scan_results": {"scan_completed": False, "success": True}}), encoding="utf-8")
    with pytest.raises(ValueError, match="scan report is incomplete"):
        strix_report_scope.validate(tmp_path, ["python/fast_mlsirm/report.py"])

    (run / "run.json").write_text(json.dumps({"status": "completed", "scan_results": {"scan_completed": True, "success": True}}), encoding="utf-8")
    with pytest.raises(ValueError, match="scan report does not identify a changed source file"):
        strix_report_scope.validate(tmp_path, ["python/fast_mlsirm/report.py"])

    (run / "penetration_test_report.md").write_text("python/fast_mlsirm/report.py", encoding="utf-8")
    strix_report_scope.validate(tmp_path, ["python/fast_mlsirm/report.py"])

    run2 = tmp_path / "another-scan"
    run2.mkdir(parents=True)
    with pytest.raises(ValueError, match="expected exactly one current scan report"):
        strix_report_scope.validate(tmp_path, [])
