"""Static contract tests for the central control-plane quality workflow."""

from __future__ import annotations

from pathlib import Path


WORKFLOW_PATH = Path(".github/workflows/control-plane-quality-ci.yml")
PRODUCTION_MODULES = (
    "scripts.ci.agent_mention_router",
    "scripts.ci.agent_mention_sweep",
    "scripts.ci.install_base_python_locks",
    "scripts.ci.javascript_coverage_gate",
    "scripts.ci.redact_sensitive_log",
    "scripts.ci.sandboxed_verify",
    "scripts.ci.sandboxed_web_e2e",
)
PRODUCTION_PATHS = tuple(module.replace(".", "/") + ".py" for module in PRODUCTION_MODULES)


def workflow_text() -> str:
    """Return the quality workflow as UTF-8 text for deterministic assertions."""
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def test_quality_workflow_uses_least_privilege_and_immutable_actions() -> None:
    """Pin the workflow to read-only permissions and reviewed action revisions."""
    text = workflow_text()

    assert "name: Central Control Plane Quality CI" in text
    assert "permissions:\n  contents: read" in text
    assert "contents: write" not in text
    assert "pull-requests: write" not in text
    assert "actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0" in text
    assert "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97" in text
    assert "step-security/harden-runner@bf7454d06d71f1098171f2acdf0cd4708d7b5920" in text


def test_quality_workflow_proves_supported_python_and_locked_tooling() -> None:
    """Require Python 3.10 compatibility and a hash-locked Python 3.14 gate."""
    text = workflow_text()

    assert 'python-version: "3.10"' in text
    assert 'python-version: "3.14"' in text
    assert "requirements-opencode-review-ci-hashes.txt" in text
    assert "--require-hashes" in text
    assert "python -m compileall -q" in text
    assert 'GITHUB_EVENT_PATH: ""' in text


def test_quality_workflow_enforces_complete_coverage_and_docstrings() -> None:
    """Require every changed production module to reach complete branch evidence."""
    text = workflow_text()

    assert "python -m coverage run" in text
    assert "--branch" in text
    assert "--include=" in text
    assert "python -m coverage report --show-missing --fail-under=100" in text
    assert "python -m interrogate" in text
    assert "--fail-under 100" in text
    assert "--cov=" not in text
    for path in PRODUCTION_PATHS:
        assert path in text


def test_quality_workflow_runs_its_own_regression_contract() -> None:
    """Keep the workflow self-verifying whenever its implementation changes."""
    text = workflow_text()

    assert "tests/test_control_plane_quality_workflow_contract.py" in text
    assert '".github/workflows/control-plane-quality-ci.yml"' in text
    assert "copilot" not in text.casefold()
    assert "schedule:" not in text
