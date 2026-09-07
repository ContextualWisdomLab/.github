"""Contracts for the single-run agent review runtime quality workflow."""

from __future__ import annotations

from tests.test_required_workflow_queue_contract import (
    workflow_level_cancels_in_progress,
)

import re
import subprocess
from pathlib import Path

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = (
    REPOSITORY_ROOT
    / ".github"
    / "workflows"
    / "agent-review-runtime-quality-ci.yml"
)
RETIRED_WORKFLOWS = (
    "exact-artifact-sbom-attestation-quality.yml",
    "hourly-nvidia-nim-review-repair.yml",
    "organization-commercial-readiness-loop-quality-ci.yml",
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
    assert workflow_level_cancels_in_progress(workflow)
    assert "github.sha" not in concurrency_contract
    assert "head.sha" not in concurrency_contract
    assert "github.ref" not in concurrency_contract


def test_consolidated_workflow_materializes_one_runner_job() -> None:
    """Avoid three independent checkouts and dependency boot sequences."""

    workflow = _workflow_text()

    assert workflow.count("runs-on:") == 1
    assert workflow.count("actions/checkout@") == 1
    assert workflow.count("actions/setup-python@") == 3
    assert "workflow_dispatch:" not in workflow
    assert "gh api" not in workflow
    assert re.search(r"(?m)^[ \t]*sleep[ \t]+", workflow) is None
    self_test_step = workflow.split("- name: Verify consolidated workflow contract", 1)[1]
    assert "if:" not in self_test_step
    assert "python -m pytest -q tests/test_agent_review_runtime_quality_consolidation.py" in self_test_step


def test_changelog_only_edits_do_not_boot_the_consolidated_runner() -> None:
    """A release-note-only change needs no agent runtime contract suite."""

    trigger = _workflow_text().split("on:\n", 1)[1].split("\nconcurrency:\n", 1)[0]

    assert '      - "CHANGELOG.md"' not in trigger


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
        "scripts/ci/pr_review_conflict_scope.py",
        "scripts/ci/pr_review_autofix_context.py",
        "scripts/ci/zdr_policy.py",
        "scripts/ci/contextual_orchestrator_review_policy.py",
        "scripts/ci/contextual_orchestrator_review_launcher.py",
        "tests/test_pr_review_fix_hourly_contract.py",
        "tests/test_pr_review_autofix_writer_security_contract.py",
        "scripts/ci/organization_commercial_readiness_loop.py",
        "organization_commercial_readiness_fixtures.py",
        "tests/test_organization_commercial_readiness_loop*.py",
        "scripts/ci/verify_exact_artifact_sbom_handoff.py",
        "tests/test_exact_artifact_sbom_attestation_contract.py",
        "tests/test_exact_artifact_sbom_review_regressions.py",
        "tests/test_verify_exact_artifact_sbom_handoff.py",
        "tests/test_exact_artifact_quality_single_runner.py",
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


def test_review_repair_suite_is_selected_and_conditionally_executed() -> None:
    """Run review-repair contracts only when their owned paths change."""

    workflow = _workflow_text()

    assert "review_repair_suite=false" in workflow
    assert "echo \"review_repair=$review_repair_suite\"" in workflow
    assert "scripts/ci/pr_review_fix_scheduler.py" in workflow
    assert (
        "if: steps.affected_suites.outputs.review_repair == 'true'" in workflow
    )
    assert workflow.count("runs-on:") == 1


@pytest.mark.parametrize(
    ("changed_path", "starts_runner", "review_repair", "queue"),
    (
        ("scripts/ci/pr_review_merge_scheduler.py", True, True, False),
        ("scripts/ci/pr_review_merge_scheduler_core.py", True, True, False),
        ("tests/test_pr_review_merge_scheduler.py", True, True, False),
        ("tests/test_agent_review_runtime_quality_consolidation.py", True, False, False),
        (".github/workflows/pr-review-merge-scheduler.yml", True, True, True),
        ("scripts/ci/current_head_run_coalescer.py", True, False, True),
        ("CHANGELOG.md", False, False, False),
    ),
)
def test_merge_scheduler_changes_start_and_select_contracts(
    changed_path: str, starts_runner: bool, review_repair: bool, queue: bool
) -> None:
    """Bind scheduler changes to both runner admission and the real selector."""
    workflow = _workflow_text()
    trigger = workflow.split("on:\n", 1)[1].split("\nconcurrency:\n", 1)[0]
    assert (f'      - "{changed_path}"' in trigger) is starts_runner

    selector = workflow.split('            case "$changed_path" in\n', 1)[1].split(
        "            esac", 1
    )[0]
    result = subprocess.run(
        [
            "bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c",
            'IFS= read -r changed_path\nreview_repair_suite=false\nqueue_suite=false\n'
            'case "$changed_path" in\n' + selector
            + 'esac\nprintf "%s,%s" "$review_repair_suite" "$queue_suite"\n',
        ],
        input=changed_path + "\n",
        text=True,
        capture_output=True,
        check=True,
    )
    assert result.stdout == f"{str(review_repair).lower()},{str(queue).lower()}"
    assert result.stderr == ""


def test_commercial_readiness_suite_is_selected_and_conditionally_executed() -> None:
    """Preserve the retired caller's coverage contract in the shared job."""

    workflow = _workflow_text()

    assert "commercial_readiness_suite=false" in workflow
    assert "echo \"commercial_readiness=$commercial_readiness_suite\"" in workflow
    assert (
        "if: steps.affected_suites.outputs.commercial_readiness == 'true'"
        in workflow
    )
    assert "--include='scripts/ci/organization_commercial_readiness_loop.py'" in workflow
    assert "--fail-under=100" in workflow


def test_exact_artifact_suite_preserves_version_and_quality_contracts() -> None:
    """Compile on Python 3.10 before running full Python 3.14 evidence."""

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
    assert "exact_artifact_suite=false" in workflow
    assert "outputs.exact_artifact == 'true'" in workflow
    assert "--include=scripts/ci/verify_exact_artifact_sbom_handoff.py" in workflow
    assert "interrogate --fail-under=100" in workflow
