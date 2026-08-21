"""Contract tests for exact-head control-plane SLI receipt quality evidence."""

from pathlib import Path


WORKFLOW_PATH = Path(".github/workflows/control-plane-sli-receipt-quality-ci.yml")


def _workflow_text() -> str:
    """Return the control-plane SLI receipt quality workflow as UTF-8 text."""

    return WORKFLOW_PATH.read_text(encoding="utf-8")


def test_quality_workflow_runs_for_every_receipt_surface() -> None:
    """ADR, collector, tests, and the gate itself must retrigger exact-head evidence."""

    workflow = _workflow_text()
    required_paths = (
        '".github/workflows/control-plane-sli-receipt-quality-ci.yml"',
        '"scripts/ci/control_plane_sli_receipt.py"',
        '"tests/test_control_plane_sli_receipt.py"',
        '"tests/test_control_plane_sli_receipt_quality_workflow_contract.py"',
        '"docs/doctoring/control-plane-sli-receipts.md"',
        '"AGENTS.md"',
        '"ARCHITECTURE.md"',
        '"CLAUDE.md"',
        '"CHANGELOG.md"',
    )
    for required_path in required_paths:
        assert required_path in workflow


def test_quality_workflow_pins_actions_and_uses_read_only_permissions() -> None:
    """Quality evidence executes from the exact PR head with least privilege."""

    workflow = _workflow_text()
    assert "permissions:\n  contents: read" in workflow
    assert "contents: write" not in workflow
    assert "persist-credentials: false" in workflow
    assert "actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0" in workflow
    assert "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97" in workflow
    assert "ref: ${{ github.event.pull_request.head.sha || github.sha }}" in workflow
    assert (
        'test "$(git rev-parse HEAD)" = "${{ github.event.pull_request.head.sha || github.sha }}"'
        in workflow
    )


def test_quality_workflow_proves_coverage_docstrings_and_compilation() -> None:
    """The gate proves 100% branch coverage, public docstrings, and compilation."""

    workflow = _workflow_text()
    assert "python -m pip install --disable-pip-version-check --require-hashes" in workflow
    assert "-r requirements-opencode-review-ci-hashes.txt" in workflow
    assert "--source=scripts.ci.control_plane_sli_receipt" in workflow
    assert "python -m coverage report --show-missing --fail-under=100" in workflow
    assert "python -m interrogate --fail-under 100 --ignore-init-method" in workflow
    assert "python -m compileall -q" in workflow
    assert "python -m pytest tests -q" in workflow
    assert "git diff --check" in workflow
