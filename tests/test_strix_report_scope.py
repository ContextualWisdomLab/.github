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


# Scope section of the 0-finding fast-mlsirm#2246 report (run 36580588738,
# attempt 2): it names the PR-scope directories it audited, not a file.
SCOPED_DIRECTORY_REPORT = """# Methodology

**Scope:**
- `/workspace/strix-pr-scope.AoFHD6/crates/mlsirm-core` (Core Rust implementation)
- `/workspace/strix-pr-scope.AoFHD6/crates/fast-mlsirm-py` (PyO3 bindings)
- `/workspace/strix-pr-scope.AoFHD6/python/fast_mlsirm` (Python wrapper)

No security vulnerabilities were identified during this assessment.
"""


def _completed_run(tmp_path: Path, report: str) -> None:
    run = tmp_path / "current-scan"
    run.mkdir()
    (run / "run.json").write_text(
        json.dumps(
            {
                "status": "completed",
                "scan_results": {
                    "scan_completed": True,
                    "success": True,
                    "executive_summary": "No issues found in the audited PR scope.",
                    "methodology": "Reviewed the PR-scope source directories.",
                    "technical_analysis": "Changed numerical code has no untrusted input path.",
                    "recommendations": "No remediation required.",
                },
            }
        ),
        encoding="utf-8",
    )
    (run / "penetration_test_report.md").write_text(report, encoding="utf-8")


def test_scan_scope_directory_containing_a_changed_file_identifies_the_scope(tmp_path: Path) -> None:
    _completed_run(tmp_path, SCOPED_DIRECTORY_REPORT)
    changed = ["crates/mlsirm-core/src/gpu_regression.rs", "python/fast_mlsirm/regression.py"]
    assert subprocess.run([sys.executable, str(SCRIPT), str(tmp_path), *changed], capture_output=True).returncode == 0


def test_scan_scope_directory_unrelated_to_changed_files_is_rejected(tmp_path: Path) -> None:
    _completed_run(tmp_path, SCOPED_DIRECTORY_REPORT)
    changed = ["docs/methods.md", "tests/test_regression.py"]
    assert subprocess.run([sys.executable, str(SCRIPT), str(tmp_path), *changed], capture_output=True).returncode == 1


def test_bare_repository_directory_or_scope_root_is_not_enough(tmp_path: Path) -> None:
    changed = ["crates/mlsirm-core/src/gpu_regression.rs"]
    _completed_run(tmp_path, "Audited crates/mlsirm-core; nothing found.\n")
    assert subprocess.run([sys.executable, str(SCRIPT), str(tmp_path), *changed], capture_output=True).returncode == 1
    (tmp_path / "current-scan" / "penetration_test_report.md").write_text(
        "Scope: `/workspace/strix-pr-scope.AoFHD6/`; nothing found.\n", encoding="utf-8"
    )
    assert subprocess.run([sys.executable, str(SCRIPT), str(tmp_path), *changed], capture_output=True).returncode == 1
    # A repository-root equivalent under the scope root binds nothing either.
    (tmp_path / "current-scan" / "penetration_test_report.md").write_text(
        "Scope: `/workspace/strix-pr-scope.AoFHD6/.`; nothing found.\n", encoding="utf-8"
    )
    assert subprocess.run([sys.executable, str(SCRIPT), str(tmp_path), *changed], capture_output=True).returncode == 1
