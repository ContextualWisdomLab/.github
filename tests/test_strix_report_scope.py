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
        json.dumps(
            {
                "status": "completed",
                "scan_results": {
                    "scan_completed": True,
                    "success": True,
                    "executive_summary": "No issues found in the changed file.",
                    "methodology": "Reviewed the changed source file.",
                    "technical_analysis": "The changed function preserves authorization checks.",
                    "recommendations": "Retain the existing checks.",
                },
            }
        ),
        encoding="utf-8",
    )
    report = run / "penetration_test_report.md"
    report.write_text("Python OpenSSH client RCE vulnerability.\n", encoding="utf-8")
    command = [sys.executable, str(SCRIPT), str(tmp_path), "python/fast_mlsirm/report.py"]
    assert subprocess.run(command, capture_output=True).returncode == 1

    report.write_text("Assessed python/fast_mlsirm/report.py; no vulnerabilities found.\n", encoding="utf-8")
    assert subprocess.run(command, capture_output=True).returncode == 0
    assert subprocess.run(command[:-1], capture_output=True).returncode == 1
    metadata = json.loads((run / "run.json").read_text(encoding="utf-8"))
    metadata["scan_results"]["executive_summary"] = "Business-level summary for leadership."
    (run / "run.json").write_text(json.dumps(metadata), encoding="utf-8")
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    assert result.returncode == 1
    assert "placeholder" in result.stderr
    del metadata["scan_results"]["executive_summary"]
    (run / "run.json").write_text(json.dumps(metadata), encoding="utf-8")
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    assert result.returncode == 1
    assert "incomplete" in result.stderr
