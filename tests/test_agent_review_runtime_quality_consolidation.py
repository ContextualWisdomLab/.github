"""Contracts for the single-run agent review runtime quality workflow."""

from __future__ import annotations

import re
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = (
    REPOSITORY_ROOT
    / ".github"
    / "workflows"
    / "agent-review-runtime-quality-ci.yml"
)
RETIRED_WORKFLOWS = (
    "noema-token-lifetime-quality-ci.yml",
    "opencode-rust-coverage-toolchain-quality-ci.yml",
    "strix-changed-path-quality-ci.yml",
    "queue-ownership-quality-ci.yml",
)


def _workflow_text() -> str:
    """Return the consolidated workflow source."""

    return WORKFLOW_PATH.read_text(encoding="utf-8")


def test_quality_workflows_are_replaced_by_one_owner() -> None:
    """Retire independent trigger surfaces after full delta succession."""

    assert WORKFLOW_PATH.is_file()
    for retired_name in RETIRED_WORKFLOWS:
        assert not (
            REPOSITORY_ROOT / ".github" / "workflows" / retired_name
        ).exists()


def test_pr_concurrency_cancels_only_the_same_workflow_repository_and_pr() -> None:
    """Bind stale-run cancellation to the required three-part PR identity."""

    workflow = _workflow_text()
    concurrency_contract = workflow.split("concurrency:", 1)[1].split(
        "permissions:", 1
    )[0]

    assert (
        "group: agent-review-runtime-quality-"
        "${{ github.repository }}-${{ github.event.pull_request.number }}"
        in concurrency_contract
    )
    assert "cancel-in-progress: true" in concurrency_contract
    assert "github.sha" not in concurrency_contract
    assert "head.sha" not in concurrency_contract
    assert "github.ref" not in concurrency_contract


def test_consolidated_workflow_materializes_one_runner_job() -> None:
    """Avoid three independent checkouts and dependency boot sequences."""

    workflow = _workflow_text()

    assert workflow.count("runs-on:") == 1
    assert workflow.count("actions/checkout@") == 1
    assert workflow.count("actions/setup-python@") == 1
    assert "workflow_dispatch:" not in workflow
    assert "gh api" not in workflow
    assert re.search(r"(?m)^[ \t]*sleep[ \t]+", workflow) is None


def test_consolidated_workflow_preserves_all_contract_suites() -> None:
    """Keep the retired Noema, OpenCode, and Strix evidence in one job."""

    workflow = _workflow_text()

    for required_path in (
        "tests/test_noema_reviewer_token_lifetime.py",
        "tests/test_noema_two_phase_handoff.py",
        "tests/test_noema_refreshed_app_identity.py",
        "tests/test_noema_token_lifetime_stale_run_contract.py",
        "tests/test_opencode_rust_coverage_toolchain_contract.py",
        "tests/test_docs_only_pr_runner_admission.py",
        "tests/test_strix_changed_path_policy.py",
        "tests/test_strix_model_behavior_error.py",
        "tests/test_strix_nvidia_nim_not_found_fallback.py",
        "tests/test_strix_workflow_dependency_hashes.py",
        "tests/test_strix_quality_timeout_fixture_budget.py",
        "scripts/ci/test_strix_quick_gate.sh",
        "tests/test_org_sweep_queue_hygiene_owner.py",
    ):
        assert required_path in workflow


def test_exact_head_is_verified_before_selected_suites_run() -> None:
    """Reject a checkout that differs from the pull request's current head."""

    workflow = _workflow_text()
    selector = workflow.split(
        "- name: Select affected contract suites", 1
    )[1].split("- name: Install exact hash-verified base dependencies", 1)[0]

    assert 'test "$(git rev-parse HEAD)" = "$HEAD_SHA"' in selector
    assert 'git diff --name-only "$BASE_SHA...$HEAD_SHA"' in selector
