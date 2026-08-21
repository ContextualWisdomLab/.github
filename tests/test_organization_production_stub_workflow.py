from __future__ import annotations

from pathlib import Path

WORKFLOW_PATH = Path(".github/workflows/organization-production-stub-scan.yml")
CHANGELOG_PATH = Path("CHANGELOG.md")
DOCTORING_PATH = Path("docs/doctoring/production-stub-eradication-references.md")
PLAN_PATH = Path(
    "docs/superpowers/plans/2026-08-09-organization-production-stub-eradication.md"
)


def workflow_text() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def test_hourly_sharded_scan_uses_exact_repository_and_scanner_revisions() -> None:
    """Run work hourly while assigning repositories to stable bounded fleet shards."""
    text = workflow_text()

    assert 'cron: "17 * * * *"' in text
    assert "SHARD_COUNT: '12'" in text
    assert "MAX_REPOSITORIES_PER_RUN: '12'" in text
    assert 'if event_name == "schedule":' in text
    assert "hashlib.sha256(full_name.encode(\"utf-8\")).digest()" in text
    assert "repository_shard == scheduled_shard" in text
    assert "types: [organization-production-stub-scan]" in text
    assert "cancel-in-progress: false" in text
    assert "max-parallel: 4" in text
    assert "ref: ${{ matrix.repository_sha }}" in text
    assert "ref: ${{ github.sha }}" in text
    assert "--all-tracked" in text
    assert "--format json" in text
    assert "organization_production_stub_scan.py" in text
    assert "@main" not in text


def test_shard_receipt_uses_the_single_selection_calculation() -> None:
    """Bind the operator receipt to the shard and bounded window Python selected."""
    text = workflow_text()

    assert 'Path(os.environ["RUNNER_TEMP"], "selected-shard.txt")' in text
    assert 'else "all"' in text
    assert 'scheduled_shard="$(cat "${RUNNER_TEMP}/selected-shard.txt")"' in text
    assert "Selected bounded dispatch window at offset ${continuation_offset}" in text
    assert "epoch_hour=$(( $(date -u +%s) / 3600 ))" not in text
    assert "scheduled_shard=$(( epoch_hour % SHARD_COUNT ))" not in text


def test_manual_dispatch_uses_bounded_offsets_for_the_full_fleet_replay() -> None:
    """Continue a full-fleet replay across explicit finite repository-dispatch windows."""
    text = workflow_text()

    assert "EVENT_NAME: ${{ github.event_name }}" in text
    assert (
        "CONTINUATION_OFFSET: ${{ github.event.client_payload.continuation_offset || '0' }}"
        in text
    )
    assert 'selection_mode = "dispatch_continuation"' in text
    assert "continuation_offset : continuation_offset + max_repositories" in text
    assert "client_payload.continuation_offset=${next_continuation_offset}" in text
    assert "selected-repositories.json" in text
    assert "No eligible organization repository was selected" in text
    assert "scheduled shard is a successful no-op" in text


def test_operator_documentation_matches_the_hourly_sharded_contract() -> None:
    """Keep durable operator claims aligned with the executable cadence."""
    changelog = CHANGELOG_PATH.read_text(encoding="utf-8")
    doctoring = DOCTORING_PATH.read_text(encoding="utf-8")
    historical_plan = PLAN_PATH.read_text(encoding="utf-8")
    normalized_plan = " ".join(
        line.removeprefix("> ").strip() for line in historical_plan.splitlines()
    )

    assert "hourly exact-default-branch production-stub inventory" in changelog
    assert "stable twelfth" in changelog
    assert "one stable twelfth every hour" in doctoring
    assert "at most 12 repositories" in doctoring
    assert "deterministic continuation" in doctoring
    assert "full-fleet repository-dispatch" in doctoring
    assert "twice per day" not in doctoring
    for stale_claim in (
        "runs the fleet inventory once per day",
        "daily off-peak scanner",
        "Daily default-branch rescan",
        "no hourly fleet fan-out",
    ):
        assert stale_claim not in doctoring

    assert "Status: CURRENT (cadence reconciled, 2026-08-16)" in historical_plan
    assert "one stable SHA-256-assigned twelfth every hour" in normalized_plan
    assert "caps each invocation at 12 repositories" in normalized_plan
    assert "repository-dispatch remains the full-fleet replay path" in normalized_plan
    for stale_instruction in (
        'cron: "17 18 * * *"',
        'cron: "17 * * * *"\' not in workflow',
        "daily Korean off-peak fleet pass",
        "Schedule the daily fleet pass",
        "Daily Korean off-peak exact-SHA organization inventory",
        "old hourly fleet crons are absent",
    ):
        assert stale_instruction not in historical_plan


def test_private_target_checkout_uses_the_organization_token_without_persisting_it() -> None:
    """The repository-scoped GITHUB_TOKEN cannot clone another private repository."""
    text = workflow_text()
    target_checkout = text.split("- name: Checkout exact target repository", 1)[1].split(
        "- name: Checkout immutable central scanner source", 1
    )[0]

    assert "token: ${{ secrets.PR_REVIEW_MERGE_TOKEN }}" in target_checkout
    assert "persist-credentials: false" in target_checkout


def test_scan_is_read_only_except_for_bounded_remediation_issues() -> None:
    text = workflow_text()

    assert "permissions:\n  contents: read" in text
    assert "persist-credentials: false" in text
    assert "PR_REVIEW_MERGE_TOKEN" in text
    assert "COPILOT_GITHUB_TOKEN" not in text
    assert "NVIDIA_NIM_API_KEY" not in text
    assert "cwl-production-stub-inventory" in text
    assert "state_reason=completed" in text
    assert "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a" in text


def test_remediation_issue_lookup_does_not_pipe_paginated_output_to_head() -> None:
    """Avoid SIGPIPE failures and share one lookup across both mutation paths."""
    text = workflow_text()

    assert "- name: Find existing remediation issue" in text
    assert "id: remediation-issue" in text
    assert '>"${RUNNER_TEMP}/open-issues-pages.json"' in text
    assert "jq -sr --arg title \"$title\"" in text
    assert "steps.remediation-issue.outputs.issue_number" in text
    assert "| head -n 1" not in text


def test_issue_mutation_is_disabled_when_target_repository_has_issues_disabled() -> None:
    """Keep exact inventory failure evidence without assuming every repository has Issues."""
    text = workflow_text()

    assert "map({full_name, default_branch, has_issues})" in text
    assert "read -r full_name default_branch has_issues" in text
    assert "--argjson has_issues \"$has_issues\"" in text
    assert "has_issues: $has_issues" in text
    assert "if: steps.scan.outputs.scanner_exit_code != '0' && matrix.has_issues == true" in text
    assert "if: steps.scan.outputs.scanner_exit_code == '0' && matrix.has_issues == true" in text
    assert "Target repository has Issues disabled; remediation remains in the exact inventory artifact." in text


def test_finding_state_is_never_reclassified_as_a_successful_scan() -> None:
    """Fail closed even when a preceding scan step has no recorded output."""
    text = workflow_text()

    assert "scanner_exit_code" in text
    assert "Create or refresh remediation issue" in text
    assert "Close resolved remediation issue" in text
    assert "SCANNER_EXIT_CODE: ${{ steps.scan.outputs.scanner_exit_code }}" in text
    assert 'exit "${SCANNER_EXIT_CODE:-1}"' in text
    assert 'exit "${{ steps.scan.outputs.scanner_exit_code }}"' not in text
    assert "--repository \"$TARGET_REPOSITORY\"" in text
    assert "--repository-sha \"$TARGET_SHA\"" in text
    assert "--workflow-sha \"$WORKFLOW_SHA\"" in text
    assert "inventory_payload_is_binding" in text
    assert "inventory_payload_is_clean" in text
    assert "inventory_payload_matches_identity" in text
    assert '--input "${RUNNER_TEMP}/issue-payload.json"' in text
    assert 'body="$(cat "${RUNNER_TEMP}/issue-body.md")"' not in text
    assert '-f body="$body"' not in text


def test_shard_execution_budget_is_observable_and_preventive() -> None:
    """Record the enforced matrix cap before separately warning on elapsed runtime."""
    text = workflow_text()

    assert "selected_repository_count: ${{ steps.inventory.outputs.selected_repository_count }}" in text
    assert "deferred_repository_count: ${{ steps.inventory.outputs.deferred_repository_count }}" in text
    assert "max_repositories_per_run: ${{ steps.inventory.outputs.max_repositories_per_run }}" in text
    assert "SHARD_EXECUTION_BUDGET_SECONDS: '3600'" in text
    assert "needs: [discover-repositories, scan-repository]" in text
    assert "SELECTED_REPOSITORY_COUNT: ${{ needs.discover-repositories.outputs.selected_repository_count }}" in text
    assert "DEFERRED_REPOSITORY_COUNT: ${{ needs.discover-repositories.outputs.deferred_repository_count }}" in text
    assert "MAX_REPOSITORIES_PER_RUN: ${{ needs.discover-repositories.outputs.max_repositories_per_run }}" in text
    assert "violated the enforced run budget" in text
    assert "completed as a successful no-op" in text
    assert "Selection budget receipt:" in text
    assert "repos/${GITHUB_REPOSITORY}/actions/runs/${GITHUB_RUN_ID}" in text
    assert "Shard execution receipt:" in text
    assert "::warning::Shard execution exceeded" in text
