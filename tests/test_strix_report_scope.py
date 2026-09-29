"""A completed Strix report must name the PR source it assessed."""

import json
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.ci import strix_report_scope as scope

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


CHANGED = "python/fast_mlsirm/report.py"


def _scan(tmp_path: Path, metadata: object, report: str = f"Assessed {CHANGED}.\n") -> Path:
    run = tmp_path / "run"
    run.mkdir()
    (run / "run.json").write_text(json.dumps(metadata), encoding="utf-8")
    (run / "penetration_test_report.md").write_text(report, encoding="utf-8")
    return run


COMPLETED = {"status": "completed", "scan_results": {"scan_completed": True, "success": True}}


def test_validate_accepts_one_completed_report_naming_changed_source(tmp_path: Path) -> None:
    _scan(tmp_path, COMPLETED)
    scope.validate(tmp_path, [CHANGED])


@pytest.mark.parametrize(
    ("metadata", "report", "message"),
    [
        ([], "", "scan metadata is not an object"),
        ({"status": "completed", "scan_results": ["completed"]}, "", "scan results are not an object"),
        ({"status": "running"}, "", "scan report is incomplete"),
        ({"status": "completed", "scan_results": {"scan_completed": True, "success": False}}, "", "scan report is incomplete"),
        (COMPLETED, "No source named.\n", "does not identify a changed source file"),
    ],
)
def test_validate_rejects_untrusted_report_content(tmp_path: Path, metadata: object, report: str, message: str) -> None:
    _scan(tmp_path, metadata, report)
    with pytest.raises(ValueError, match=message):
        scope.validate(tmp_path, [CHANGED])


def test_validate_rejects_missing_or_linked_output_directory(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="output directory is missing"):
        scope.validate(tmp_path / "absent", [CHANGED])
    real = tmp_path / "real"
    real.mkdir()
    (tmp_path / "linked").symlink_to(real, target_is_directory=True)
    with pytest.raises(ValueError, match="output directory is missing"):
        scope.validate(tmp_path / "linked", [CHANGED])


def test_validate_requires_exactly_one_unlinked_run(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="exactly one current scan report"):
        scope.validate(tmp_path, [CHANGED])
    _scan(tmp_path, COMPLETED)
    (tmp_path / "second").mkdir()
    with pytest.raises(ValueError, match="exactly one current scan report"):
        scope.validate(tmp_path, [CHANGED])


def test_validate_rejects_missing_or_linked_report_files(tmp_path: Path) -> None:
    run = _scan(tmp_path, COMPLETED)
    report = run / "penetration_test_report.md"
    report.unlink()
    with pytest.raises(ValueError, match="missing or linked"):
        scope.validate(tmp_path, [CHANGED])
    elsewhere = tmp_path.parent / f"{tmp_path.name}-report.md"
    elsewhere.write_text(f"Assessed {CHANGED}.\n", encoding="utf-8")
    report.symlink_to(elsewhere)
    with pytest.raises(ValueError, match="missing or linked"):
        scope.validate(tmp_path, [CHANGED])


def test_cli_exits_zero_on_scoped_report_and_one_with_bounded_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _scan(tmp_path, COMPLETED)
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), str(tmp_path), CHANGED])
    runpy.run_path(str(SCRIPT), run_name="__main__")

    monkeypatch.setattr(sys, "argv", [str(SCRIPT)])
    with pytest.raises(SystemExit) as exit_info:
        runpy.run_path(str(SCRIPT), run_name="__main__")
    assert exit_info.value.code == 1
    assert "ERROR: Strix report scope:" in capsys.readouterr().err


def test_validate_accepts_changed_file_named_within_its_reported_directory(tmp_path: Path) -> None:
    """Reports often name the scanned directory once and each file by name (#2291)."""
    _scan(
        tmp_path,
        COMPLETED,
        "Scope: `/workspace/strix-pr-scope.v6Wilu/scripts/ci/`.\n"
        "A security review of `strix_quick_gate.sh` and `strix_model_utils.sh`.\n",
    )
    scope.validate(tmp_path, ["scripts/ci/strix_quick_gate.sh"])


def test_validate_accepts_file_name_ending_a_sentence(tmp_path: Path) -> None:
    _scan(tmp_path, COMPLETED, "Scope: scripts/ci/. The review covered strix_quick_gate.sh.\n")
    scope.validate(tmp_path, ["scripts/ci/strix_quick_gate.sh"])


@pytest.mark.parametrize(
    "report",
    [
        "Reviewed `strix_quick_gate.sh` without naming its directory.\n",
        "Scope: scripts/ci/. Reviewed `my_strix_quick_gate.sh`.\n",
        "Scope: scripts/ci/. Reviewed `strix_quick_gate.sh.bak`.\n",
        "Scope: other/scripts/ci-tools/. Reviewed strix_quick_gate.sh.\n",
    ],
)
def test_validate_rejects_bare_or_partial_file_names(tmp_path: Path, report: str) -> None:
    _scan(tmp_path, COMPLETED, report)
    with pytest.raises(ValueError, match="does not identify a changed source file"):
        scope.validate(tmp_path, ["scripts/ci/strix_quick_gate.sh"])


def test_validate_accepts_file_name_within_a_reported_ancestor_directory(tmp_path: Path) -> None:
    """fast-mlsirm#2052 named the crate directory and the file, not ``src/``."""
    _scan(
        tmp_path,
        COMPLETED,
        "**Scope:** `/workspace/strix-pr-scope.4eyzTL` (including\n"
        "`crates/mlsirm-core` and `python/fast_mlsirm`).\n"
        "- **Rust Audit:** Review of the `two_tier_recursion.rs` and `lib.rs`.\n",
    )
    scope.validate(tmp_path, ["crates/mlsirm-core/src/two_tier_recursion.rs"])


@pytest.mark.parametrize(
    "report",
    [
        "Scope: crates/ only. Reviewed two_tier_recursion.rs.\n",
        "Scope: crates/mlsirm-core-extra. Reviewed two_tier_recursion.rs.\n",
        "Scope: crates/mlsirm-core. Reviewed two_tier_recursion.rs/notes.\n",
        "Scope: crates/mlsirm-core. Reviewed other_recursion.rs.\n",
    ],
)
def test_validate_rejects_generic_or_mismatched_ancestors(tmp_path: Path, report: str) -> None:
    _scan(tmp_path, COMPLETED, report)
    with pytest.raises(ValueError, match="does not identify a changed source file"):
        scope.validate(tmp_path, ["crates/mlsirm-core/src/two_tier_recursion.rs"])
