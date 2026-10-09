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
        json.dumps({"status": "completed", "scan_results": {"scan_completed": True, "success": True}}),
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


@pytest.mark.parametrize("report, changed, accepted", [
    (SCOPED_DIRECTORY_REPORT, ["crates/mlsirm-core/src/lib.rs"], True),
    (SCOPED_DIRECTORY_REPORT, ["docs/methods.md"], False),
    ("Scope: `/workspace/strix-pr-scope.AoFHD6/`", ["src/main.rs"], False),
])
def test_scope_directory_binding_in_process(tmp_path, report, changed, accepted):
    """Directory scope must contain a changed path, not merely name the root."""
    _completed_run(tmp_path, report)
    if accepted:
        scope.validate(tmp_path, changed)
    else:
        with pytest.raises(ValueError, match="changed source"):
            scope.validate(tmp_path, changed)
