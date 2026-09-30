"""A completed Strix report must name the PR source it assessed."""

from __future__ import annotations

import json
import runpy
import sys
from pathlib import Path

import pytest

from scripts.ci import strix_report_scope as report_scope


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/ci/strix_report_scope.py"
CHANGED_PATH = "python/fast_mlsirm/report.py"


def _write_report(
    output_dir: Path,
    *,
    metadata: object | None = None,
    report_text: str = f"Assessed {CHANGED_PATH}; no vulnerabilities found.\n",
) -> Path:
    """Create one ordinary scan report and return its run directory."""
    run_dir = output_dir / "current-scan"
    run_dir.mkdir(parents=True, exist_ok=True)
    if metadata is None:
        metadata = {
            "status": "completed",
            "scan_results": {"scan_completed": True, "success": True},
        }
    (run_dir / "run.json").write_text(json.dumps(metadata), encoding="utf-8")
    (run_dir / "penetration_test_report.md").write_text(
        report_text, encoding="utf-8"
    )
    return run_dir


def test_validate_accepts_only_a_completed_scoped_report(tmp_path: Path) -> None:
    """A completed report naming a changed source path is accepted."""
    _write_report(tmp_path)
    report_scope.validate(tmp_path, [CHANGED_PATH])


def test_validate_rejects_missing_or_linked_output(tmp_path: Path) -> None:
    """The trusted scan root must be a real directory."""
    with pytest.raises(ValueError, match="output directory is missing"):
        report_scope.validate(tmp_path / "missing", [CHANGED_PATH])

    real_dir = tmp_path / "real"
    real_dir.mkdir()
    linked_dir = tmp_path / "linked"
    linked_dir.symlink_to(real_dir, target_is_directory=True)
    with pytest.raises(ValueError, match="output directory is missing"):
        report_scope.validate(linked_dir, [CHANGED_PATH])


def test_validate_requires_exactly_one_real_run_directory(tmp_path: Path) -> None:
    """Files and linked directories never count as the single current run."""
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (output_dir / "noise.txt").write_text("ignored", encoding="utf-8")
    linked_target = tmp_path / "linked-target"
    linked_target.mkdir()
    (output_dir / "linked-run").symlink_to(linked_target, target_is_directory=True)
    with pytest.raises(ValueError, match="exactly one current scan report"):
        report_scope.validate(output_dir, [CHANGED_PATH])

    _write_report(output_dir)
    (output_dir / "second-run").mkdir()
    with pytest.raises(ValueError, match="exactly one current scan report"):
        report_scope.validate(output_dir, [CHANGED_PATH])


@pytest.mark.parametrize("linked_name", ["run.json", "penetration_test_report.md"])
def test_validate_rejects_missing_or_linked_report_files(
    tmp_path: Path, linked_name: str
) -> None:
    """Neither report input may be absent or redirected through a symlink."""
    run_dir = _write_report(tmp_path)
    target = run_dir / linked_name
    target.unlink()
    with pytest.raises(ValueError, match="report files are missing or linked"):
        report_scope.validate(tmp_path, [CHANGED_PATH])

    outside = tmp_path / f"outside-{linked_name}"
    outside.write_text("{}" if linked_name == "run.json" else CHANGED_PATH)
    target.symlink_to(outside)
    with pytest.raises(ValueError, match="report files are missing or linked"):
        report_scope.validate(tmp_path, [CHANGED_PATH])


@pytest.mark.parametrize(
    ("metadata", "expected_error"),
    [
        ([], "metadata is not an object"),
        ({"status": "completed", "scan_results": ["invalid"]}, "results are not an object"),
        ({"status": "running", "scan_results": {"scan_completed": True, "success": True}}, "report is incomplete"),
        ({"status": "completed", "scan_results": {"scan_completed": False, "success": True}}, "report is incomplete"),
        ({"status": "completed", "scan_results": {"scan_completed": True, "success": False}}, "report is incomplete"),
    ],
)
def test_validate_rejects_malformed_or_incomplete_metadata(
    tmp_path: Path, metadata: object, expected_error: str
) -> None:
    """Metadata shape and every completion signal fail closed."""
    _write_report(tmp_path, metadata=metadata)
    with pytest.raises(ValueError, match=expected_error):
        report_scope.validate(tmp_path, [CHANGED_PATH])


def test_validate_rejects_malformed_json_and_unrelated_scope(tmp_path: Path) -> None:
    """Unreadable metadata and a report unrelated to the diff never pass."""
    run_dir = _write_report(tmp_path)
    (run_dir / "run.json").write_text("{not-json", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        report_scope.validate(tmp_path, [CHANGED_PATH])

    _write_report(tmp_path, report_text="Python OpenSSH client RCE vulnerability.\n")
    with pytest.raises(ValueError, match="does not identify a changed source file"):
        report_scope.validate(tmp_path, [CHANGED_PATH])


def test_cli_reports_validation_error_and_accepts_scoped_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The command boundary maps validation failures to exit 1 and stderr."""
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), str(tmp_path), CHANGED_PATH])
    with pytest.raises(SystemExit, match="1"):
        runpy.run_path(str(SCRIPT), run_name="__main__")
    assert "ERROR: Strix report scope: expected exactly one" in capsys.readouterr().err

    _write_report(tmp_path)
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), str(tmp_path)])
    with pytest.raises(SystemExit) as empty_scope_exit:
        runpy.run_path(str(SCRIPT), run_name="__main__")
    assert empty_scope_exit.value.code == 1
    assert "does not identify a changed source file" in capsys.readouterr().err

    monkeypatch.setattr(sys, "argv", [str(SCRIPT), str(tmp_path), CHANGED_PATH])
    runpy.run_path(str(SCRIPT), run_name="__main__")
