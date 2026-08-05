"""Contract tests for exact-head trusted uv materializer quality evidence."""

from pathlib import Path


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
    for required_path in required_paths:
        assert workflow.count(required_path) == 2


def test_quality_workflow_pins_actions_and_uses_read_only_permissions() -> None:
    """Quality evidence executes from the exact PR head with least privilege."""

    workflow = _workflow_text()

    assert "permissions:\n  contents: read" in workflow
    assert workflow.count(
        "step-security/harden-runner@bf7454d06d71f1098171f2acdf0cd4708d7b5920"
    ) == 2
    assert workflow.count(
        "actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0"
    ) == 2
    assert workflow.count(
        "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97"
    ) == 2
    assert workflow.count("persist-credentials: false") == 2
    assert workflow.count("ref: ${{ github.event.pull_request.head.sha }}") == 2


def test_minimum_python_contract_exercises_the_tomli_fallback() -> None:
    """Python 3.10 imports production through a deterministic local tomli stub."""

    workflow = _workflow_text()

    assert 'python-version: "3.10"' in workflow
    assert "python -m compileall -q scripts/ci/materialize_base_python_requirements.py" in workflow
    assert 'stub_root / "tomli.py"' in workflow
    assert "materializer.tomllib.STUB_MARKER is True" in workflow


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
    assert "python -m coverage run -m pytest tests -q" in workflow
    assert "unset COVERAGE_RCFILE" in workflow
    assert "python -m interrogate --fail-under 100" in workflow
    assert "python -m compileall -q" in workflow

    required_tests = (
        "tests/test_materialize_base_python_requirements.py",
        "tests/test_materialize_uv_export_hash_contract.py",
        "tests/test_trusted_uv_download_contract.py",
        "tests/test_trusted_git_executable.py",
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
