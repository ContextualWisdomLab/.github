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


@pytest.mark.parametrize("condition, expected", [
    ("missing_output", "scan output directory is missing"),
    ("linked_output", "scan output directory is missing"),
    ("no_run", "expected exactly one current scan report"),
    ("two_runs", "expected exactly one current scan report"),
    ("linked_run", "expected exactly one current scan report"),
    ("missing_metadata", "scan report files are missing or linked"),
    ("linked_metadata", "scan report files are missing or linked"),
    ("linked_report", "scan report files are missing or linked"),
    ("nonobject_metadata", "scan metadata is not an object"),
    ("nonobject_results", "scan results are not an object"),
    ("incomplete", "scan report is incomplete"),
])
def test_invalid_report_container_fails_closed(tmp_path, condition, expected):
    """Reject missing, ambiguous, linked and malformed report containers."""
    output = tmp_path / "output"
    if condition == "missing_output":
        with pytest.raises(ValueError, match=expected):
            scope.validate(output, [CHANGED])
        return
    output.mkdir()
    run = output / "current-scan"
    run.mkdir()
    metadata = run / "run.json"
    report = run / "penetration_test_report.md"
    metadata.write_text(json.dumps({
        "status": "completed",
        "scan_results": {"scan_completed": True, "success": True},
    }), encoding="utf-8")
    report.write_text(CHANGED, encoding="utf-8")
    if condition == "linked_output":
        link = tmp_path / "output-link"
        link.symlink_to(output, target_is_directory=True)
        output = link
    elif condition in {"no_run", "linked_run"}:
        outside = tmp_path / "outside-run"
        run.rename(outside)
        if condition == "linked_run":
            run.symlink_to(outside, target_is_directory=True)
    elif condition == "two_runs":
        (output / "other-scan").mkdir()
    elif condition == "missing_metadata":
        metadata.unlink()
    elif condition in {"linked_metadata", "linked_report"}:
        target = metadata if condition == "linked_metadata" else report
        outside = tmp_path / "outside-file"
        target.rename(outside)
        target.symlink_to(outside)
    elif condition == "nonobject_metadata":
        metadata.write_text("[]", encoding="utf-8")
    elif condition == "nonobject_results":
        metadata.write_text(json.dumps({"scan_results": ["unexpected"]}), encoding="utf-8")
    elif condition == "incomplete":
        metadata.write_text(json.dumps({"status": "running"}), encoding="utf-8")
    with pytest.raises(ValueError, match=expected):
        scope.validate(output, [CHANGED])


@pytest.mark.parametrize("valid", [True, False])
def test_report_scope_cli_preserves_success_and_denial(tmp_path, valid, monkeypatch, capsys):
    """Execute the actual script entry point with exact success or rejection."""
    import runpy
    import sys

    if valid:
        validate_report(tmp_path, CHANGED)
    script = str(Path(scope.__file__).resolve())
    monkeypatch.setattr(sys, "argv", [script, str(tmp_path), CHANGED])
    if valid:
        runpy.run_path(script, run_name="__main__")
    else:
        with pytest.raises(SystemExit) as raised:
            runpy.run_path(script, run_name="__main__")
        assert raised.value.code == 1
    output = capsys.readouterr()
    assert output.out == ""
    if valid:
        assert output.err == ""
    else:
        assert "ERROR: Strix report scope: expected exactly one current scan report" in output.err
