"""Contract tests for the executable-line coverage integration."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/opencode-review-dispatch.yml"


def test_python_coverage_uses_authoritative_changed_statement_classifier() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "enforce_python_changed_executable_coverage()" in text
    assert "python_changed_executable_lines.py" in text
    assert "--coverage-data" in text
    assert "--minimum 90" in text
    assert "the Python test run did not publish a regular coverage.py data file" in text
    assert "run_python_test_coverage" in text
    assert text.index("run_python_test_coverage") < text.index(
        "enforce_python_changed_executable_coverage"
    )
