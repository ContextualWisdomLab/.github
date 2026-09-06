"""Contracts for the single-runner exact artifact quality workflow."""

from __future__ import annotations

from tests.test_required_workflow_queue_contract import (
    workflow_level_cancels_in_progress,
)

import re
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = (
    REPOSITORY_ROOT
    / ".github"
    / "workflows"
    / "agent-review-runtime-quality-ci.yml"
)


def _workflow_text() -> str:
    """Return the exact artifact quality workflow source."""

    return WORKFLOW_PATH.read_text(encoding="utf-8")


def test_exact_artifact_quality_uses_one_runner_boot() -> None:
    """Compile both supported Python versions without a second runner job."""

    workflow = _workflow_text()

    assert workflow.count("runs-on:") == 1
    assert workflow.count("step-security/harden-runner@") == 1
    assert workflow.count("actions/checkout@") == 1
    assert workflow.count('python-version: "3.10"') == 1
    assert workflow.count('python-version: "3.14"') == 2


def test_minimum_python_compile_precedes_current_python_contracts() -> None:
    """Keep the Python 3.10 syntax gate before the Python 3.14 test suite."""

    workflow = _workflow_text()

    minimum_setup = workflow.index(
        "- name: Set up minimum supported Python for exact-artifact contracts"
    )
    minimum_compile = workflow.index(
        "- name: Compile exact-artifact production and contracts on Python 3.10"
    )
    current_setup = workflow.index(
        "- name: Restore Python 3.14 for exact-artifact contracts"
    )
    current_contract = workflow.index(
        "- name: Verify exact-artifact SBOM attestation contracts on Python 3.14"
    )

    assert minimum_setup < minimum_compile < current_setup < current_contract


def test_pr_concurrency_uses_workflow_repository_and_pr_identity() -> None:
    """Cancel only an older run of this workflow for the same repository and PR."""

    workflow = _workflow_text()
    concurrency = workflow.split("concurrency:", 1)[1].split(
        "permissions:", 1
    )[0]

    assert (
        "group: agent-review-runtime-quality-"
        "${{ github.repository }}-"
        "${{ github.event.pull_request.number }}"
        in concurrency
    )
    assert workflow_level_cancels_in_progress(workflow)
    assert "github.sha" not in concurrency
    assert "pull_request.head.sha" not in concurrency


def test_successor_keeps_exact_head_hash_lock_and_read_only_permissions() -> None:
    """Reuse the consolidated trust boundary without weakening SBOM evidence."""

    workflow = _workflow_text()
    permissions = workflow.split("permissions:", 1)[1].split("jobs:", 1)[0]
    selector = workflow.split(
        "- name: Select affected contract suites", 1
    )[1].split("- name: Install exact hash-verified base dependencies", 1)[0]

    assert "contents: read" in permissions
    assert "write" not in permissions
    assert 'test "$(git rev-parse HEAD)" = "$HEAD_SHA"' in selector
    assert "--require-hashes" in workflow
    assert "requirements-opencode-review-ci-hashes.txt" in workflow


def test_successor_preserves_all_exact_artifact_contracts() -> None:
    """Retain every predecessor test, coverage, docstring, and syntax gate."""

    workflow = _workflow_text()

    for required_path in (
        "scripts/ci/verify_exact_artifact_sbom_handoff.py",
        "tests/test_exact_artifact_sbom_attestation_contract.py",
        "tests/test_exact_artifact_sbom_review_regressions.py",
        "tests/test_verify_exact_artifact_sbom_handoff.py",
        "tests/test_exact_artifact_quality_single_runner.py",
    ):
        assert required_path in workflow

    assert "coverage run --branch" in workflow
    assert "--fail-under=100" in workflow
    assert "interrogate --fail-under=100" in workflow
    exact_artifact_steps = workflow[
        workflow.index(
            "- name: Set up minimum supported Python for exact-artifact contracts"
        ) : workflow.index("- name: Verify consolidated workflow contract")
    ]
    assert exact_artifact_steps.count("compileall -q") == 2


def test_quality_runner_has_no_polling_or_runner_held_sleep() -> None:
    """Keep the quality lane deterministic and free of API polling waits."""

    workflow = _workflow_text()

    assert "gh api" not in workflow
    assert re.search(r"(?m)^[ \t]*sleep[ \t]+", workflow) is None
    assert "workflow_dispatch:" not in workflow
