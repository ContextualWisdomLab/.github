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
    coverage_call = text.index("run_python_test_coverage\n", text.index("measured_any=0"))
    enforcement_call = text.index(
        "enforce_python_changed_executable_coverage \"$project_dir\"", coverage_call
    )
    assert coverage_call < enforcement_call
    assert "--project-dir \"$project_dir\"" in text
    assert 'printf \'%s\\n\' "."' in text


def test_python_coverage_discovers_root_and_nested_projects_without_duplicates() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    discovery = text[text.index("tracked_python_projects_with_tests()") :]
    discovery = discovery[: discovery.index("verify_trusted_python_test_toolchain()")]
    assert "sort -u" in discovery
    assert 'if [ -d tests ] && trusted_git ls-files \'*.py\' | grep -q .' in discovery
    assert 'printf \'%s\\n\' "."' in discovery
    assert 'project_dir="$(dirname "$pyproject_file")"' in discovery
    assert discovery.index("{\n") < discovery.index("} | sort -u")
