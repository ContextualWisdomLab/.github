"""Contract tests for exact-head trusted uv materializer quality evidence."""

from pathlib import Path


WORKFLOW_PATH = Path(".github/workflows/trusted-uv-materializer-quality-ci.yml")
AGENT_MENTION_WORKFLOW_PATH = Path(
    ".github/workflows/agent-mention-router-quality-ci.yml"
)
AGENT_RUNTIME_WORKFLOW_PATH = Path(
    ".github/workflows/agent-review-runtime-quality-ci.yml"
)
REPOSITORY_METADATA_WORKFLOW_PATH = Path(
    ".github/workflows/repository-metadata-reconcile.yml"
)


def _workflow_text() -> str:
    """Return the trusted uv materializer quality workflow as UTF-8 text."""

    return WORKFLOW_PATH.read_text(encoding="utf-8")


def test_quality_workflow_runs_for_every_materializer_surface() -> None:
    """Changes to production, tests, tooling, or the gate itself trigger evidence."""

    workflow = _workflow_text()

    required_paths = (
        '".github/workflows/trusted-uv-materializer-quality-ci.yml"',
        '"scripts/ci/materialize_base_python_requirements.py"',
        '"scripts/ci/verify_release_maturin_tool_assets.py"',
        '"tests/conftest.py"',
        '"tests/test_materialize*.py"',
        '"tests/test_trusted_uv*.py"',
        '"tests/test_uv*.py"',
        '"tests/test_repository_branch_coverage_*.py"',
        '"tests/test_verify_release_maturin_tool_assets.py"',
        '"requirements-opencode-review-ci-hashes.txt"',
        '"requirements-opencode-review-ci.txt"',
        '"requirements-noema-document-ci.txt"',
        '"scripts/ci/compile_opencode_review_lock.sh"',
        '"pyproject.toml"',
    )
    for required_path in required_paths:
        assert workflow.count(required_path) == 2


def test_quality_workflow_admits_stacked_pull_requests() -> None:
    """A non-default canonical owner base must not suppress exact-head evidence."""

    pull_request_trigger = _workflow_text().split("  pull_request:\n", 1)[1].split(
        "  push:\n", 1
    )[0]

    assert "branches:" not in pull_request_trigger


def test_quality_workflow_pins_actions_and_uses_read_only_permissions() -> None:
    """Quality evidence executes from the exact PR head with least privilege."""

    workflow = _workflow_text()

    assert "permissions:\n  contents: read" in workflow
    assert workflow.count(
        "step-security/harden-runner@b09bb98e06d4d774595224525879c09bc6e98c40"
    ) == 2
    assert workflow.count(
        "actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0"
    ) == 2
    assert workflow.count(
        "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97"
    ) == 2
    assert workflow.count("persist-credentials: false") == 2
    assert workflow.count("ref: ${{ github.event.pull_request.head.sha }}") == 2
    minimum_job, full_job = workflow.split("  full-quality-gate:\n", 1)
    assert "fetch-depth: 0" not in minimum_job
    assert full_job.count("fetch-depth: 0") == 1


def test_common_lock_source_changes_trigger_every_direct_consumer() -> None:
    """Every workflow installing the generated common lock tracks its sources."""

    tracked_inputs = (
        '"requirements-opencode-review-ci.txt"',
        '"requirements-noema-document-ci.txt"',
        '"scripts/ci/compile_opencode_review_lock.sh"',
    )
    consumer_paths = (
        (AGENT_MENTION_WORKFLOW_PATH, 2),
        (AGENT_RUNTIME_WORKFLOW_PATH, 1),
        (REPOSITORY_METADATA_WORKFLOW_PATH, 1),
    )
    for workflow_path, expected_count in consumer_paths:
        workflow = workflow_path.read_text(encoding="utf-8")
        for tracked_input in tracked_inputs:
            assert workflow.count(tracked_input) == expected_count


def test_metadata_consumer_tracks_the_generated_common_lock() -> None:
    """The metadata workflow must run when its installed lock changes."""

    workflow = REPOSITORY_METADATA_WORKFLOW_PATH.read_text(encoding="utf-8")

    assert workflow.count('"requirements-opencode-review-ci-hashes.txt"') == 1


def test_common_lock_source_declares_the_transitive_parser_inputs() -> None:
    """The reviewed source binds both parser requirements regenerated in the lock."""

    source = Path("requirements-opencode-review-ci.txt").read_text(encoding="utf-8")
    lock = Path("requirements-opencode-review-ci-hashes.txt").read_text(
        encoding="utf-8"
    )

    assert "-r requirements-noema-document-ci.txt" in source
    assert "PyYAML==6.0.3" in source
    assert "defusedxml==0.7.1" in lock
    assert "pyyaml==6.0.3" in lock


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
