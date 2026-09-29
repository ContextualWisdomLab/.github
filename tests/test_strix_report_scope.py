"""A completed Strix report must name the PR source it assessed."""

import json
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.ci import strix_report_scope


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


@pytest.mark.parametrize(
    ("case", "message"),
    [
        ("missing-output", "output directory"),
        ("linked-output", "output directory"),
        ("missing-run", "exactly one"),
        ("two-runs", "exactly one"),
        ("linked-run", "exactly one"),
        ("missing-metadata", "files are missing"),
        ("linked-metadata", "files are missing"),
        ("missing-report", "files are missing"),
        ("linked-report", "files are missing"),
        ("nonobject-metadata", "not an object"),
        ("nonobject-results", "not an object"),
        ("missing-results", "incomplete"),
        ("pending-status", "incomplete"),
        ("unfinished-scan", "incomplete"),
        ("unsuccessful-scan", "incomplete"),
        ("unrelated-report", "changed source"),
        ("empty-paths", "changed source"),
    ],
)
def test_validate_rejects_incomplete_or_unbound_reports(tmp_path: Path, case: str, message: str) -> None:
    output = tmp_path / "output"
    output.mkdir()
    run = output / "current-scan"
    run.mkdir()
    metadata_path = run / "run.json"
    report_path = run / "penetration_test_report.md"
    metadata = {"status": "completed", "scan_results": {"scan_completed": True, "success": True}}
    report_path.write_text("Assessed src/a.py", encoding="utf-8")
    if case == "missing-output":
        output = tmp_path / "missing"
    elif case == "linked-output":
        output = tmp_path / "linked"
        output.symlink_to(tmp_path / "output", target_is_directory=True)
    elif case == "missing-run":
        report_path.unlink()
        run.rmdir()
    elif case == "two-runs":
        (output / "other-scan").mkdir()
    elif case == "linked-run":
        run.rename(tmp_path / "real-scan")
        run.symlink_to(tmp_path / "real-scan", target_is_directory=True)
    elif case == "missing-metadata":
        pass
    elif case == "linked-metadata":
        metadata_path.symlink_to(tmp_path / "outside.json")
    elif case == "missing-report":
        report_path.unlink()
    elif case == "linked-report":
        report_path.unlink()
        report_path.symlink_to(tmp_path / "outside.md")
    elif case == "nonobject-metadata":
        metadata = []
    elif case == "nonobject-results":
        metadata["scan_results"] = ["not an object"]
    elif case == "missing-results":
        metadata.pop("scan_results")
    elif case == "pending-status":
        metadata["status"] = "pending"
    elif case == "unfinished-scan":
        metadata["scan_results"]["scan_completed"] = False
    elif case == "unsuccessful-scan":
        metadata["scan_results"]["success"] = False
    elif case == "unrelated-report":
        report_path.write_text("Only an unrelated library was assessed", encoding="utf-8")
    if case not in {"missing-run", "missing-metadata", "linked-metadata"}:
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        strix_report_scope.validate(output, [] if case == "empty-paths" else ["src/a.py"])


def test_validate_accepts_one_complete_current_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run = tmp_path / "current-scan"
    run.mkdir()
    (tmp_path / "unrelated.txt").write_text("ignored", encoding="utf-8")
    (run / "run.json").write_text(
        json.dumps({"status": "completed", "scan_results": {"scan_completed": True, "success": True}}),
        encoding="utf-8",
    )
    (run / "penetration_test_report.md").write_text("Assessed src/a.py", encoding="utf-8")
    strix_report_scope.validate(tmp_path, ["src/a.py"])
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), str(tmp_path), "src/a.py"])
    runpy.run_path(str(SCRIPT), run_name="__main__")


def test_cli_error_path_remains_fail_closed_in_process(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(sys, "argv", [str(SCRIPT)])
    with pytest.raises(SystemExit) as failure:
        runpy.run_path(str(SCRIPT), run_name="__main__")
    assert failure.value.code == 1
    assert "ERROR: Strix report scope:" in capsys.readouterr().err
