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


def test_report_scope_accepts_path_suffix_at_component_boundary_only(tmp_path: Path) -> None:
    run = tmp_path / "current-scan"
    run.mkdir()
    (run / "run.json").write_text(
        json.dumps({"status": "completed", "scan_results": {"scan_completed": True, "success": True}}),
        encoding="utf-8",
    )
    report = run / "penetration_test_report.md"
    command = [sys.executable, str(SCRIPT), str(tmp_path), "scripts/ci/check_telemetry_ownership.py"]

    report.write_text("Reviewed `check_telemetry_ownership.py`; no findings.\n", encoding="utf-8")
    assert subprocess.run(command, capture_output=True).returncode == 0
    report.write_text("Reviewed ci/check_telemetry_ownership.py; no findings.\n", encoding="utf-8")
    assert subprocess.run(command, capture_output=True).returncode == 0
    report.write_text("Reviewed /workspace/scope/scripts/ci/check_telemetry_ownership.py.\n", encoding="utf-8")
    assert subprocess.run(command, capture_output=True).returncode == 0

    report.write_text("Reviewed test_check_telemetry_ownership.py; no findings.\n", encoding="utf-8")
    assert subprocess.run(command, capture_output=True).returncode == 1
    report.write_text("Reviewed check_telemetry_ownership.pyc; no findings.\n", encoding="utf-8")
    assert subprocess.run(command, capture_output=True).returncode == 1
    report.write_text("Reviewed i/check_telemetry_ownership.py; no findings.\n", encoding="utf-8")
    assert subprocess.run(command, capture_output=True).returncode == 1


def _load_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location("strix_report_scope", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_report_scope_rejects_each_malformed_report_shape(tmp_path: Path) -> None:
    import pytest

    scope = _load_module()
    with pytest.raises(ValueError, match="directory is missing"):
        scope.validate(tmp_path / "absent", ["a.py"])
    link = tmp_path / "link"
    link.symlink_to(tmp_path)
    with pytest.raises(ValueError, match="directory is missing"):
        scope.validate(link, ["a.py"])
    output = tmp_path / "out"
    output.mkdir()
    with pytest.raises(ValueError, match="exactly one"):
        scope.validate(output, ["a.py"])
    run = output / "run"
    run.mkdir()
    with pytest.raises(ValueError, match="missing or linked"):
        scope.validate(output, ["a.py"])
    metadata = run / "run.json"
    (run / "penetration_test_report.md").write_text("a.py\n", encoding="utf-8")
    for body, message in (
        ([], "not an object"),
        ({"scan_results": [1]}, "results are not an object"),
        ({"status": "completed", "scan_results": {"scan_completed": True}}, "incomplete"),
    ):
        metadata.write_text(json.dumps(body), encoding="utf-8")
        with pytest.raises(ValueError, match=message):
            scope.validate(output, ["a.py"])
    metadata.write_text(
        json.dumps({"status": "completed", "scan_results": {"scan_completed": True, "success": True}}),
        encoding="utf-8",
    )
    scope.validate(output, ["src/a.py"])
    with pytest.raises(ValueError, match="does not identify"):
        scope.validate(output, ["src/b.py"])


def test_report_scope_main_exits_nonzero_on_invalid_scope(tmp_path: Path, monkeypatch, capsys) -> None:
    import runpy

    import pytest

    monkeypatch.setattr(sys, "argv", [str(SCRIPT), str(tmp_path / "absent"), "a.py"])
    with pytest.raises(SystemExit) as exit_info:
        runpy.run_path(str(SCRIPT), run_name="__main__")
    assert exit_info.value.code == 1
    assert "directory is missing" in capsys.readouterr().err
