"""Contract tests for exact-head trusted uv materializer quality evidence."""

from pathlib import Path
import shlex
import subprocess
import sys
import tomllib

import pytest


WORKFLOW_PATH = Path(".github/workflows/trusted-uv-materializer-quality-ci.yml")


def _workflow_text() -> str:
    """Return the trusted uv materializer quality workflow as UTF-8 text."""

    return WORKFLOW_PATH.read_text(encoding="utf-8")


def test_quality_workflow_runs_for_every_materializer_surface() -> None:
    """Changes to production, tests, tooling, or the gate itself trigger evidence."""

    workflow = _workflow_text()

    required_paths = (
        '".github/workflows/trusted-uv-materializer-quality-ci.yml"',
        '"scripts/ci/materialize_base_python_requirements.py"',
        '"tests/conftest.py"',
        '"tests/test_materialize*.py"',
        '"tests/test_trusted_uv*.py"',
        '"tests/test_uv*.py"',
        '"tests/test_repository_branch_coverage_*.py"',
        '"requirements-opencode-review-ci-hashes.txt"',
        '"pyproject.toml"',
    )
    pr_trigger, push_trigger = workflow.split("on:\n", 1)[1].split(
        "\nconcurrency:\n", 1
    )[0].split("  push:\n", 1)
    for required_path in required_paths:
        assert required_path in pr_trigger
    assert push_trigger.strip() == "branches: [main]"
    assert workflow.count("runs-on:") == 1
    assert not WORKFLOW_PATH.with_name("main-full-suite-gate.yml").exists()


def test_quality_workflow_pins_actions_and_uses_read_only_permissions() -> None:
    """Quality evidence executes from the exact PR head with least privilege."""

    workflow = _workflow_text()

    assert "permissions:\n  contents: read" in workflow
    assert workflow.count(
        "step-security/harden-runner@b09bb98e06d4d774595224525879c09bc6e98c40"
    ) == 1
    assert workflow.count(
        "actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0"
    ) == 1
    assert workflow.count(
        "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97"
    ) == 2
    assert workflow.count("persist-credentials: false") == 1
    assert workflow.count(
        "ref: ${{ github.event.pull_request.head.sha || github.sha }}"
    ) == 1


def test_minimum_python_contract_exercises_the_tomli_fallback() -> None:
    """Python 3.10 imports production through a deterministic local tomli stub."""

    workflow = _workflow_text()

    assert 'python-version: "3.10"' in workflow
    assert "python -m compileall -q scripts/ci/materialize_base_python_requirements.py" in workflow
    assert 'stub_root / "tomli.py"' in workflow
    assert "materializer.tomllib.STUB_MARKER is True" in workflow
    assert workflow.index('python-version: "3.10"') < workflow.index(
        "materializer.tomllib.STUB_MARKER is True"
    ) < workflow.index('python-version: "3.14"')


def test_full_quality_gate_proves_tests_coverage_docstrings_and_compilation() -> None:
    """The stable runtime proves complete deterministic production evidence."""

    workflow = _workflow_text()

    assert 'python-version: "3.14"' in workflow
    assert (
        "python -m pip install --disable-pip-version-check --require-hashes "
        "-r requirements-opencode-review-ci-hashes.txt"
    ) in workflow
    assert "branch = True" in workflow
    assert "scripts/ci/materialize_base_python_requirements.py" in workflow
    assert "fail_under = 100" in workflow
    assert "python -m coverage report" in workflow
    assert workflow.count("python -m coverage run -m pytest tests -q -W error") == 1
    assert "unset COVERAGE_RCFILE" in workflow
    assert "run: python -m interrogate --fail-under 100\n" in workflow
    assert tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))[
        "tool"
    ]["interrogate"] == {"exclude": ["tests"], "fail-under": 100}
    assert "python -m compileall -q" in workflow

    required_tests = (
        "tests/test_materialize_base_python_requirements.py",
        "tests/test_materialize_uv_export_hash_contract.py",
        "tests/test_trusted_uv_download_contract.py",
        "tests/test_trusted_uv_portability_and_streaming.py",
        "tests/test_uv_export_isolation_contract.py",
        "tests/test_uv_redirect_and_coverage_contract.py",
        "tests/test_uv_redirect_boundary.py",
        "tests/test_uv_workspace_fail_closed.py",
        "tests/test_trusted_uv_materializer_quality_workflow_contract.py",
        "tests/test_repository_branch_coverage_javascript_and_noema.py",
        "tests/test_repository_branch_coverage_review_schedulers.py",
        "tests/test_repository_branch_coverage_execution_sandboxes.py",
        "tests/test_repository_branch_coverage_reporting_edges.py",
    )
    for test_path in required_tests:
        assert test_path in workflow


def test_minimum_version_failure_does_not_skip_the_full_suite() -> None:
    """Native status guards preserve both contracts without forgiving failures."""
    workflow = _workflow_text()
    assert "continue-on-error:" not in workflow
    minimum_setup = workflow.split("- name: Set up minimum supported Python", 1)[1].split(
        "- name: Compile production on Python 3.10", 1
    )[0]
    assert "id: minimum_python" in minimum_setup
    for step_name, step_id, condition in (
        (
            "Set up current stable Python", "stable_python",
            "!cancelled() && (steps.minimum_python.outcome == 'success' || "
            "steps.minimum_python.outcome == 'failure')",
        ),
        (
            "Install hash-locked quality tooling", "quality_tooling",
            "!cancelled() && steps.stable_python.outcome == 'success'",
        ),
        (
            "Run trusted uv tests with complete branch coverage", "",
            "!cancelled() && steps.quality_tooling.outcome == 'success'",
        ),
        (
            "Run complete central test and branch coverage gate", "",
            "!cancelled() && steps.quality_tooling.outcome == 'success'",
        ),
        (
            "Enforce complete production docstrings", "",
            "!cancelled() && steps.quality_tooling.outcome == 'success'",
        ),
        (
            "Compile production and quality contracts", "",
            "!cancelled() && steps.stable_python.outcome == 'success'",
        ),
    ):
        step = workflow.split(f"- name: {step_name}\n", 1)[1].split("- name:", 1)[0]
        assert f"if: ${{{{ {condition} }}}}" in step
        if step_id:
            assert f"id: {step_id}" in step


@pytest.mark.parametrize("emits_warning", (False, True))
def test_full_suite_command_rejects_warnings(tmp_path: Path, emits_warning: bool) -> None:
    """Run the real workflow command against clean and warning-emitting tests."""
    command_line = next(
        line.strip() for line in _workflow_text().splitlines()
        if line.strip().startswith("python -m coverage run -m pytest tests ")
    )
    test_directory = tmp_path / "tests"
    test_directory.mkdir()
    (test_directory / "test_warning_contract.py").write_text(
        "import warnings\ndef test_fixture():\n    "
        + ("warnings.warn('quality-gate-fixture', UserWarning)" if emits_warning else "assert True")
        + "\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, *shlex.split(command_line)[1:]],
        cwd=tmp_path,
        env={"PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == (1 if emits_warning else 0), result.stdout + result.stderr
    assert ("1 failed" if emits_warning else "1 passed") in result.stdout
    if emits_warning:
        assert "UserWarning: quality-gate-fixture" in result.stdout
