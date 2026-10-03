"""Contract tests for exact-head trusted uv materializer quality evidence."""

from pathlib import Path


WORKFLOW_PATH = Path(".github/workflows/trusted-uv-materializer-quality-ci.yml")
<<<<<<< HEAD
=======
OPENCODE_REQUIREMENTS_PATH = Path("requirements-opencode-review-ci.txt")
>>>>>>> 38a1692b (merge: integrate latest review authority into CodeQL owner)


def _workflow_text() -> str:
    """Return the trusted uv materializer quality workflow as UTF-8 text."""

    return WORKFLOW_PATH.read_text(encoding="utf-8")


<<<<<<< HEAD
def test_quality_workflow_runs_for_every_materializer_surface() -> None:
    """Changes to production, tests, tooling, or the gate itself trigger evidence."""

    workflow = _workflow_text()

    required_paths = (
=======
def test_full_quality_gate_installs_yaml_parser_used_by_repository_tests() -> None:
    """The complete suite installs the parser imported during collection."""

    requirements = OPENCODE_REQUIREMENTS_PATH.read_text(encoding="utf-8")

    assert "pyyaml==6.0.3" in requirements.lower()


def test_quality_workflow_runs_for_every_materializer_surface_and_main_push() -> None:
    """PR owner-surface changes trigger evidence and every main push runs the full gate."""

    workflow = _workflow_text()

    required_pr_paths = (
>>>>>>> 38a1692b (merge: integrate latest review authority into CodeQL owner)
        '".github/workflows/trusted-uv-materializer-quality-ci.yml"',
        '"scripts/ci/materialize_base_python_requirements.py"',
        '"tests/conftest.py"',
        '"tests/test_materialize*.py"',
        '"tests/test_trusted_uv*.py"',
        '"tests/test_uv*.py"',
        '"tests/test_repository_branch_coverage_*.py"',
        '"requirements-opencode-review-ci-hashes.txt"',
<<<<<<< HEAD
        '"pyproject.toml"',
    )
    for required_path in required_paths:
        assert workflow.count(required_path) == 2


def test_quality_workflow_pins_actions_and_uses_read_only_permissions() -> None:
    """Quality evidence executes from the exact PR head with least privilege."""
=======
        '"requirements-noema-document-ci-hashes.txt"',
        '"pyproject.toml"',
    )
    for required_path in required_pr_paths:
        assert workflow.count(required_path) == 1

    push_block = workflow.split("  push:\n", 1)[1].split("\nconcurrency:", 1)[0]
    assert "    branches: [main]" in push_block
    assert "    paths:" not in push_block


def test_quality_workflow_pins_actions_and_uses_read_only_permissions() -> None:
    """One hardened job checks out the exact PR head or the exact main-push SHA."""
>>>>>>> 38a1692b (merge: integrate latest review authority into CodeQL owner)

    workflow = _workflow_text()

    assert "permissions:\n  contents: read" in workflow
    assert workflow.count(
        "step-security/harden-runner@b09bb98e06d4d774595224525879c09bc6e98c40"
<<<<<<< HEAD
    ) == 2
    assert workflow.count(
        "actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0"
    ) == 2
    assert workflow.count(
        "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97"
    ) == 2
    assert workflow.count("persist-credentials: false") == 2
    assert workflow.count("ref: ${{ github.event.pull_request.head.sha }}") == 2
=======
    ) == 1
    assert workflow.count(
        "actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0"
    ) == 1
    assert workflow.count(
        "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97"
    ) == 2
    assert workflow.count("persist-credentials: false") == 1
    assert workflow.count("fetch-depth: 0") == 1
    assert workflow.count(
        "ref: ${{ github.event.pull_request.head.sha || github.sha }}"
    ) == 1
    assert "runs-on: ubuntu-24.04" in workflow
    assert "timeout-minutes: 30" in workflow
>>>>>>> 38a1692b (merge: integrate latest review authority into CodeQL owner)


def test_minimum_python_contract_exercises_the_tomli_fallback() -> None:
    """Python 3.10 imports production through a deterministic local tomli stub."""

    workflow = _workflow_text()

    assert 'python-version: "3.10"' in workflow
    assert "python -m compileall -q scripts/ci/materialize_base_python_requirements.py" in workflow
    assert 'stub_root / "tomli.py"' in workflow
    assert "materializer.tomllib.STUB_MARKER is True" in workflow
<<<<<<< HEAD
=======
    assert "id: minimum_python" in workflow
    assert "steps.minimum_python.outcome == 'success'" in workflow
    assert "steps.minimum_python.outcome == 'failure'" in workflow
>>>>>>> 38a1692b (merge: integrate latest review authority into CodeQL owner)


def test_full_quality_gate_proves_tests_coverage_docstrings_and_compilation() -> None:
    """The stable runtime proves complete deterministic production evidence."""

    workflow = _workflow_text()

    assert 'python-version: "3.14"' in workflow
    assert (
<<<<<<< HEAD
        "python -m pip install --disable-pip-version-check --require-hashes "
        "-r requirements-opencode-review-ci-hashes.txt"
    ) in workflow
=======
        "cache-dependency-path: |\n"
        "            requirements-opencode-review-ci-hashes.txt\n"
        "            requirements-noema-document-ci-hashes.txt"
    ) in workflow
    assert "python -m pip install --disable-pip-version-check --require-hashes" in workflow
    assert "-r requirements-opencode-review-ci-hashes.txt" in workflow
    assert "-r requirements-noema-document-ci-hashes.txt" in workflow
>>>>>>> 38a1692b (merge: integrate latest review authority into CodeQL owner)
    assert "branch = True" in workflow
    assert "scripts/ci/materialize_base_python_requirements.py" in workflow
    assert "fail_under = 100" in workflow
    assert "python -m coverage report" in workflow
<<<<<<< HEAD
    assert "python -m coverage run -m pytest tests -q" in workflow
=======
    assert "python -m coverage run -m pytest tests -q -W error" in workflow
>>>>>>> 38a1692b (merge: integrate latest review authority into CodeQL owner)
    assert "unset COVERAGE_RCFILE" in workflow
    assert "python -m interrogate --fail-under 100" in workflow
    assert "python -m compileall -q" in workflow

    required_tests = (
        "tests/test_materialize_base_python_requirements.py",
        "tests/test_materialize_uv_export_hash_contract.py",
        "tests/test_trusted_uv_download_contract.py",
        "tests/test_trusted_uv_portability_and_streaming.py",
        "tests/test_uv_export_isolation_contract.py",
<<<<<<< HEAD
=======
        "tests/test_uv_flat_lock_publication_boundary.py",
>>>>>>> 38a1692b (merge: integrate latest review authority into CodeQL owner)
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
