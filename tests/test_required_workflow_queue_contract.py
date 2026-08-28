"""Verify central required-workflow queue, security, and dispatch contracts."""

import json
import os
import shlex
import shutil
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


def workflow_text(name: str) -> str:
    """Read one central workflow for contract assertions."""
    return (REPO_ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")


def workflow_step(workflow: str, name: str) -> str:
    """Extract one named workflow step without parsing YAML dynamically."""
    step = f"      - name: {name}\n"
    start = workflow.index(step)
    try:
        end = workflow.index("\n      - name:", start + len(step))
    except ValueError:
        end = len(workflow)
    return workflow[start:end]


def osv_result_classifier_script(workflow: str) -> str:
    step = workflow_step(workflow, "Install trusted OSV result evidence classifier")
    marker = "          cat >\"$RUNNER_TEMP/classify-osv-result.py\" <<'PY'\n"
    start = step.index(marker) + len(marker)
    end = step.index("\n          PY", start)
    return textwrap.dedent(step[start:end])


def test_merge_scheduler_dispatches_one_review_by_default() -> None:
    """Keep the default scheduler dispatch bounded to one review."""
    workflow = workflow_text("pr-review-merge-scheduler.yml")

    assert workflow.count('default: "1"') >= 2
    assert "vars.REVIEW_DISPATCH_LIMIT || '1'" in workflow
    assert "SCHEDULER_ALLOW_CROSS_REPO_REPOSITORY_DISPATCH" in workflow
    assert (
        "secrets.PR_REVIEW_MERGE_TOKEN != '' || secrets.OPENCODE_APPROVE_TOKEN != ''"
        in workflow
    )


def test_organization_readiness_does_not_echo_untrusted_http_method(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep arbitrary HTTP method text out of organization-loop diagnostics."""
    from types import SimpleNamespace

    from scripts.ci.organization_commercial_readiness_loop import (
        GitHubClient,
        GitHubError,
    )

    token = "ghp_abcdefghijklmnopqrstuvwxyz0123456789AB"
    monkeypatch.setattr(
        "subprocess.run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="request rejected",
        ),
    )

    with pytest.raises(GitHubError) as raised:
        GitHubClient("client-token").request("/repos/example", method=token)

    message = str(raised.value)
    assert token.upper() not in message
    assert "[REDACTED_METHOD]" in message


def test_merge_scheduler_rejects_untrusted_stale_timeout_values() -> None:
    """Dispatch payloads must not smuggle shell syntax into scheduler arguments."""
    workflow = workflow_text("pr-review-merge-scheduler.yml")

    assert workflow.count("STALE_OPENCODE_MINUTES must contain only decimal digits") == 2
    assert workflow.count("STALE_OPENCODE_MINUTES must be between 1 and 1440") == 4
    assert workflow.count("stale_opencode_minutes=$((10#$STALE_OPENCODE_MINUTES))") == 2
    assert workflow.count('STALE_OPENCODE_MINUTES="$stale_opencode_minutes"') == 2


def test_merge_scheduler_deduplicates_unscoped_repository_dispatches() -> None:
    """Use stable repository-scoped concurrency keys for unscoped events."""
    workflow = workflow_text("pr-review-merge-scheduler.yml")
    concurrency_contract = workflow.split("concurrency:", 1)[1].split(
        "permissions:", 1
    )[0]

    assert "format('org-sweep-{0}', github.repository)" in concurrency_contract
    assert "format('repo-dispatch-{0}', github.repository)" in concurrency_contract
    assert "format('workflow-run-no-pr-{0}', github.repository)" in concurrency_contract
    assert (
        "github.event_name == 'workflow_run' && !github.event.workflow_run.pull_requests[0].number"
        in concurrency_contract
    )
    assert "github.event_name == 'repository_dispatch' && github.run_id" not in (
        concurrency_contract
    )
    assert "cancel-in-progress: ${{" in concurrency_contract
    assert "github.event_name == 'repository_dispatch'" in concurrency_contract


def test_merge_scheduler_provides_same_repository_dispatch_credential() -> None:
    """Guard the runner-token dispatch credential for central review workflows.

    The OpenCode app installation has no Actions permission and no
    PR_REVIEW_MERGE_TOKEN / OPENCODE_APPROVE_TOKEN PAT is configured, so before
    this credential existed the org sweep deadlocked every PR needing current-head
    review evidence with "no cross-repository repository-dispatch credential". The
    scheduler and the sweep both run inside ContextualWisdomLab/.github — the same
    repository the required workflows are dispatched on — so the runner's own
    github.token (actions: write) must be passed through SCHEDULER_DISPATCH_TOKEN
    in BOTH jobs; the scheduler only uses it when GITHUB_REPOSITORY equals the
    dispatch repository.
    """
    workflow = workflow_text("pr-review-merge-scheduler.yml")

    assert workflow.count("SCHEDULER_DISPATCH_TOKEN: ${{ github.token }}") == 2


def test_targeted_scheduler_dispatch_is_allowlisted_and_exact_pr_scoped() -> None:
    """Central single-PR dispatch accepts a bounded fork head without trusting it."""
    workflow = workflow_text("pr-review-merge-scheduler.yml")
    validation = workflow_step(workflow, "Validate targeted repository dispatch")
    inspect = workflow_step(workflow, "Inspect PR review and merge queue")

    assert "TARGET_REPOSITORY_INPUT:" in validation
    assert "TARGET_PR_NUMBER:" in validation
    assert "TARGET_BASE_BRANCH_INPUT:" in validation
    assert (
        "ALLOWED_TARGET_REPOSITORIES: ${{ "
        "vars.OPENCODE_REPOSITORY_DISPATCH_TARGETS }}"
    ) in validation
    assert 'GITHUB_REPOSITORY" != "ContextualWisdomLab/.github"' in validation
    assert "target_allowed=0" in validation
    assert '"repos/${TARGET_REPOSITORY_INPUT}/pulls/${TARGET_PR_NUMBER}"' in validation
    assert '[ "$live_state" != "open" ]' in validation
    assert '[ "$live_base_repository" != "$TARGET_REPOSITORY_INPUT" ]' in validation
    assert (
        '! [[ "$live_head_repository" =~ '
        '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]]'
    ) in validation
    assert '[ "$live_head_repository" != "$TARGET_REPOSITORY_INPUT" ]' not in validation
    assert "Targeted scheduler dispatch base branch does not match the live PR" in validation
    assert "TARGET_REPOSITORY: ${{ steps.targeted_dispatch.outputs.repository }}" in inspect
    assert (
        "TARGET_DEFAULT_BRANCH: ${{ steps.targeted_dispatch.outputs.base_branch }}"
        in inspect
    )
    assert '--repo "$TARGET_REPOSITORY"' in inspect
    assert '--base-branch "$TARGET_DEFAULT_BRANCH"' in inspect
    assert 'args+=(--pr-number "$PULL_REQUEST_NUMBER")' in inspect
    assert (
        "github.event_name == 'repository_dispatch' && "
        "github.event.client_payload.target_repository != '' && "
        "github.event.client_payload.target_repository != github.repository && "
        "(secrets.PR_REVIEW_MERGE_TOKEN || secrets.OPENCODE_APPROVE_TOKEN || "
        "steps.scheduler_app_token.outputs.token) || github.token"
    ) in inspect
    assert (
        "format('target-{0}-pr-{1}', "
        "github.event.client_payload.target_repository, "
        "github.event.client_payload.pr_number)"
    ) in workflow


def test_privileged_review_retries_use_default_branch_repository_dispatch() -> None:
    """Privileged retries must never load workflow code from a selected ref."""
    expected_types = {
        "opencode-review-dispatch.yml": "opencode-review",
        "noema-review.yml": "noema-review",
        "strix.yml": "strix-scan",
        "pr-review-merge-scheduler.yml": "merge-scheduler",
    }
    for filename, event_type in expected_types.items():
        workflow = workflow_text(filename)
        trigger_contract = workflow.split("concurrency:", 1)[0]

        assert "repository_dispatch:" in trigger_contract
        assert f"types: [{event_type}]" in trigger_contract
        assert "workflow_dispatch:" not in trigger_contract
        assert "github.event.inputs" not in workflow
        assert "github.event.client_payload" in workflow

    scheduler = (
        REPO_ROOT / "scripts" / "ci" / "pr_review_merge_scheduler.py"
    ).read_text(encoding="utf-8")
    assert 'f"repos/{dispatch_repo}/dispatches"' in scheduler
    assert '"event_type": "opencode-review"' in scheduler
    assert '"event_type": "strix-scan"' in scheduler

    autofix_workflow = workflow_text("pr-review-autofix.yml")
    assert "repository_dispatch:" in autofix_workflow
    assert "types: [pr-review-autofix]" in autofix_workflow
    assert "workflow_dispatch:" not in autofix_workflow
    assert "github.event.client_payload" in autofix_workflow
    autofix_scheduler = (
        REPO_ROOT / "scripts" / "ci" / "pr_review_fix_scheduler.py"
    ).read_text(encoding="utf-8")
    assert 'f"repos/{dispatch_repo}/dispatches"' in autofix_scheduler
    assert 'AUTOFIX_REPOSITORY_DISPATCH_TYPE = "pr-review-autofix"' in autofix_scheduler
    assert '"gh",\n        "workflow",\n        "run"' not in autofix_scheduler


def test_no_central_workflow_exposes_branch_selected_manual_dispatch() -> None:
    """Every central manual entrypoint must load code from the default branch."""
    workflow_files = sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml"))
    offenders = [
        path.name
        for path in workflow_files
        if "workflow_dispatch:" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_required_pull_request_workflows_cancel_superseded_runs() -> None:
    """Ensure required pull-request workflows cancel obsolete executions."""
    for filename in (
        "close-empty-pr.yml",
        "codeql-pr.yml",
        "noema-review.yml",
        "opencode-review.yml",
        "osv-scanner-pr.yml",
        "security-scan.yml",
        "scorecard-pr.yml",
    ):
        workflow = workflow_text(filename)
        concurrency_contract = workflow.split("concurrency:", 1)[1].split(
            "permissions:", 1
        )[0]

        assert "concurrency:" in workflow
        assert "github.event.pull_request.base.repo.full_name" in concurrency_contract
        assert "github.repository" in concurrency_contract
        assert "github.event.pull_request.number" in workflow
        assert "cancel-in-progress: true" in workflow
        if filename in {
            "close-empty-pr.yml",
            "security-scan.yml",
        }:
            assert (
                "github.event_name == 'pull_request_target'" in concurrency_contract
                or ("github.event_name == 'pull_request'" in concurrency_contract)
            )
        elif filename == "opencode-review.yml":
            assert "opencode-review-bootstrap-" in concurrency_contract
        else:
            if filename in {"codeql-pr.yml", "osv-scanner-pr.yml", "scorecard-pr.yml"}:
                assert "github.event_name == 'pull_request'" in concurrency_contract
            else:
                assert (
                    "github.event_name == 'pull_request_target'" in concurrency_contract
                )
        assert "github.event.pull_request.head.sha" not in concurrency_contract
        assert "format('pr-{0}-{1}'" not in concurrency_contract


def test_central_semgrep_logs_every_finding_and_distinguishes_engine_failure() -> None:
    """Keep Semgrep finding output distinct from scanner-engine failures."""
    workflow = workflow_text("sast-semgrep.yml")

    assert "Report every Semgrep finding in the job log" in workflow
    assert "--exclude='docs/research/**/standards'" in workflow
    assert "SEMGREP_FINDING_COUNT=" in workflow
    assert "SEMGREP_FINDING rule=" in workflow
    assert 'level=\\(.level // $levels[.ruleId] // "unknown")' in workflow
    assert 'path=\\($location.artifactLocation.uri // "unknown")' in workflow
    assert "line=\\($location.region.startLine // 0)" in workflow
    assert "message=" in workflow
    assert "SEMGREP_ENGINE_FAILURE rc=" in workflow
    assert "semgrep_sarif.outputs.finding_count != '0'" in workflow
    assert 'if [ "${SEMGREP_FINDING_COUNT:-missing}" != "0" ]' in workflow
    assert "Every rule, path, line, and message is listed" in workflow
    assert "Semgrep engine/configuration failed with rc=${SEMGREP_RC}" in workflow


def test_central_semgrep_binds_pr_scans_and_sarif_to_the_exact_head() -> None:
    """Reject GitHub's synthetic merge as SAST source or SARIF identity."""
    workflow = workflow_text("sast-semgrep.yml")
    checkout = workflow_step(workflow, "Checkout exact submitted revision")
    verify = workflow_step(workflow, "Verify exact submitted revision")
    upload = workflow_step(workflow, "Upload Semgrep SARIF to code scanning")

    assert (
        "repository: ${{ github.event.pull_request.head.repo.full_name || github.repository }}"
        in checkout
    )
    assert (
        "ref: ${{ github.event.pull_request.head.sha || github.sha }}" in checkout
    )
    assert "persist-credentials: false" in checkout
    assert (
        "EXPECTED_CHECKOUT_SHA: ${{ github.event.pull_request.head.sha || github.sha }}"
        in verify
    )
    assert 'actual_sha="$(git rev-parse HEAD)"' in verify
    assert 'if [ "$actual_sha" != "$EXPECTED_CHECKOUT_SHA" ]; then' in verify
    assert "exit 1" in verify
    assert (
        "ref: ${{ github.event_name == 'pull_request' && format('refs/pull/{0}/head', github.event.pull_request.number) || github.ref }}"
        in upload
    )
    assert (
        "sha: ${{ github.event.pull_request.head.sha || github.sha }}" in upload
    )


def test_strix_serializes_provider_evidence_per_repository() -> None:
    """Serialize Strix per repository so shared provider keys are not rate-limited.

    Root cause (2026-08-23/24): sibling PRs scanned concurrently, each retrying
    the shared NVIDIA NIM key three times, producing litellm.RateLimitError
    storms and fail-closed gate failures on every open PR. The concurrency group
    now scopes one scan at a time per repository and event class. GitHub retains
    one active and one pending run per group; the scheduler re-dispatches exact
    current-head evidence when a pending run is superseded.
    """
    workflow = workflow_text("strix.yml")
    concurrency_contract = workflow.split("concurrency:", 1)[1].split(
        "permissions:", 1
    )[0]

    assert "concurrency:" in workflow
    assert "github.event.client_payload.target_repository" in concurrency_contract
    assert "github.event.pull_request.base.repo.full_name" in concurrency_contract
    assert "github.repository" in concurrency_contract
    assert (
        "format('closed-pr-{0}-{1}', github.event.pull_request.base.repo.full_name, "
        "github.event.pull_request.number)"
    ) in concurrency_contract
    assert (
        "format('{0}-{1}', github.event_name, github.event.client_payload.target_repository || "
        "github.event.pull_request.base.repo.full_name || github.repository)"
    ) in concurrency_contract
    assert (
        "format('{0}-{1}-{2}', github.event_name, github.repository, github.ref)"
        in concurrency_contract
    )
    # Repository-level (not PR-level) grouping: no pr-{N} component remains.
    assert "format('pr-{0}', github.event.pull_request.number)" not in concurrency_contract
    assert "github.event.pull_request.head.sha" not in concurrency_contract
    assert "github.event.client_payload.pr_head_sha" not in concurrency_contract
    # Running scans are not cancelled; GitHub's native group has one pending slot.
    assert "cancel-in-progress: false" in workflow
    assert "cancel-in-progress: true" not in workflow.split("jobs:", 1)[0]
    assert "queue: max" not in workflow
    assert "scheduler" in concurrency_contract
    assert "default-branch repository_dispatch evidence cannot cancel" in workflow
    assert "RateLimitError" in concurrency_contract
    assert (
        "refs/pull/<n>/head has already advanced before this queued run starts"
        in workflow
    )


def test_strix_install_normalizes_executable_permissions_before_hashing() -> None:
    """Normalize the Strix executable before its trusted hash is computed."""
    workflow = workflow_text("strix.yml")
    install_step = workflow_step(workflow, "Install Strix")

    assert install_step.index("umask 022") < install_step.index(
        "python3 -m pip install"
    )
    permission_normalization = 'chmod go-w -- "$strix_scripts_root" "$strix_executable"'
    assert install_step.index('strix_scripts_root="') < install_step.index(
        permission_normalization
    )
    assert install_step.index(permission_normalization) < install_step.index(
        'strix_executable_sha256="'
    )


def test_pull_request_close_events_cancel_superseded_runs_without_heavy_jobs() -> None:
    """Close events should cancel old runs without starting expensive jobs."""
    workflows = (
        "close-empty-pr.yml",
        "codeql-pr.yml",
        "noema-review.yml",
        "osv-scanner-pr.yml",
        "pr-review-merge-scheduler.yml",
        "scorecard-pr.yml",
        "security-scan.yml",
        "strix.yml",
    )

    for filename in workflows:
        workflow = workflow_text(filename)

        assert "closed" in workflow
        assert "cancel-closed-pr-runs:" in workflow
        if filename == "strix.yml":
            assert "Cancel queued and running scans for the closed pull request" in workflow
            assert (
                "secrets.PR_REVIEW_MERGE_TOKEN || secrets.OPENCODE_APPROVE_TOKEN "
                "|| github.token"
            ) in workflow
            assert "DISPATCH_REPOSITORY" not in workflow
            assert "CLOSED_PR_HEAD_SHA" in workflow
            assert 'select(.event == "pull_request_target")' in workflow
            assert 'select(.event == "repository_dispatch")' not in workflow
            assert "leaving runs unchanged" in workflow
            assert (
                "for active_status in queued in_progress requested waiting pending"
                in workflow
            )
            cleanup_job = workflow.split("  cancel-closed-pr-runs:", 1)[1].split(
                "  strix:", 1
            )[0]
            assert "actions: write" in cleanup_job
            assert "actions/checkout" not in cleanup_job
            assert "cleanup skipped" not in cleanup_job
        else:
            assert (
                "PR closed; this run only cancels older runs through workflow concurrency."
                in workflow
            )
        assert "github.event.action != 'closed'" in workflow

    opencode_bootstrap = workflow_text("opencode-review.yml")
    assert "types: [opened, synchronize, reopened, ready_for_review, closed]" in (
        opencode_bootstrap
    )
    assert "actions/checkout" not in opencode_bootstrap
    assert "${{ secrets." not in opencode_bootstrap

    strix_workflow = workflow_text("strix.yml")
    # Strix serializes per repository (rate-limit root-cause fix): close-event
    # runs still cancel superseded same-PR evidence through their own
    # cancel-closed-pr-runs job, while scan jobs queue instead of cancelling.
    assert "cancel-in-progress: false" in strix_workflow
    assert "Serialize Strix scans per repository" in strix_workflow or "per REPOSITORY" in strix_workflow


def test_close_empty_pr_metadata_lookup_retries_and_fails_open() -> None:
    """Retry invalid close-event metadata and leave the PR open on uncertainty."""
    workflow = workflow_text("close-empty-pr.yml")

    assert "gh_api_json_with_retry()" in workflow
    assert "jq -e type" in workflow
    assert "did not return valid JSON; retrying" in workflow
    assert "did not return valid JSON after 4 attempts" in workflow
    assert "leaving it open because metadata could not be read" in workflow
    assert "exit 0" in workflow


def test_cancelled_review_workflow_runs_do_not_spawn_more_queue_work() -> None:
    """Prevent cancelled review runs from creating follow-up queue work."""
    for filename in ("noema-review.yml", "pr-review-merge-scheduler.yml"):
        workflow = workflow_text(filename)

        assert "github.event.workflow_run.conclusion != 'cancelled'" in workflow


def test_required_workflow_trusted_source_refs_are_not_input_controlled() -> None:
    """Ensure privileged workflows resolve trusted source code independently of inputs."""
    for filename in (
        "opencode-review-dispatch.yml",
        "noema-review.yml",
        "pr-review-merge-scheduler.yml",
    ):
        workflow = workflow_text(filename)

        assert "canonical_ref:" not in workflow
        assert "INPUT_CANONICAL_REF" not in workflow
        assert "github.event.client_payload.canonical_ref" not in workflow
        assert "inputs.canonical_ref" not in workflow
        assert "workflow_sha" in workflow
        if filename == "opencode-review-dispatch.yml":
            assert "ref: ${{ steps.trusted_source.outputs.ref }}" in workflow
            assert "ref: ${{ github.workflow_sha }}" not in workflow
        else:
            assert (
                "ref: ${{ github.workflow_sha }}" in workflow
                or "TRUSTED_SOURCE_REF: ${{ steps.trusted_source.outputs.ref }}"
                in workflow
            )
        assert "JOB_CONTEXT_JSON: ${{ toJSON(job) }}" in workflow
        assert "GITHUB_CONTEXT_JSON: ${{ toJSON(github) }}" in workflow


def test_noema_workflow_run_followup_cannot_cancel_required_pr_event_review() -> None:
    """Keep Noema workflow-run follow-ups isolated from PR-event reviews."""
    workflow = workflow_text("noema-review.yml")
    concurrency_contract = workflow.split("permissions:", 1)[0]

    assert "github.repository }}-${{ github.event_name }}-${{" in concurrency_contract
    assert "github.event_name == 'workflow_run'" in concurrency_contract
    assert "github.event_name == 'pull_request_target'" in concurrency_contract


def test_noema_review_credentials_and_orchestrator_configuration_fail_closed() -> None:
    """Require explicit reviewer credentials and the trusted orchestrator sidecar."""
    workflow = workflow_text("noema-review.yml")

    assert "fail_unavailable()" in workflow
    assert 'echo "::error::$message"' in workflow
    assert "vars.NOEMA_TOKEN_EXCHANGE_URL || vars.NOEMA_EXCHANGE_URL || ''" in workflow
    assert (
        "Noema reviewer credential is unconfigured: set NOEMA_GITHUB_APP_CLIENT_ID with "
        "NOEMA_GITHUB_APP_PRIVATE_KEY, NOEMA_REVIEW_TOKEN, or NOEMA_TOKEN_EXCHANGE_URL. "
        "Review cannot be skipped."
    ) in workflow
    assert (
        "Noema app token exchange unavailable: OIDC request environment is missing."
        in workflow
    )
    assert (
        "Noema app token exchange unavailable: OIDC token request did not complete."
        in workflow
    )
    assert (
        "Noema app token exchange unavailable: OIDC token response was empty."
        in workflow
    )
    assert (
        "Noema app token exchange unavailable: app token request did not complete."
        in workflow
    )
    assert (
        "Noema app token exchange unavailable: app token response was empty."
        in workflow
    )
    assert (
        "Noema reviewer credential selection succeeded but no token was minted"
        in workflow
    )
    assert "Resolve Noema target repository visibility" in workflow
    assert "target_visibility.outputs.require_zdr" in workflow
    assert "CONTEXTUAL_ORCHESTRATOR_REQUIRE_ZDR" in workflow
    assert "https://integrate.api.nvidia.com/v1/chat/completions" not in workflow
    assert "nvidia/nemotron-3-ultra-550b-a55b" not in workflow
    assert "contextual_orchestrator_review_sidecar.sh" in workflow
    assert 'export NOEMA_LLM_MODEL="orchestrator/free"' in workflow
    assert (
        "contextual-orchestrator review sidecar must be provisioned before Noema LLM review."
        in workflow
    )
    assert "BYTEZ_API_KEY: ${{ secrets.BYTEZ_API_KEY }}" in workflow
    assert "NVIDIA_NIM_API_KEY: ${{ secrets.NVIDIA_NIM_API_KEY }}" in workflow
    assert "NVIDIA_NIM_API_KEY_SUB: ${{ secrets.NVIDIA_NIM_API_KEY_SUB }}" in workflow
    assert "OPENROUTER_API_KEY: ${{ secrets.OPENROUTER_API_KEY }}" in workflow
    assert "OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}" in workflow
    assert "COPILOT_GITHUB_TOKEN" not in workflow
    assert "secrets: inherit" not in workflow
    assert "mark_unconfigured()" not in workflow
    assert "review skipped until Noema is deployed" not in workflow
    assert "Noema app token is unavailable; review skipped." not in workflow


def test_strix_gateway_default_and_noema_sidecar_fail_closed(
    tmp_path: Path,
) -> None:
    """Keep Strix on the gateway and fail Noema closed without its sidecar."""
    bash_executable = shutil.which("bash") or "/bin/bash"
    strix_output = tmp_path / "strix-output"
    strix = subprocess.run(  # noqa: S603, S607
        [
            bash_executable,
            "-c",
            textwrap.dedent(
                workflow_step(
                    workflow_text("strix.yml"),
                    "Gate Strix secrets",
                )
                .split("        run: |\n", 1)[1]
            ),
        ],
        env={
            **os.environ,
            "GITHUB_OUTPUT": str(strix_output),
            "STRIX_MODEL": "contextual-orchestrator/orchestrator/free",
            "STRIX_MODEL_REQUESTED": "",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert strix.returncode == 0, strix.stderr
    assert {
        "strix_model=contextual-orchestrator/orchestrator/free",
        "enabled=true",
        "provider_mode=contextual_orchestrator",
    } <= set(strix_output.read_text().splitlines())
    assert (
        "STRIX_MODEL: contextual-orchestrator/orchestrator/free"
        in workflow_text("strix.yml")
    )
    assert (
        "STRIX_MODEL: ${{ steps.gate.outputs.strix_model }}"
        in workflow_text("strix.yml")
    )

    noema_script = textwrap.dedent(
        workflow_step(
            workflow_text("noema-review.yml"),
            "Run Noema LLM review and submit verdict",
        ).split("        run: |\n", 1)[1]
    )
    noema_env = {
        **os.environ,
        "PR_NUMBER": "1",
        "GH_TOKEN": "synthetic-review-token",
    }
    for key in (
        "CONTEXTUAL_ORCHESTRATOR_BASE_URL",
        "CONTEXTUAL_ORCHESTRATOR_TOKEN",
        "NOEMA_LLM_VIA_ORCHESTRATOR",
        "NOEMA_LLM_API_KEY",
    ):
        noema_env.pop(key, None)
    noema = subprocess.run(  # noqa: S603, S607
        [
            bash_executable,
            "-c",
            noema_script,
        ],
        env=noema_env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert noema.returncode == 1
    assert "sidecar must be provisioned before Noema LLM review" in noema.stdout


def test_noema_workflow_run_without_pull_request_skips_before_token_exchange() -> None:
    """Skip unassociated workflow runs before requesting review credentials."""
    workflow = workflow_text("noema-review.yml")

    assert (
        "Noema review skipped: no pull request number is associated with this event."
        in workflow
    )
    assert "if: env.PR_NUMBER == ''" in workflow
    assert workflow.count("if: env.PR_NUMBER != ''") >= 4


def test_noema_review_supports_review_token_pat_fallback() -> None:
    """Guard the NOEMA_REVIEW_TOKEN PAT fallback that activates the second reviewer.

    The two-reviewer merge rule needs a second approving-review identity. Rather
    than forcing a Worker deployment, a NOEMA_REVIEW_TOKEN secret must be usable
    directly as the reviewer identity: when it is present the OIDC app-token
    exchange is skipped, and the review step must prefer it. The secret value is
    never emitted as a step output.
    """
    workflow = workflow_text("noema-review.yml")

    assert "NOEMA_REVIEW_TOKEN: ${{ secrets.NOEMA_REVIEW_TOKEN }}" in workflow
    assert 'if [ -n "${NOEMA_REVIEW_TOKEN:-}" ]; then' in workflow
    assert (
        "Noema reviewer using the NOEMA_REVIEW_TOKEN secret fallback identity."
        in workflow
    )
    # The review step must prefer the PAT over the exchanged app token.
    assert (
        "GH_TOKEN: ${{ secrets.NOEMA_REVIEW_TOKEN || steps.noema_github_app_token.outputs.token || steps.noema_oidc_token.outputs.token }}"
        in workflow
    )
    assert "steps.noema_credential.outputs.source == 'github-app'" in workflow


def test_noema_review_mints_a_least_privilege_github_app_token() -> None:
    """Guard the independent App identity and its repository-scoped permissions."""
    workflow = workflow_text("noema-review.yml")

    assert (
        "uses: actions/create-github-app-token@bcd2ba49218906704ab6c1aa796996da409d3eb1 # v3.2.0"
        in workflow
    )
    assert "client-id: ${{ vars.NOEMA_GITHUB_APP_CLIENT_ID }}" in workflow
    assert "private-key: ${{ secrets.NOEMA_GITHUB_APP_PRIVATE_KEY }}" in workflow
    assert "owner: ContextualWisdomLab" in workflow
    assert "repositories: ${{ steps.noema_credential.outputs.repository }}" in workflow
    for permission in (
        "permission-actions: read",
        "permission-checks: read",
        "permission-contents: read",
        "permission-metadata: read",
        "permission-pull-requests: write",
        "permission-security-events: read",
        "permission-statuses: read",
        "permission-vulnerability-alerts: read",
    ):
        assert permission in workflow


def test_opencode_dispatch_hands_approved_head_to_noema_before_merge() -> None:
    """The two-reviewer chain must run Noema before the direct merge follow-up."""
    workflow = workflow_text("opencode-review-dispatch.yml")
    handoff = workflow_step(
        workflow, "Dispatch Noema after current-head OpenCode approval"
    )

    assert workflow.index(
        "      - name: Dispatch Noema after current-head OpenCode approval"
    ) < workflow.index("      - name: Run merge scheduler after approval")
    assert "always()" in handoff
    assert "github.event_name == 'repository_dispatch'" in handoff
    assert (
        "needs.validate-pr-metadata.outputs.target_repository != github.repository"
        not in handoff
    )
    assert "continue-on-error: true" in handoff
    assert "timeout-minutes: 18" in handoff
    assert (
        "GH_TOKEN: ${{ secrets.PR_REVIEW_MERGE_TOKEN || "
        "secrets.OPENCODE_APPROVE_TOKEN || "
        "steps.opencode_app_token.outputs.token || github.token }}"
    ) in handoff
    assert "python3 scripts/ci/noema_review_handoff.py" in handoff
    assert '--repo "$GH_REPOSITORY"' in handoff
    assert '--pr-number "$PR_NUMBER"' in handoff
    assert '--head-sha "$PR_HEAD_SHA"' in handoff
    assert "--attempts 90" in handoff
    assert "--interval-seconds 10" in handoff
    for sealed_env in (
        "OPENCODE_CHANGED_FILES_FILE: ${{ runner.temp }}/opencode-changed-files.txt",
        "OPENCODE_ARTIFACT_MANIFEST_SHA256: ${{ "
        "steps.seal_artifacts.outputs.manifest_sha256 }}",
        "OPENCODE_SOURCE_WORKDIR: ${{ runner.temp }}/opencode-pr-head",
        'OPENCODE_REQUIRE_ADVERSARIAL_VALIDATION: "true"',
    ):
        assert sealed_env in handoff

    merge_follow_up = workflow_step(workflow, "Run merge scheduler after approval")
    for sealed_env in (
        "OPENCODE_CHANGED_FILES_FILE: ${{ runner.temp }}/opencode-changed-files.txt",
        "OPENCODE_ARTIFACT_MANIFEST_SHA256: ${{ "
        "steps.seal_artifacts.outputs.manifest_sha256 }}",
        "OPENCODE_SOURCE_WORKDIR: ${{ runner.temp }}/opencode-pr-head",
        'OPENCODE_REQUIRE_ADVERSARIAL_VALIDATION: "true"',
    ):
        assert sealed_env in merge_follow_up


def test_noema_and_scheduler_trusted_checkouts_use_static_main() -> None:
    """Keep Noema and scheduler trusted checkouts pinned to central immutable sources."""
    noema = workflow_text("noema-review.yml")
    scheduler = workflow_text("pr-review-merge-scheduler.yml")

    for workflow in (noema, scheduler):
        assert "workflow_sha" in workflow
        assert "workflow_repository" in workflow
        assert "Trusted" in workflow or "trusted" in workflow
        assert "Materialize trusted" in workflow
        assert "uses: actions/checkout" not in workflow
        assert (
            "repos/ContextualWisdomLab/.github/tarball/${TRUSTED_SOURCE_REF}"
            in workflow
        )
        assert (
            "Trusted" in workflow
            and "source ref must resolve to the immutable workflow commit SHA"
            in workflow
        )
        assert "repository: ContextualWisdomLab/.github" not in workflow
        assert (
            "repository: ${{ steps.trusted_source.outputs.repository }}" not in workflow
        )
        assert "TRUSTED_SOURCE_REF: ${{ steps.trusted_source.outputs.ref }}" in workflow
        assert "INPUT_CANONICAL_REF" not in workflow


def test_unassociated_review_workflow_runs_do_not_scan_the_whole_pr_queue() -> None:
    """Avoid scanning every PR when a workflow run has no associated pull request."""
    workflow = workflow_text("pr-review-merge-scheduler.yml")

    assert "github.event.workflow_run.pull_requests[0].number" in workflow


def test_org_queue_sweep_covers_target_repositories_on_a_heartbeat() -> None:
    """Guard the org-wide approved-PR fallback sweep contract.

    Target repositories only receive scheduler runs on PR events, so a PR that
    becomes mergeable after its last event sits approved-but-unmerged forever.
    The sweep job must exist, run only from the central repository on its own
    cron, use a cross-repository mutation credential (never the repository
    github.token silently), skip the central repository itself, and fail with a
    visible reason when it cannot mutate sibling repositories. The sweep runs
    every 15 minutes so an approval that lands after a PR's last event is
    auto-updated/merged promptly instead of idling indefinitely. Its cron has a
    distinct concurrency key from the separate 30-minute scan, and the job has
    enough runtime headroom to finish a complete organization walk.
    """
    workflow = workflow_text("pr-review-merge-scheduler.yml")

    assert "org-queue-sweep:" in workflow
    assert '- cron: "*/15 * * * *"' in workflow
    assert "github.repository == 'ContextualWisdomLab/.github'" in workflow
    assert "github.event.schedule == '*/15 * * * *'" in workflow
    assert "github.event.client_payload.org_sweep == true" in workflow
    assert (
        "github.event_name == 'schedule' && format('schedule-{0}', "
        "github.event.schedule)"
    ) in workflow
    org_sweep_header = workflow.split("  org-queue-sweep:", 1)[1].split(
        "    permissions:", 1
    )[0]
    assert "timeout-minutes: 60" in org_sweep_header
    for setting in (
        "ORG_SWEEP_TRIGGER_REVIEWS",
        "ORG_SWEEP_ENABLE_AUTO_MERGE",
        "ORG_SWEEP_UPDATE_BRANCHES",
    ):
        assert f"{setting}: ${{{{ github.event_name == 'schedule' ||" in workflow
    # The single-repository scan must not double-run on the sweep cron.
    assert "github.event.schedule != '*/15 * * * *'" in workflow
    assert "github.event.client_payload.org_sweep != true" in workflow
    # The sweep must never silently no-op with the repository-scoped token.
    assert (
        "Organization queue sweep has no cross-repository mutation credential."
        in workflow
    )
    assert 'select(.full_name != "ContextualWisdomLab/.github")' in workflow
    assert "select(.archived == false and .disabled == false)" in workflow
    # The sweep must not silently truncate large/old queues or skip a repository
    # whose only open work is a stacked/non-default-base PR.
    assert "vars.ORG_SWEEP_MAX_PRS || '1000'" in workflow
    assert "/pulls?state=open&per_page=1&base=" not in workflow
    assert "No open PRs (including stacked or non-default-base PRs)" in workflow
    # Every repository failure must leave a concrete logged reason.
    assert "see the decision log above for the concrete per-PR reason" in workflow
    # Queue hygiene: previous-head runs are cancelled immediately, while the
    # legacy age guard cannot cancel a valid current-head PR run.
    assert "ORG_SWEEP_STALE_QUEUE_HOURS" in workflow
    assert "/actions/runs?status=${active_status}&per_page=100" in workflow
    assert "for active_status in queued in_progress" in workflow
    assert '"pull_request" or .event == "pull_request_target"' in workflow
    assert "$current_pr_head == null or .head_sha != $current_pr_head" in workflow
    assert ".head_sha != $current_default_sha" in workflow
    assert "do not match an open PR or default-branch Current HEAD" in workflow
    assert '.current_head // "closed-or-no-open-pr"' in workflow
    assert '.current_head // \\"closed-or-no-open-pr\\"' not in workflow
    assert "select($current_pr_heads[$head_key] == null)" in workflow
    assert "Could not cancel superseded run" in workflow
    assert "No run will be cancelled from incomplete evidence" in workflow
    assert "queue_hygiene_ready=false" in workflow
    # Organization sweep budgets must be consumed across the repository loop;
    # resetting the configured limit for every target can flood Actions with
    # long-running review dispatches.
    assert '"$ORG_SWEEP_REVIEW_DISPATCH_LIMIT" =~ ^(-1|[0-9]+)$' in workflow
    assert '"$ORG_SWEEP_BRANCH_UPDATE_LIMIT" =~ ^(-1|[0-9]+)$' in workflow
    assert "org_review_dispatches_used=0" in workflow
    assert "org_branch_updates_used=0" in workflow
    assert 'review_dispatch_limit=$((ORG_SWEEP_REVIEW_DISPATCH_LIMIT - org_review_dispatches_used))' in workflow
    assert 'branch_update_limit=$((ORG_SWEEP_BRANCH_UPDATE_LIMIT - org_branch_updates_used))' in workflow
    assert '--review-dispatch-limit "$review_dispatch_limit"' in workflow
    assert '--branch-update-limit "$branch_update_limit"' in workflow
    assert 'grep -Ec \'^PR #[0-9]+: (review_dispatch|security_dispatch):\'' in workflow
    assert 'grep -Ec \'^PR #[0-9]+: (update_branch|restamp_head):\'' in workflow
    # The scheduler requires --project-flow; the sweep must derive and pass it
    # per target repository (regression: the first sweep failed every repo with
    # "--project-flow is required").
    assert "--project-flow" in workflow
    assert 'main|master) project_flow="github-flow"' in workflow
    assert 'develop) project_flow="git-flow"' in workflow


def test_org_queue_sweep_superseded_run_log_filter_executes() -> None:
    """The Current-HEAD cancellation evidence must be valid jq, not just valid Bash."""
    jq = shutil.which("jq")
    if jq is None:
        pytest.skip("jq is required for the executable workflow filter regression test")

    workflow = workflow_text("pr-review-merge-scheduler.yml")
    jq_line = next(
        line.strip()
        for line in workflow.splitlines()
        if "closed-or-no-open-pr" in line and "jq -r" in line
    )
    jq_filter = shlex.split(jq_line)[2]
    payload = [
        {
            "id": 42,
            "name": "Required OpenCode Review",
            "status": "in_progress",
            "event": "pull_request_target",
            "head_branch": "old-head",
            "run_head": "deadbeef",
            "current_head": None,
        }
    ]

    result = subprocess.run(
        [jq, "-r", jq_filter],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "current_head=closed-or-no-open-pr" in result.stdout


def _extract_org_sweep_rotation_snippet(workflow: str) -> str:
    """Return only the rotation-offset bash block, without the surrounding
    `gh api`/dispatch logic that would require live network credentials."""

    start_marker = "          sweep_target_count=${#sweep_targets[@]}\n"
    end_marker = 'rotation tick ${ORG_SWEEP_ROTATION_INDEX})."\n'
    start = workflow.index(start_marker)
    end = workflow.index(end_marker, start) + len(end_marker)
    return textwrap.dedent(workflow[start:end])


def test_org_queue_sweep_rotation_offset_is_deterministic_and_reorders_targets() -> None:
    """Rotating the sweep walk order must preserve every target and only reorder them."""
    workflow = workflow_text("pr-review-merge-scheduler.yml")
    snippet = _extract_org_sweep_rotation_snippet(workflow)

    for rotation_index, expected_first in (
        ("0", "repo-a"),
        ("1", "repo-b"),
        ("2", "repo-c"),
        ("5", "repo-a"),  # 5 % 5 == 0: wraps back to unrotated order
        ("7", "repo-c"),  # 7 % 5 == 2
    ):
        script = (
            "sweep_targets=($'repo-a\\tmain' $'repo-b\\tmain' $'repo-c\\tmain' "
            "$'repo-d\\tmain' $'repo-e\\tmain')\n"
            + snippet
            + '\nprintf "%s\\n" "${sweep_targets[@]}"\n'
        )
        result = subprocess.run(
            ["bash", "-euo", "pipefail", "-c", script],
            env={**os.environ, "ORG_SWEEP_ROTATION_INDEX": rotation_index},
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        rotated = [
            line.split("\t")[0]
            for line in result.stdout.strip().splitlines()
            if "\t" in line
        ]
        assert len(rotated) == 5
        assert set(rotated) == {"repo-a", "repo-b", "repo-c", "repo-d", "repo-e"}
        assert rotated[0] == expected_first, (rotation_index, result.stdout)


def test_org_queue_sweep_rotation_offset_is_safe_with_no_targets() -> None:
    """An org with no sweepable repositories must not crash the rotation arithmetic."""
    workflow = workflow_text("pr-review-merge-scheduler.yml")
    snippet = _extract_org_sweep_rotation_snippet(workflow)
    script = "sweep_targets=()\n" + snippet
    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", script],
        env={**os.environ, "ORG_SWEEP_ROTATION_INDEX": "3"},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "starting at rotation offset 0" in result.stdout


def _extract_org_sweep_rotation_default_snippet(workflow: str) -> str:
    """Return only the wall-clock-default/validation block for the rotation index,
    without the surrounding `gh api` calls that would require network credentials."""

    start_marker = "          if [ -z \"${ORG_SWEEP_ROTATION_INDEX:-}\" ]; then\n"
    end_marker = "            exit 1\n          fi\n\n          repositories_json="
    start = workflow.index(start_marker)
    end = workflow.index(end_marker, start) + len("            exit 1\n          fi\n")
    return textwrap.dedent(workflow[start:end])


def _fake_gh_script(*, get_ok: bool, get_value: str, patch_ok: bool, post_ok: bool) -> str:
    """A stand-in `gh` executable simulating the repository-variable API.

    ``get_ok`` controls whether `gh api .../variables/NAME --jq .value`
    exits zero at all -- a real "does the variable exist and is it
    readable" outcome, kept distinct from what value it prints on success
    (``get_value``), so tests can simulate a *failed* read (transient error
    or a genuinely missing variable) separately from a *successful* read
    of an empty/malformed value. ``patch_ok``/``post_ok`` control whether
    the corresponding mutation exits zero, so tests can force the
    PATCH-then-POST-create fallback or the full-failure wall-clock
    fallback without a real GitHub API call.
    """
    get_exit = "0" if get_ok else "1"
    patch_exit = "0" if patch_ok else "1"
    post_exit = "0" if post_ok else "1"
    return textwrap.dedent(
        f"""\
        #!/usr/bin/env bash
        set -euo pipefail
        if [ "$1" != "api" ]; then
          echo "unsupported fake gh invocation: $*" >&2
          exit 2
        fi
        shift
        if [[ "$1" == *"/variables/"* ]] && [[ "$*" == *"-X PATCH"* || "$*" == *"PATCH"* ]]; then
          exit {patch_exit}
        fi
        if [[ "$1" == "repos/"*"/actions/variables" ]]; then
          exit {post_exit}
        fi
        if [[ "$1" == *"/variables/"* ]]; then
          if [ "{get_exit}" = "0" ]; then
            printf '%s' "{get_value}"
          fi
          exit {get_exit}
        fi
        echo "unsupported fake gh api path: $1" >&2
        exit 2
        """
    )


def _run_rotation_default_snippet(
    snippet: str,
    tmp_path: Path,
    *,
    get_ok: bool = True,
    get_value: str,
    patch_ok: bool,
    post_ok: bool,
) -> subprocess.CompletedProcess[str]:
    """Execute the extracted default/validation block with a fake `gh` on PATH."""

    fake_gh = tmp_path / "gh"
    fake_gh.write_text(
        _fake_gh_script(get_ok=get_ok, get_value=get_value, patch_ok=patch_ok, post_ok=post_ok),
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)
    script = snippet + '\nprintf "%s\\n" "$ORG_SWEEP_ROTATION_INDEX"\n'
    env = dict(os.environ)
    env.pop("ORG_SWEEP_ROTATION_INDEX", None)
    env["GITHUB_REPOSITORY"] = "ContextualWisdomLab/.github"
    env["PATH"] = f"{tmp_path}{os.pathsep}{env.get('PATH', '')}"
    return subprocess.run(
        ["bash", "-euo", "pipefail", "-c", script], env=env, capture_output=True, text=True
    )


def test_org_queue_sweep_rotation_index_uses_persistent_counter_when_available(
    tmp_path: Path,
) -> None:
    """The primary source increments a persistent counter by exactly one per
    actual sweep execution — immune to how much wall-clock time a prior
    slow (up to 60-minute, non-cancelling) run consumed, which a wall-clock
    tick alone cannot guarantee (CodeRabbit review finding on #1223)."""

    workflow = workflow_text("pr-review-merge-scheduler.yml")
    snippet = _extract_org_sweep_rotation_default_snippet(workflow)

    result = _run_rotation_default_snippet(
        snippet, tmp_path, get_value="7", patch_ok=True, post_ok=True
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "8"  # incremented by exactly one


def test_org_queue_sweep_rotation_index_counter_increment_forces_base_10(
    tmp_path: Path,
) -> None:
    """A manually-seeded leading-zero value ("08") must not be parsed as
    octal, where it would error under set -e (Devin review finding on
    #1223) — unprefixed bash arithmetic treats a leading zero as an octal
    literal, and "08"/"09" are not valid octal digits."""

    workflow = workflow_text("pr-review-merge-scheduler.yml")
    snippet = _extract_org_sweep_rotation_default_snippet(workflow)

    result = _run_rotation_default_snippet(
        snippet, tmp_path, get_value="08", patch_ok=True, post_ok=True
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "9"


def test_org_queue_sweep_rotation_index_creates_counter_on_first_run(tmp_path: Path) -> None:
    """A failed read (variable does not exist yet) falls back to creating it."""

    workflow = workflow_text("pr-review-merge-scheduler.yml")
    snippet = _extract_org_sweep_rotation_default_snippet(workflow)

    result = _run_rotation_default_snippet(
        snippet, tmp_path, get_ok=False, get_value="", patch_ok=False, post_ok=True
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "1"


def test_org_queue_sweep_rotation_index_falls_back_to_wall_clock(tmp_path: Path) -> None:
    """If the persistent counter is entirely unavailable (both the read and
    the create-on-first-run POST fail), degrade to a wall-clock tick rather
    than failing the whole sweep over a fairness mechanism."""

    workflow = workflow_text("pr-review-merge-scheduler.yml")
    snippet = _extract_org_sweep_rotation_default_snippet(workflow)

    result = _run_rotation_default_snippet(
        snippet, tmp_path, get_ok=False, get_value="", patch_ok=False, post_ok=False
    )
    assert result.returncode == 0, result.stderr
    stdout_lines = result.stdout.strip().splitlines()
    computed_tick = int(stdout_lines[-1])  # last line: the printed value; earlier: the warning
    expected_tick = int(time.time()) // 900
    assert abs(computed_tick - expected_tick) <= 1  # tolerate a tick boundary race
    assert "could not read/write" in result.stdout  # a `::warning::` workflow command


def test_org_queue_sweep_rotation_index_transient_read_failure_does_not_reset_counter(
    tmp_path: Path,
) -> None:
    """A *failed* read must never be treated as "the counter is 0 and safe to
    PATCH": that would silently reset an already-accumulated counter value
    back down to 1, restarting the rotation sequence instead of degrading to
    the wall-clock fallback (Devin review finding on #1223). Simulated here
    as: the read fails, and the create-on-first-run POST also fails (as it
    should when the variable genuinely already exists and this run simply
    could not see it) -- landing on the wall-clock fallback rather than a
    PATCH that would have clobbered the real value."""

    workflow = workflow_text("pr-review-merge-scheduler.yml")
    snippet = _extract_org_sweep_rotation_default_snippet(workflow)

    result = _run_rotation_default_snippet(
        snippet, tmp_path, get_ok=False, get_value="", patch_ok=True, post_ok=False
    )
    assert result.returncode == 0, result.stderr
    stdout_lines = result.stdout.strip().splitlines()
    computed_tick = int(stdout_lines[-1])
    expected_tick = int(time.time()) // 900
    assert abs(computed_tick - expected_tick) <= 1
    # Critically: never "1" -- that would mean the failed read was treated
    # as a fresh-start reset rather than an unreadable existing value.
    assert stdout_lines[-1] != "1"


def test_org_queue_sweep_rotation_index_successful_read_but_failed_patch_falls_back(
    tmp_path: Path,
) -> None:
    """A successful read of an existing value, followed by a failed PATCH,
    must fall back to the wall-clock tick and log the value that could not
    be written -- not silently drop the accumulated counter."""

    workflow = workflow_text("pr-review-merge-scheduler.yml")
    snippet = _extract_org_sweep_rotation_default_snippet(workflow)

    result = _run_rotation_default_snippet(
        snippet, tmp_path, get_ok=True, get_value="41", patch_ok=False, post_ok=False
    )
    assert result.returncode == 0, result.stderr
    stdout_lines = result.stdout.strip().splitlines()
    computed_tick = int(stdout_lines[-1])
    expected_tick = int(time.time()) // 900
    assert abs(computed_tick - expected_tick) <= 1
    assert "read ORG_SWEEP_ROTATION_COUNTER=41 but could not PATCH it" in result.stdout


def test_org_queue_sweep_rotation_index_override_is_preserved() -> None:
    """An explicitly injected value (as tests do) is never overwritten."""

    workflow = workflow_text("pr-review-merge-scheduler.yml")
    snippet = _extract_org_sweep_rotation_default_snippet(workflow)
    script = snippet + '\nprintf "%s\\n" "$ORG_SWEEP_ROTATION_INDEX"\n'

    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", script],
        env={**os.environ, "ORG_SWEEP_ROTATION_INDEX": "42"},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "42"


def test_org_queue_sweep_rotation_index_rejects_malformed_override() -> None:
    """A malformed override still fails closed rather than reaching arithmetic."""

    workflow = workflow_text("pr-review-merge-scheduler.yml")
    snippet = _extract_org_sweep_rotation_default_snippet(workflow)
    script = snippet + '\nprintf "%s\\n" "$ORG_SWEEP_ROTATION_INDEX"\n'

    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", script],
        env={**os.environ, "ORG_SWEEP_ROTATION_INDEX": "not-a-number"},
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "ORG_SWEEP_ROTATION_INDEX must be a non-negative integer" in result.stdout


def test_org_queue_sweep_documents_rotation_leverage_and_validates_input() -> None:
    """Record why rotation exists and keep the new input on the same fail-closed contract."""
    workflow = workflow_text("pr-review-merge-scheduler.yml")

    assert "ContextualWisdomLab/.github#1219" in workflow
    assert (
        'ORG_SWEEP_ROTATION_INDEX=$(( $(date -u +%s) / 900 ))'
    ) in workflow
    assert (
        'if ! [[ "$ORG_SWEEP_ROTATION_INDEX" =~ ^[0-9]+$ ]]; then'
    ) in workflow
    assert (
        "rotation_offset=$(( ORG_SWEEP_ROTATION_INDEX % sweep_target_count ))"
    ) in workflow
    # `github.run_number` increments on every trigger of this workflow, not
    # only the sweep schedule, so it cannot give the per-sweep-tick rotation
    # guarantee the fix is meant to provide (ContextualWisdomLab/.github#1220
    # review finding). The env-block default must not reintroduce it.
    assert "ORG_SWEEP_ROTATION_INDEX: ${{ github.run_number }}" not in workflow
    # The fix must not change the org-wide budget itself, only which
    # repositories consume it — otherwise it reintroduces the exact
    # cost/rate-limit risk #1219 explicitly declined to guess at.
    assert "vars.ORG_SWEEP_REVIEW_DISPATCH_LIMIT || '1'" in workflow


def test_org_queue_sweep_manual_cadence_inputs_reach_the_sweep_job() -> None:
    """Manual full-sweep cadence must override repository variables and defaults."""
    workflow = workflow_text("pr-review-merge-scheduler.yml")

    assert (
        "ORG_SWEEP_REVIEW_DISPATCH_LIMIT: ${{ github.event.client_payload.review_dispatch_limit || inputs.review_dispatch_limit || "
        "vars.ORG_SWEEP_REVIEW_DISPATCH_LIMIT || '1' }}"
    ) in workflow
    assert (
        "STALE_OPENCODE_MINUTES: ${{ github.event.client_payload.stale_opencode_minutes || inputs.stale_opencode_minutes || "
        "vars.STALE_OPENCODE_MINUTES || '90' }}"
    ) in workflow
    assert (
        "ORG_SWEEP_MAX_PRS: ${{ github.event.client_payload.max_prs || inputs.max_prs || vars.ORG_SWEEP_MAX_PRS || '1000' }}"
    ) in workflow
    assert (
        "ORG_SWEEP_TRIGGER_REVIEWS: ${{ github.event_name == 'schedule' || github.event_name == 'repository_dispatch' && github.event.client_payload.trigger_reviews != false || inputs.trigger_reviews == true }}"
        in workflow
    )
    assert (
        "ORG_SWEEP_ENABLE_AUTO_MERGE: ${{ github.event_name == 'schedule' || github.event_name == 'repository_dispatch' && github.event.client_payload.enable_auto_merge != false || inputs.enable_auto_merge == true }}"
    ) in workflow
    assert (
        "ORG_SWEEP_MERGE_MODE: ${{ github.event.client_payload.merge_mode || inputs.merge_mode || 'direct_or_auto' }}"
        in workflow
    )
    assert (
        "ORG_SWEEP_UPDATE_BRANCHES: ${{ github.event_name == 'schedule' || github.event_name == 'repository_dispatch' && github.event.client_payload.update_branches != false || inputs.update_branches == true }}"
        in workflow
    )
    assert 'if [ "$ORG_SWEEP_TRIGGER_REVIEWS" = "true" ]; then' in workflow
    assert 'if [ "$ORG_SWEEP_ENABLE_AUTO_MERGE" = "true" ]; then' in workflow
    assert '--merge-mode "$ORG_SWEEP_MERGE_MODE"' in workflow
    assert 'if [ "$ORG_SWEEP_UPDATE_BRANCHES" = "true" ]; then' in workflow


def test_org_queue_sweep_active_run_aggregation_tolerates_error_payloads() -> None:
    """An inaccessible Actions page must not add a secondary jq null error."""
    jq = shutil.which("jq")
    if jq is None:
        pytest.skip("jq is required for the executable workflow filter regression test")

    workflow = workflow_text("pr-review-merge-scheduler.yml")
    aggregation_line = next(
        line.strip()
        for line in workflow.splitlines()
        if "done | jq -sc" in line and "workflow_runs" in line
    )
    jq_filter = shlex.split(aggregation_line)[4]
    payload = (
        '{"workflow_runs":[]}\n{"message":"Resource not accessible by integration"}\n'
    )

    result = subprocess.run(
        [jq, "-sc", jq_filter],
        input=payload,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == []


def test_org_queue_sweep_treats_inaccessible_repositories_as_non_fatal() -> None:
    """A repository the sweep credential cannot read must not fail the sweep.

    When the OpenCode app is not installed on a sibling repository (or the
    PR_REVIEW_MERGE_TOKEN does not cover it), every read returns HTTP 403
    "Resource not accessible by integration". That is an access-grant fact the
    automation can never resolve, so those repositories are reported as skipped,
    non-fatal "unavailable" repositories rather than hard failures — otherwise a
    handful of un-enrolled repositories keeps the scheduled sweep (the
    ``*/15 * * * *`` cron) permanently red and masks a genuinely new repository
    that starts failing.

    The sweep stays fail-closed two ways: any non-403 scheduler failure still
    increments ``failures`` and fails the job, and if MORE than
    ``ORG_SWEEP_MAX_UNAVAILABLE`` repositories become unreachable at once (a
    credential-scope regression, not a few un-enrolled repos) the job fails.
    """
    workflow = workflow_text("pr-review-merge-scheduler.yml")

    # The 403 signal is classified as a skipped, non-fatal "unavailable" repo.
    assert "ORG_SWEEP_MAX_UNAVAILABLE" in workflow
    assert 'grep -qF "Resource not accessible by integration"' in workflow
    assert "unavailable=$((unavailable + 1))" in workflow
    assert 'unavailable_repos+=("$repo_full_name")' in workflow
    assert "the sweep credential lacks access (HTTP 403" in workflow
    # A non-403 failure must still be a hard failure (fail-closed preserved).
    assert "failures=$((failures + 1))" in workflow
    assert "see the decision log above for the concrete per-PR reason" in workflow
    # Widespread inaccessibility is a credential regression and must fail loudly.
    assert 'if [ "$unavailable" -gt "$ORG_SWEEP_MAX_UNAVAILABLE" ]; then' in workflow
    assert "indicates a credential-scope regression" in workflow
    # The ceiling must be validated as a non-negative integer BEFORE the numeric
    # test, or a misconfigured non-integer would make "[ -gt ]" error inside an
    # if condition (which set -e does not trap) and silently skip the guard.
    assert '"$ORG_SWEEP_MAX_UNAVAILABLE" =~ ^[0-9]+$' in workflow
    assert "ORG_SWEEP_MAX_UNAVAILABLE must be a non-negative integer" in workflow


def test_fix_scheduler_cancels_superseded_cron_runs() -> None:
    """Cancel stale scheduled repair runs before they duplicate mutation work."""
    workflow = workflow_text("pr-review-fix-scheduler.yml")

    assert "central-pr-review-fix-scheduler-" in workflow
    assert "cancel-in-progress: true" in workflow


def test_security_scan_skips_dependency_review_when_dependency_graph_is_unavailable() -> (
    None
):
    """Treat unsupported dependency graphs as an explicit non-enforceable case."""
    workflow = workflow_text("security-scan.yml")

    assert "id: dependency_review_support" in workflow
    assert "/dependency-graph/compare/${BASE_SHA}...${HEAD_SHA}" in workflow
    assert '"$status" = "403"' in workflow
    assert '"$status" = "404"' in workflow
    assert "steps.dependency_review_support.outputs.supported == 'true'" in workflow


def test_security_scan_preserves_base_output_across_cross_fork_checkout() -> None:
    """Limit cross-fork replacement to a child checkout directory."""
    workflow = workflow_text("security-scan.yml")

    assert workflow.count("--allow-no-lockfiles") == 4
    assert "--output-file=old-results.json" in workflow
    assert "--output-file=new-results.json" in workflow
    assert "--output-files=sarif:results.sarif" in workflow
    assert "--output-file=results.sarif" not in workflow
    assert "--output=old-results.json" not in workflow
    assert "--output=new-results.json" not in workflow
    assert workflow.count("path: source") == 2
    assert workflow.count("\n            source/\n") == 4
    assert "clean: false" not in workflow
    assert "test -s old-results.json" in workflow
    assert "test -s new-results.json" in workflow


def test_secret_scan_push_limits_gitleaks_to_current_branch_history() -> None:
    """Limit push secret scanning to the current branch history."""
    workflow = workflow_text("secret-scan.yml")

    assert "CURRENT_SHA: ${{ github.sha }}" in workflow
    assert 'log_opts="${BASE_SHA}..${HEAD_SHA}"' in workflow
    assert 'log_opts="${CURRENT_SHA}"' in workflow
    assert '--log-opts="${log_opts}"' in workflow
    assert "unrelated remote refs are excluded" in workflow


def test_osv_pr_workflow_has_one_startup_safe_scan_args_block() -> None:
    """Keep the standalone OSV workflow's resolver settings singular and safe."""
    workflow = workflow_text("osv-scanner-pr.yml")
    concurrency_contract = workflow.split("permissions:", 1)[0]

    assert (
        "github.event_name == 'pull_request' && github.event.pull_request.base.repo.full_name"
        in concurrency_contract
    )
    assert (
        "github.event_name == 'pull_request' && github.event.pull_request.number"
        in concurrency_contract
    )
    assert workflow.count("scan-args: |-") == 1
    assert "--no-resolve" in workflow
    assert (
        "--maven-registry=https://maven-central.storage-download.googleapis.com/maven2"
        in workflow
    )


def test_osv_scan_logs_and_retries_without_transitive_resolution_on_resolver_failure() -> (
    None
):
    """Retry OSV direct evidence without allowing transitive resolver stalls."""
    workflow = workflow_text("security-scan.yml")

    assert "timeout-minutes: 25" in workflow
    assert "Explain OSV scan mode and timeout budget" in workflow
    assert (
        "external transitive registry resolver stalls cannot hold the required-check queue indefinitely"
        in workflow
    )
    assert "id: osv_base" in workflow
    assert "id: osv_head" in workflow
    assert "id: osv_base_retry" in workflow
    assert "id: osv_head_retry" in workflow
    assert "Classify base OSV result evidence" in workflow
    assert "Classify head OSV result evidence" in workflow
    assert "Classify retried base OSV result evidence" in workflow
    assert "Classify retried head OSV result evidence" in workflow
    assert "Retry base OSV without transitive resolution" in workflow
    assert "Retry head OSV without transitive resolution" in workflow
    assert workflow.count("timeout-minutes: 8") == 2
    assert workflow.count("timeout-minutes: 4") == 2
    assert workflow.count("\n            --no-resolve\n") == 4
    assert workflow.count("did not produce authoritative result evidence") == 2
    assert (
        "Direct manifest and lockfile vulnerability evidence remains enforced"
        in workflow
    )
    assert (
        "external transitive registry resolution is intentionally avoided" in workflow
    )
    assert (
        "Retry base OSV without transitive resolution\n"
        "        if: steps.osv_base_evidence.outputs.complete != 'true'\n"
        "        id: osv_base_retry\n        continue-on-error: true"
        in workflow
    )
    assert (
        "Retry head OSV without transitive resolution\n"
        "        if: steps.osv_head_evidence.outputs.complete != 'true'\n"
        "        id: osv_head_retry\n        continue-on-error: true"
        in workflow
    )
    assert "--output-file=old-results.json" in workflow
    assert "--output-file=new-results.json" in workflow
    assert "--output-files=sarif:results.sarif" in workflow
    assert "--output=old-results.json" not in workflow
    assert "--output=new-results.json" not in workflow
    assert "Require authoritative base and head OSV evidence" in workflow
    assert "Require successful base and head OSV scans" not in workflow
    assert "Normalize successful empty OSV result documents" not in workflow
    assert workflow.count("failure with authoritative vulnerability evidence") == 1
    assert workflow.count("completed successfully without findings output") == 1
    assert workflow.count('runpy.run_path(os.path.join(os.environ["RUNNER_TEMP"]') == 4
    assert "Preserve base OSV evidence and direct-source provenance" in workflow
    assert 'cp -- old-results.json "$RUNNER_TEMP/osv-base-provenance/old-results.json"' in workflow
    assert "Restore authoritative base OSV evidence" in workflow
    assert workflow.index("Preserve base OSV evidence and direct-source provenance") < workflow.index(
        "Checkout head"
    ) < workflow.index("Restore authoritative base OSV evidence")
    assert workflow.index("Require authoritative base and head OSV evidence") < workflow.index(
        "Require OSV scan output"
    )
    assert "Print OSV findings being compared" in workflow
    assert "OSV {label} scan produced {len(findings)} finding(s)" in workflow


@pytest.mark.parametrize(
    ("outcome", "payload", "expected_complete", "expected_message"),
    [
        (
            "failure",
            {"results": [{"packages": [{"vulnerabilities": [{"id": "PYSEC-1"}]}]}]},
            "true",
            "failure with authoritative vulnerability evidence",
        ),
        (
            "failure",
            {"results": []},
            "false",
            "failed without authoritative vulnerability evidence",
        ),
        (
            "failure",
            {"results": "malformed"},
            "false",
            "results must be a list",
        ),
    ],
)
def test_osv_result_evidence_classifier_distinguishes_findings_from_scan_failure(
    tmp_path: Path,
    outcome: str,
    payload: dict[str, object],
    expected_complete: str,
    expected_message: str,
) -> None:
    workflow = workflow_text("security-scan.yml")
    script = osv_result_classifier_script(workflow)
    result_path = tmp_path / "old-results.json"
    result_path.write_text(json.dumps(payload), encoding="utf-8")
    output_path = tmp_path / "github-output"

    result = subprocess.run(
        [sys.executable, "-"],
        input=script,
        text=True,
        capture_output=True,
        env={
            **os.environ,
            "SCAN_OUTCOME": outcome,
            "RESULT_FILE": str(result_path),
            "GITHUB_OUTPUT": str(output_path),
        },
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert f"complete={expected_complete}" in output_path.read_text(encoding="utf-8")
    assert expected_message in result.stdout


def test_osv_result_evidence_classifier_normalizes_only_successful_empty_scan(
    tmp_path: Path,
) -> None:
    workflow = workflow_text("security-scan.yml")
    script = osv_result_classifier_script(workflow)
    result_path = tmp_path / "old-results.json"
    output_path = tmp_path / "github-output"

    result = subprocess.run(
        [sys.executable, "-"],
        input=script,
        text=True,
        capture_output=True,
        env={
            **os.environ,
            "SCAN_OUTCOME": "success",
            "RESULT_FILE": str(result_path),
            "GITHUB_OUTPUT": str(output_path),
        },
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert output_path.read_text(encoding="utf-8").strip() == "complete=true"
    assert json.loads(result_path.read_text(encoding="utf-8")) == {"results": []}


def test_osv_result_evidence_classifier_rejects_symlinked_finding_document(
    tmp_path: Path,
) -> None:
    workflow = workflow_text("security-scan.yml")
    script = osv_result_classifier_script(workflow)
    target_path = tmp_path / "target.json"
    target_path.write_text(
        json.dumps(
            {"results": [{"packages": [{"vulnerabilities": [{"id": "spoof"}]}]}]}
        ),
        encoding="utf-8",
    )
    result_path = tmp_path / "old-results.json"
    result_path.symlink_to(target_path)
    output_path = tmp_path / "github-output"

    result = subprocess.run(
        [sys.executable, "-"],
        input=script,
        text=True,
        capture_output=True,
        env={
            **os.environ,
            "SCAN_OUTCOME": "failure",
            "RESULT_FILE": str(result_path),
            "GITHUB_OUTPUT": str(output_path),
        },
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert output_path.read_text(encoding="utf-8").strip() == "complete=false"
    assert "result document must be a regular file" in result.stdout


def test_osv_sarif_upload_is_marked_comprehensive_after_clean_comparison(
    tmp_path: Path,
) -> None:
    """Mark a clean OSV comparison as comprehensive for code-scanning closure."""
    workflow = workflow_text("security-scan.yml")
    step = "      - name: Mark clean OSV SARIF as comprehensive\n"
    start = workflow.index(step)
    run_start = workflow.index("        run: |\n", start) + len("        run: |\n")
    run_end = workflow.index("\n      - name:", run_start)
    script = textwrap.dedent(
        "\n".join(line[10:] for line in workflow[run_start:run_end].splitlines())
    )
    sarif_path = tmp_path / "results.sarif"
    sarif_path.write_text(
        json.dumps(
            {
                "version": "2.1.0",
                "runs": [
                    {
                        "tool": {
                            "driver": {
                                "name": "osv-scanner",
                                "isComprehensive": False,
                            }
                        },
                        "results": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    updated = json.loads(sarif_path.read_text(encoding="utf-8"))

    assert updated["runs"][0]["tool"]["driver"]["isComprehensive"] is True
    assert "marked the code-scanning analysis comprehensive" in result.stdout


def test_security_scan_osv_upload_uses_pr_head_for_pr_head_sarif() -> None:
    """Upload OSV SARIF against the exact pull-request head revision."""
    workflow = workflow_text("security-scan.yml")
    upload_step = workflow_step(workflow, "Upload OSV SARIF to code scanning")

    assert "Checkout PR merge ref for OSV SARIF upload" not in workflow
    assert 'merge_ref="refs/pull/${PR_NUMBER}/merge"' not in workflow
    assert "commit_oid is not a merge commit" in upload_step
    assert "github/codeql-action/upload-sarif" in upload_step
    assert "sarif_file: results.sarif" in upload_step
    assert "ref: refs/pull/${{ github.event.pull_request.number }}/head" in upload_step
    assert "sha: ${{ github.event.pull_request.head.sha }}" in upload_step
    assert "category:" not in upload_step
    assert "continue-on-error: true" in upload_step
    assert "wait-for-processing: false" in upload_step


def test_pr_sarif_upload_rate_limits_do_not_mask_scanner_gates() -> None:
    """Scanner hard gates must run even when GitHub code-scanning upload is busy."""
    cases = (
        (
            "python-security.yml",
            "Upload Bandit SARIF to code scanning",
            "upload_bandit_sarif",
            "Report Bandit SARIF upload failure",
            "upload rate limits cannot hide MEDIUM+ findings",
        ),
        (
            "security-scan.yml",
            "Upload OSV SARIF to code scanning",
            "upload_osv_sarif",
            "Report OSV SARIF upload failure",
            "upload rate limits cannot hide OSV findings",
        ),
        (
            "security-scan.yml",
            "Upload Trivy SARIF to code scanning",
            "upload_trivy_sarif",
            "Report Trivy SARIF upload failure",
            "upload rate limits cannot hide CRITICAL/HIGH/MEDIUM findings",
        ),
        (
            "security-scan.yml",
            "Upload Scorecard SARIF to code scanning",
            "upload_scorecard_sarif",
            "Report Scorecard SARIF upload failure",
            "CodeQL, OSV, Trivy, and dependency-review remain the hard gates",
        ),
    )

    for filename, upload_name, step_id, warning_name, warning_text in cases:
        workflow = workflow_text(filename)
        upload_step = workflow_step(workflow, upload_name)
        warning_step = workflow_step(workflow, warning_name)

        assert f"id: {step_id}" in upload_step
        assert "continue-on-error: true" in upload_step
        assert "github/codeql-action/upload-sarif" in upload_step
        assert "wait-for-processing: false" in upload_step
        assert f"steps.{step_id}.outcome == 'failure'" in warning_step
        assert warning_text in warning_step


def test_standalone_osv_scan_delegates_sarif_upload_to_central_gate() -> None:
    """The supplemental OSV diff must not duplicate the central SARIF upload."""
    standalone = workflow_text("osv-scanner-pr.yml")
    central = workflow_text("security-scan.yml")

    assert "upload-sarif: false" in standalone
    assert "pinned upstream reusable workflow declares this permission" in standalone
    assert "security-events: write" in standalone
    assert "--fail-on-vuln=true" in central
    assert "Print OSV findings being compared" in central
    assert "Upload OSV SARIF to code scanning" in central


def test_osv_findings_log_accepts_null_results_for_manifestless_repos(
    tmp_path: Path,
) -> None:
    """Log zero findings when OSV returns null result arrays."""
    workflow = workflow_text("security-scan.yml")
    step = "      - name: Print OSV findings being compared\n"
    start = workflow.index(step)
    run_start = workflow.index("        run: |\n", start) + len("        run: |\n")
    run_end = workflow.index("\n      - name:", run_start)
    script = textwrap.dedent(
        "\n".join(line[10:] for line in workflow[run_start:run_end].splitlines())
    )

    for filename in ("old-results.json", "new-results.json"):
        (tmp_path / filename).write_text('{"results": null}\n', encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    assert "OSV base scan produced 0 finding(s) in old-results.json." in result.stdout
    assert "OSV head scan produced 0 finding(s) in new-results.json." in result.stdout


def test_optional_strix_workflow_absence_is_logged_without_failing_lookup() -> None:
    """Make optional Strix absence visible without turning it into a lookup crash."""
    workflow = workflow_text("opencode-review-dispatch.yml")
    failed_check_evidence = (
        REPO_ROOT / "scripts/ci/collect_failed_check_evidence.sh"
    ).read_text(encoding="utf-8")

    assert "skipping optional current-head Strix workflow-run lookup" in workflow
    assert "skipping optional manual Strix run lookup" in workflow
    assert "Optional workflow %s is not installed" in failed_check_evidence
    assert 'if target_workflow_available "strix.yml"; then' in failed_check_evidence


def test_strix_provider_outage_without_findings_is_typed_non_passing() -> None:
    """Keep provider outages typed and non-passing until authoritative evidence exists."""
    workflow = workflow_text("strix.yml")

    assert "RateLimitError|Too many requests" in workflow
    assert "exceeded your current quota" in workflow
    assert "billing details" in workflow
    assert "LLM warm-up failed" in workflow
    assert "STRIX_PROVIDER_UNAVAILABLE" in workflow
    assert "model_behavior_error_signal=" in workflow
    assert "agents|pydantic_ai|strix" in workflow
    assert "zero_vulnerabilities_signal" not in workflow
    assert "Vulnerabilities[[:space:]]+[1-9]" in workflow
    assert "(^|[^A-Za-z0-9_])severity[[:space:]]*:" in workflow
    assert "STRIX_FAIL_ON_MIN_SEVERITY: MEDIUM" in workflow
    assert "::error title=STRIX_PROVIDER_UNAVAILABLE::" in workflow
    assert 'exit "$strix_rc"' in workflow
    assert "Treating as a neutral skip" not in workflow
    assert "authoritative vulnerability analysis" in workflow
    assert "incomplete scan into passing security evidence" in workflow
    assert (
        '&& ! grep -Eiq "$reported_vulnerability_signal" '
        '"$strix_neutralization_scope_log"' in workflow
    )


def test_strix_cross_repo_dispatch_uses_target_token_for_pr_scoping() -> None:
    """Bind cross-repository Strix scans to the target PR and authorized token."""
    workflow = workflow_text("strix.yml")
    run_step = workflow.split("      - name: Run Strix (quick)", 1)[1].split(
        "      - name:", 1
    )[0]

    assert "STRIX_TARGET_PATH:" in run_step
    assert "github.event_name == 'repository_dispatch'" in run_step
    assert "github.event.client_payload.pr_number != ''" in run_step
    assert (
        "steps.target_app_token.outputs.token || secrets.OPENCODE_APPROVE_TOKEN || "
        "github.token"
    ) in run_step
    assert "github.event_name == 'pull_request_target' && github.token" in run_step
    assert (
        "(github.event_name == 'pull_request_target' || "
        "github.event.client_payload.pr_number != '') && github.token"
    ) not in run_step


def test_pr_scorecard_sarif_delegates_sast_and_vulnerability_posture_to_hard_gates() -> (
    None
):
    """PR Scorecard SARIF should not duplicate CodeQL/OSV/Trivy hard gates."""
    for filename in ("scorecard-pr.yml", "security-scan.yml"):
        workflow = workflow_text(filename)

        assert 'PR_HARD_GATE_RULE_IDS = {"SASTID", "VulnerabilitiesID"}' in workflow
        assert 'PR_GOVERNANCE_RULE_IDS = {"FuzzingID"}' in workflow
        assert (
            "PR_DELEGATED_RULE_IDS = PR_HARD_GATE_RULE_IDS | PR_GOVERNANCE_RULE_IDS"
            in workflow
        )
        assert "Delegated " in workflow
        assert "CodeQL, OSV, Trivy, and dependency-review hard gates" in workflow
        assert "default-branch governance tracking" in workflow

    default_branch_scorecard = workflow_text("scorecard-analysis.yml")

    assert "PR_DELEGATED_RULE_IDS" not in default_branch_scorecard
    assert "FuzzingID" not in default_branch_scorecard
    assert "VulnerabilitiesID" not in default_branch_scorecard


def test_standalone_scorecard_delegates_code_scanning_upload_to_central_gate() -> None:
    """The supplemental Scorecard run must not duplicate the central SARIF upload."""
    standalone = workflow_text("scorecard-pr.yml")
    central = workflow_text("security-scan.yml")

    assert "security-events: write" not in standalone
    assert "github/codeql-action/upload-sarif" not in standalone
    assert "Preserve Scorecard PR SARIF evidence" in standalone
    assert "actions/upload-artifact" in standalone
    assert "Upload Scorecard SARIF to code scanning" in central
    assert "category: scorecard" in central


@pytest.mark.parametrize(
    ("workflow_name", "step_name"),
    (
        ("security-scan.yml", "Upload OSV SARIF to code scanning"),
        ("security-scan.yml", "Upload Trivy SARIF to code scanning"),
        ("security-scan.yml", "Upload Scorecard SARIF to code scanning"),
        ("python-security.yml", "Upload Bandit SARIF to code scanning"),
    ),
)
def test_sarif_upload_quota_is_separate_from_local_security_gates(
    workflow_name: str, step_name: str
) -> None:
    """Installation API exhaustion must not impersonate a scanner finding."""
    workflow = workflow_text(workflow_name)
    marker = f"      - name: {step_name}\n"
    start = workflow.index(marker)
    end = workflow.find("\n      - name:", start + len(marker))
    upload_step = workflow[start : end if end >= 0 else len(workflow)]

    assert "continue-on-error: true" in upload_step
    if workflow_name == "security-scan.yml":
        assert "--fail-on-vuln=true" in workflow
        assert "raise SystemExit(1)" in workflow
    else:
        assert "Enforce bandit gate (fail on MEDIUM+ findings)" in workflow
        assert "steps.bandit.outputs.rc != '0'" in workflow


def test_default_branch_scorecard_upload_quota_is_non_blocking() -> None:
    """A soft Scorecard upload outage must not fail the default branch."""
    workflow = workflow_text("scorecard-analysis.yml")
    marker = "      - name: Upload to code scanning\n"
    start = workflow.index(marker)
    upload_step = workflow[start:]

    assert "continue-on-error: true" in upload_step
    assert "github/codeql-action/upload-sarif" in upload_step


def test_trivy_failure_log_prints_sarif_finding_details(tmp_path: Path) -> None:
    """Print actionable Trivy SARIF details and fail only for actual findings."""
    workflow = workflow_text("security-scan.yml")
    assert "fail-on-severity: moderate" in workflow
    assert "severity: CRITICAL,HIGH,MEDIUM" in workflow
    assert 'exit-code: "0"' in workflow
    assert "Require Trivy SARIF output" in workflow

    step = "      - name: Print Trivy findings that failed the gate\n"
    start = workflow.index(step)
    run_start = workflow.index("        run: |\n", start) + len("        run: |\n")
    run_end = workflow.index("\n      - name:", run_start)
    script = "\n".join(line[10:] for line in workflow[run_start:run_end].splitlines())

    (tmp_path / "trivy-results.sarif").write_text(
        json.dumps(
            {
                "runs": [
                    {
                        "tool": {
                            "driver": {
                                "rules": [
                                    {
                                        "id": "CVE-TEST",
                                        "properties": {"security-severity": "9.8"},
                                    }
                                ]
                            }
                        },
                        "results": [
                            {
                                "ruleId": "CVE-TEST",
                                "message": {
                                    "text": "Artifact: app\nSeverity: HIGH\nMessage: vulnerable package"
                                },
                                "locations": [
                                    {
                                        "physicalLocation": {
                                            "artifactLocation": {
                                                "uri": "requirements.txt"
                                            },
                                            "region": {"startLine": 7},
                                        }
                                    }
                                ],
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "Trivy filesystem scan reported 1 finding(s):" in result.stdout
    assert "[HIGH (security-severity=9.8)] CVE-TEST requirements.txt:7" in result.stdout
    assert "vulnerable package" in result.stdout

    (tmp_path / "trivy-results.sarif").write_text(
        json.dumps({"runs": [{"tool": {"driver": {"rules": []}}, "results": []}]}),
        encoding="utf-8",
    )

    zero_result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )

    assert zero_result.returncode == 0
    assert (
        "Trivy filesystem scan completed with 0 CRITICAL/HIGH/MEDIUM findings"
        in zero_result.stdout
    )
    assert "failed" not in zero_result.stdout.lower()


def test_scorecard_medium_plus_governance_has_owner_and_runbook() -> None:
    """Guard repository-local controls for Scorecard Medium-or-higher alerts."""
    codeowners = (REPO_ROOT / ".github" / "CODEOWNERS").read_text(encoding="utf-8")
    runbook = (REPO_ROOT / "docs" / "scorecard-governance.md").read_text(
        encoding="utf-8"
    )

    assert "* @seonghobae" in codeowners
    assert ".github/workflows/* @seonghobae" in codeowners
    assert "scripts/ci/* @seonghobae" in codeowners

    for alert_id in ("BranchProtectionID", "MaintainedID", "SASTID", "CodeReviewID"):
        assert alert_id in runbook

    assert "Medium-or-higher governance findings" in runbook
    assert "current-head OpenCode review evidence" in runbook
    assert "review thread resolution" in runbook
    assert "latest head commit" in runbook
    assert "cancel superseded runs" in runbook
    assert "Every central workflow failure must print the actionable reason" in runbook
