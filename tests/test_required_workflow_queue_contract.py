"""Verify central required-workflow queue, security, and dispatch contracts."""

import json
import os
import re
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


def test_scheduler_uses_bounded_run_state_without_cache_lock_claims() -> None:
    """Keep each run bounded without treating immutable cache snapshots as locks."""
    workflow = workflow_text("pr-review-merge-scheduler.yml")

    assert workflow.count(
        '--admission-state-path "${RUNNER_TEMP}/review-admission/state.json"'
    ) == 1
    assert workflow.count("--admission-dispatch-budget") == 1
    assert workflow.count("--admission-sequence \"$GITHUB_RUN_ID\"") == 1
    assert "actions/cache/restore" not in workflow
    assert "actions/cache/save" not in workflow
    assert "actions/upload-artifact" not in workflow


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

    assert workflow.count("STALE_OPENCODE_MINUTES must contain only decimal digits") == 1
    assert workflow.count("STALE_OPENCODE_MINUTES must be between 1 and 1440") == 2
    assert workflow.count("stale_opencode_minutes=$((10#$STALE_OPENCODE_MINUTES))") == 1
    assert workflow.count('STALE_OPENCODE_MINUTES="$stale_opencode_minutes"') == 1


def test_merge_scheduler_uses_native_auto_merge_after_required_checks() -> None:
    """Do not enqueue a scheduler run after every required workflow completion."""
    workflow = workflow_text("pr-review-merge-scheduler.yml")
    concurrency_contract = workflow.split("concurrency:", 1)[1].split(
        "permissions:", 1
    )[0]

    assert "org-sweep" not in concurrency_contract
    assert "format('repo-dispatch-{0}', github.repository)" in concurrency_contract
    assert "workflow_run:" not in workflow.split("workflow_call:", 1)[0]
    assert "github.event.workflow_run" not in concurrency_contract
    assert "github.event_name == 'repository_dispatch' && github.run_id" not in (
        concurrency_contract
    )
    assert "cancel-in-progress: ${{" in concurrency_contract
    assert "github.event_name == 'repository_dispatch'" in concurrency_contract


def test_merge_scheduler_provides_same_repository_dispatch_credential() -> None:
    """Guard the runner-token dispatch credential for central review workflows.

    The scheduler runs inside the same repository as the central required
    workflows, so its repository-scoped token is the single dispatch credential.
    """
    workflow = workflow_text("pr-review-merge-scheduler.yml")

    assert workflow.count("SCHEDULER_DISPATCH_TOKEN: ${{ github.token }}") == 1


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
    assert 'target_default_branch="$(gh api "repos/${TARGET_REPOSITORY_INPUT}" --jq' in validation
    assert 'printf \'base_branch=%s\\n\' "$target_default_branch"' in validation
    assert "PR base %s; scheduler default branch %s" in validation
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


def test_required_opencode_dispatch_does_not_wait_on_merge_scheduler() -> None:
    """Dispatch review execution directly so polling cannot starve its producer."""
    workflow = workflow_text("opencode-review.yml")
    dispatch = workflow_step(workflow, "Request current-head OpenCode review execution")

    assert 'event_type:"opencode-review"' in dispatch
    assert 'event_type:"merge-scheduler"' not in dispatch
    assert 'required_run_id:$required_run_id' in dispatch
    for field in (
        "target_repository",
        "pr_number",
        "pr_base_ref",
        "pr_base_sha",
        "pr_head_ref",
        "pr_head_sha",
    ):
        assert f"{field}:${field}" in dispatch


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
        "codeql-pr.yml",
        "noema-review.yml",
        "opencode-review.yml",
        "security-scan.yml",
    ):
        workflow = workflow_text(filename)
        concurrency_contract = workflow.split("concurrency:", 1)[1].split(
            "permissions:", 1
        )[0]

        assert "concurrency:" in workflow
        assert "github.event.pull_request.base.repo.full_name" in concurrency_contract
        assert "github.repository" in concurrency_contract
        assert "github.event.pull_request.number" in workflow
        assert re.search(r"(?m)^concurrency:", workflow)
        assert "cancel-in-progress: true" in concurrency_contract
        if filename == "security-scan.yml":
            assert (
                "github.event_name == 'pull_request_target'" in concurrency_contract
                or ("github.event_name == 'pull_request'" in concurrency_contract)
            )
        elif filename == "opencode-review.yml":
            assert "required-opencode-review-${{" in concurrency_contract
            assert "outputs.admitted == 'true'" in workflow
        elif filename == "noema-review.yml":
            assert not re.search(r"(?m)^    concurrency:", workflow)
            assert "github.event.workflow_run" not in concurrency_contract
            assert "required-noema-review-${{" in concurrency_contract
            assert "outputs.admitted == 'true'" in workflow
        else:
            if filename == "codeql-pr.yml":
                assert "github.event_name == 'pull_request'" in concurrency_contract
            else:
                assert (
                    "github.event_name == 'pull_request_target'" in concurrency_contract
                )
        assert "github.event.pull_request.head.sha" not in concurrency_contract
        assert "format('pr-{0}-{1}'" not in concurrency_contract


def test_pr_quality_workflows_isolate_concurrency_by_repository_and_pr() -> None:
    """Quality runs from different repositories must never share a PR queue."""
    groups = {
        "agent-mention-router-quality-ci.yml": "agent-mention-router-quality",
        "cloudflare-dns.yml": "cloudflare-dns",
        "javascript-coverage-quality-ci.yml": "javascript-coverage-quality",
        "trusted-uv-materializer-quality-ci.yml": (
            "trusted-uv-materializer-quality"
        ),
    }

    for filename, group_name in groups.items():
        workflow = workflow_text(filename)
        concurrency = workflow.split("concurrency:", 1)[1].split("jobs:", 1)[0]
        assert (
            f"group: {group_name}-${{{{ github.repository }}}}-"
            "${{ github.event.pull_request.number || github.ref }}"
        ) in concurrency
        if filename == "cloudflare-dns.yml":
            assert (
                "cancel-in-progress: ${{ github.event_name == 'pull_request' }}"
                in concurrency
            )
        else:
            assert "cancel-in-progress: true" in concurrency


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


def test_strix_serializes_provider_evidence_per_repository_and_pr() -> None:
    """Scope Strix workflow admission per repository AND PR.

    History: from 2026-08-24 through 2026-09-03 the concurrency group was
    deliberately repository-wide (not PR-scoped) because PR-scoping is what
    caused a real litellm.RateLimitError storm against the shared NVIDIA NIM
    key on 2026-08-23/24 -- sibling PRs scanned concurrently, each retrying the
    shared key three times, producing fail-closed gate failures on every open
    PR. That repository-wide scoping fixed the storm but starved cross-PR
    Strix evidence within the same repository instead (a different PR's scan
    always queued behind whichever scan was already running there).

    Restored to PR-scoped on explicit owner authorization (2026-09-03) after
    confirming NVIDIA_NIM_API_KEY and NVIDIA_NIM_API_KEY_SUB have independent
    rate limits rather than a shared pool. The workflow-level group now retires
    superseded runs before runner admission, including runs still blocked by
    the organization-wide job ceiling. Native and dispatched evidence share
    one group; non-PR events use a unique run id.
    """
    workflow = workflow_text("strix.yml")
    concurrency_contract = workflow.split("concurrency:", 1)[1].split(
        "permissions:", 1
    )[0]
    strix_job = workflow.split("\n  strix:\n", 1)[1]

    assert re.search(r"(?m)^concurrency:", workflow)
    assert "needs: [changed-scope, admit-current-head]" in strix_job
    assert "needs.admit-current-head.outputs.admitted == 'true'" in strix_job
    assert "strix-security-scan-${{" in concurrency_contract
    assert "github.event.pull_request.base.repo.full_name" in concurrency_contract
    assert "github.event.client_payload.target_repository" in concurrency_contract
    assert "github.event.pull_request.number" in concurrency_contract
    assert "github.event.client_payload.pr_number" in concurrency_contract
    assert "github.run_id" in concurrency_contract
    assert "github.event.pull_request.head.sha" not in concurrency_contract
    assert "github.event.client_payload.pr_head_sha" not in concurrency_contract
    assert "cancel-in-progress: true" in concurrency_contract
    assert "    concurrency:" not in strix_job.split("    permissions:", 1)[0]
    assert "queue: max" not in workflow
    assert workflow.index("admit-current-head:") < workflow.index("\n  strix:\n")
    cleanup_job = workflow.split("  cancel-superseded-pr-runs:", 1)[1].split(
        "  strix:", 1
    )[0]
    assert "github.event.action == 'synchronize'" in cleanup_job
    assert 'endswith("@" + $head_sha)' in cleanup_job
    assert "/force-cancel" in cleanup_job
    assert 'gh api "repos/${TARGET_REPOSITORY}/pulls/${TARGET_PR_NUMBER}"' in cleanup_job
    assert "could not verify the live pull request" in cleanup_job
    assert "target changed before run selection" in cleanup_job
    assert "target changed before cancellation" in cleanup_job
    assert cleanup_job.index("if ! live_target_matches") < cleanup_job.index(
        'runs_url="repos/${TARGET_REPOSITORY}/actions/runs?status=${status}&per_page=100"'
    )
    assert cleanup_job.rindex("if ! live_target_matches") < cleanup_job.index(
        'gh api --method POST "repos/${TARGET_REPOSITORY}/actions/runs/${run_id}/cancel"'
    )
    assert "actions: write" in cleanup_job
    assert "pull-requests: read" in cleanup_job
    assert "actions/checkout" not in cleanup_job
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


def test_strix_cleanup_uses_pr_metadata_when_custom_title_is_absent() -> None:
    """Required-workflow runs retain exact PR/head cleanup without run-name rendering."""
    jq = shutil.which("jq")
    if jq is None:
        pytest.skip("jq is required to execute the production cleanup selector")
    workflow = workflow_text("strix.yml")
    marker = '--arg action "$PR_ACTION" --arg repo "$TARGET_REPOSITORY" --arg current "$CURRENT_RUN_ID" \'\n'
    start = workflow.index(marker) + len(marker)
    end = workflow.index('\n              \' <<<"$runs_json"', start)
    runs = {
        "workflow_runs": [
            {"id": 1, "name": "Strix Security Scan", "event": "pull_request_target", "pull_requests": [{"number": 7, "head": {"sha": "old"}}]},
            {"id": 2, "name": "Strix Security Scan", "event": "pull_request_target", "pull_requests": [{"number": 7, "head": {"sha": "current"}}]},
            {"id": 3, "name": "Strix Security Scan", "event": "pull_request_target", "pull_requests": [{"number": 7}]},
            {"id": 4, "name": "Strix Security Scan", "event": "pull_request_target", "display_title": "Strix Security Scan owner/repo#7@old", "pull_requests": [{"number": 7, "head": {"sha": "current"}}]},
            {"id": 5, "name": "Strix Security Scan", "event": "pull_request_target", "pull_requests": [{"number": 8, "head": {"sha": "old"}}]},
        ]
    }
    result = subprocess.run(
        [jq, "-r", "--arg", "pr", "7", "--arg", "head_sha", "current", "--arg", "action", "synchronize", "--arg", "repo", "owner/repo", "--arg", "current", "99", workflow[start:end]],
        input=json.dumps(runs),
        text=True,
        capture_output=True,
        check=True,
    )
    assert result.stdout.splitlines() == ["1"]


def _run_strix_cleanup(
    tmp_path: Path, pull_states: list[dict[str, object]], *, action: str = "synchronize"
) -> str:
    """Execute the production cleanup step against a stateful fake ``gh``."""
    jq = shutil.which("jq")
    if jq is None:
        pytest.skip("jq is required to execute the production cleanup")
    step = workflow_step(
        workflow_text("strix.yml"),
        "Cancel queued and running scans for superseded or inactive pull requests",
    )
    run_block = step.split("        run: |\n", 1)[1].split("\n  strix:", 1)[0]
    script = textwrap.dedent(run_block)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    calls = tmp_path / "calls"
    pulls = tmp_path / "pulls"
    pulls.write_text(
        "\n".join(json.dumps(state) for state in pull_states) + "\n",
        encoding="utf-8",
    )
    fake_gh = fake_bin / "gh"
    fake_gh.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >>"$FAKE_CALLS"
if [[ "$*" == *"/pulls/7"* ]]; then
  count_file="${FAKE_PULLS}.count"
  count=0
  [[ ! -f "$count_file" ]] || count="$(cat "$count_file")"
  count=$((count + 1))
  printf '%s' "$count" >"$count_file"
  sed -n "${count}p" "$FAKE_PULLS"
  exit 0
fi
if [[ "$*" == *"actions/runs?status=queued"* ]]; then
  printf '%s\n' '{"workflow_runs":[{"id":100,"name":"Strix Security Scan","event":"pull_request_target","pull_requests":[{"number":7,"head":{"sha":"old"}}]}]}'
  exit 0
fi
if [[ "$*" == *"actions/runs?status="* ]]; then
  printf '%s\n' '{"workflow_runs":[]}'
  exit 0
fi
exit 0
""",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "FAKE_CALLS": str(calls),
        "FAKE_PULLS": str(pulls),
        "TARGET_REPOSITORY": "owner/repo",
        "TARGET_PR_NUMBER": "7",
        "TARGET_PR_HEAD_SHA": "current",
        "PR_ACTION": action,
        "CURRENT_RUN_ID": "999",
    }
    subprocess.run(["bash", "-c", script], env=env, check=True, capture_output=True, text=True)
    return calls.read_text(encoding="utf-8")


def test_old_strix_cleanup_never_lists_or_cancels_after_live_head_advanced(
    tmp_path: Path,
) -> None:
    """A late old synchronize job must stop before selecting current runs."""
    calls = _run_strix_cleanup(
        tmp_path, [{"state": "open", "head": {"sha": "newer"}}] * 5
    )

    assert "actions/runs?status=" not in calls
    assert "/cancel" not in calls
    assert "/force-cancel" not in calls


def test_strix_cleanup_revalidates_after_selection_before_cancellation(
    tmp_path: Path,
) -> None:
    """A head advance after selection must prevent the pending mutation."""
    calls = _run_strix_cleanup(
        tmp_path,
        [
            {"state": "open", "draft": False, "head": {"sha": "current"}},
            {"state": "open", "draft": False, "head": {"sha": "newer"}},
        ]
        + [{"state": "open", "draft": False, "head": {"sha": "newer"}}] * 4,
    )

    assert "actions/runs?status=queued" in calls
    assert "/actions/runs/100/cancel" not in calls
    assert "/actions/runs/100/force-cancel" not in calls


def test_strix_draft_transition_cancels_current_scan(tmp_path: Path) -> None:
    """A verified Draft transition retires the current expensive Strix run."""
    calls = _run_strix_cleanup(
        tmp_path,
        [{"state": "open", "draft": True, "head": {"sha": "current"}}] * 6,
        action="converted_to_draft",
    )

    assert "/actions/runs/100/cancel" in calls


def test_pull_request_close_events_cancel_superseded_runs_without_heavy_jobs() -> None:
    """Close events should cancel old runs without starting expensive jobs."""
    workflows = (
        "codeql-pr.yml",
        "noema-review.yml",
        "pr-review-merge-scheduler.yml",
        "python-security.yml",
        "sast-semgrep.yml",
        "security-scan.yml",
        "strix.yml",
    )

    for filename in workflows:
        workflow = workflow_text(filename)

        assert "closed" in workflow
        if filename == "strix.yml":
            assert "cancel-superseded-pr-runs:" in workflow
            assert "Cancel queued and running scans for superseded or inactive pull requests" in workflow
            assert (
                "secrets.PR_REVIEW_MERGE_TOKEN || secrets.OPENCODE_APPROVE_TOKEN "
                "|| github.token"
            ) in workflow
            assert "DISPATCH_REPOSITORY" not in workflow
            assert "TARGET_PR_HEAD_SHA" in workflow
            assert 'select(.event == "pull_request_target")' in workflow
            assert 'select(.event == "repository_dispatch")' not in workflow
            assert "(.pull_requests // [])" in workflow
            assert ".head.sha // \"\"" in workflow
            assert "leaving runs unchanged" in workflow
            assert (
                "for active_status in queued in_progress requested waiting pending"
                in workflow
            )
            cleanup_job = workflow.split("  cancel-superseded-pr-runs:", 1)[1].split(
                "  strix:", 1
            )[0]
        elif filename == "noema-review.yml":
            assert "cancel-closed-pr-runs:" in workflow
            assert "Cancel queued and running Noema reviews for the inactive pull request" in workflow
            assert "leaving runs unchanged" in workflow
            cleanup_job = workflow.split("  cancel-closed-pr-runs:", 1)[1].split(
                "  noema-review:", 1
            )[0]
            assert "actions: write" in cleanup_job
            assert "actions/checkout" not in cleanup_job
            assert "cleanup skipped" not in cleanup_job
        elif filename in {
            "codeql-pr.yml",
            "pr-review-merge-scheduler.yml",
            "python-security.yml",
            "sast-semgrep.yml",
            "security-scan.yml",
        }:
            assert "cancel-closed-pr-runs:" not in workflow
            concurrency_contract = workflow.split("concurrency:", 1)[1].split(
                "permissions:", 1
            )[0]
            assert "github.event.pull_request.number" in concurrency_contract
            assert "github.event.pull_request.head.sha" not in concurrency_contract
            assert "cancel-in-progress:" in concurrency_contract
        else:
            raise AssertionError(f"unclassified close-event workflow: {filename}")
        assert "github.event.action != 'closed'" in workflow
        if filename in {"noema-review.yml", "strix.yml"}:
            assert "github.event.action != 'converted_to_draft'" in workflow

    opencode_bootstrap = workflow_text("opencode-review.yml")
    assert "types: [opened, synchronize, reopened, ready_for_review, converted_to_draft, closed]" in (
        opencode_bootstrap
    )
    assert "actions/checkout" not in opencode_bootstrap
    assert "${{ secrets." not in opencode_bootstrap

    strix_workflow = workflow_text("strix.yml")
    # Strix admits the live head before same-PR cancellation while cleanup stays
    # outside that queue so synchronize and close events can retire old work.
    assert "admit-current-head:" in strix_workflow
    assert "skipping stale evidence" in strix_workflow
    assert "cancel-in-progress: true" in strix_workflow


def test_merge_scheduler_owns_empty_pr_cleanup_without_checkout() -> None:
    """Keep empty-PR cleanup in the existing metadata-only scheduler job."""
    workflow = workflow_text("pr-review-merge-scheduler.yml")
    scheduler = workflow_step(workflow, "Inspect PR review and merge queue")

    assert not (REPO_ROOT / ".github/workflows/close-empty-pr.yml").exists()
    assert "pr_review_merge_scheduler.py" in scheduler
    assert "actions/checkout" not in workflow


def test_review_workflow_completions_do_not_spawn_scheduler_runs() -> None:
    """Required checks rely on GitHub auto-merge instead of a follow-up workflow."""
    workflow = workflow_text("pr-review-merge-scheduler.yml")
    assert "github.event.workflow_run" not in workflow


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


def test_noema_triggers_preserve_standalone_pull_request_review() -> None:
    """Noema reviews PRs independently of the other review workflows."""
    workflow = workflow_text("noema-review.yml")
    noema_job = workflow.split("\n  noema-review:\n", 1)[1]
    concurrency_contract = workflow.split("\nconcurrency:\n", 1)[1].split(
        "\npermissions:\n", 1
    )[0]

    assert "workflow_run:" not in concurrency_contract
    assert "github.event.workflow_run" not in workflow
    assert "github.event.pull_request.number" in concurrency_contract
    assert "github.event.client_payload.pr_number" in concurrency_contract
    assert "required-noema-review-${{" in concurrency_contract
    assert "github.event_name" not in concurrency_contract.split(
        "cancel-in-progress:", 1
    )[0]
    assert "cancel-in-progress: true" in concurrency_contract
    assert re.search(r"(?m)^concurrency:", workflow)
    assert not re.search(r"(?m)^    concurrency:", workflow)
    assert "needs.admit-current-head.outputs.admitted == 'true'" in noema_job
    assert '[ "${live_head_sha,,}" != "${EXPECTED_HEAD_SHA,,}" ]' in workflow


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
            "Prepare Noema model verdict",
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
    assert "NOEMA_REVIEW_ACTOR: ${{ steps.noema_github_app_token.outputs['app-slug']" in workflow
    assert "NOEMA_REVIEW_INSTALLATION_ID: ${{ steps.noema_github_app_token.outputs['installation-id'] }}" in workflow


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


def test_merge_scheduler_has_no_workflow_run_trigger() -> None:
    """Required-check completion must not create another Actions run."""
    workflow = workflow_text("pr-review-merge-scheduler.yml")

    assert "workflow_run:" not in workflow.split("workflow_call:", 1)[0]


def test_review_events_can_dispatch_after_threads_are_resolved() -> None:
    """Let the scheduler dispatch OpenCode when a review event clears its last blocker."""
    workflow = workflow_text("pr-review-merge-scheduler.yml")
    scan_job = workflow.split("  scan-pr-queue:", 1)[1]

    assert "github.event_name == 'pull_request_review'" in scan_job.split(
        "TRIGGER_REVIEWS:", 1
    )[1].splitlines()[0]


def test_scan_pr_queue_has_a_bounded_runtime() -> None:
    """Keep one repository-local scan below GitHub's platform timeout."""
    workflow = workflow_text("pr-review-merge-scheduler.yml")
    scan_job = workflow.split("  scan-pr-queue:", 1)[1]

    match = re.search(r"^    timeout-minutes: (\d+)$", scan_job, flags=re.MULTILINE)
    assert match is not None, "scan-pr-queue must declare a job-level timeout-minutes"
    scan_timeout = int(match.group(1))
    assert 1 <= scan_timeout <= 45
    assert scan_timeout < 60


def test_fix_scheduler_cancels_superseded_cron_runs() -> None:
    """Cancel stale scheduled repair runs before they duplicate mutation work."""
    workflow = workflow_text("pr-review-fix-scheduler.yml")

    assert "central-pr-review-fix-scheduler-" in workflow
    assert "cancel-in-progress: true" in workflow


def test_security_scan_fails_closed_when_dependency_review_is_unavailable() -> None:
    workflow = workflow_text("security-scan.yml")
    support_probe = workflow_step(workflow, "Check dependency review support")

    assert "id: dependency_review_support" in workflow
    assert "/dependency-graph/compare/${BASE_SHA}...${HEAD_SHA}" in workflow
    assert "repository: ${{ github.event.pull_request.head.repo.full_name }}" in workflow
    assert "ref: ${{ github.event.pull_request.head.sha }}" in workflow
    assert 'if [ "$curl_status" -ne 0 ] || [ "$http_status" != "200" ]; then' in workflow
    assert "--connect-timeout 10" in workflow
    assert "--max-time 30" in workflow
    assert "-o /dev/null" in workflow
    assert "curl_status=$?" in support_probe
    assert "set +e" in support_probe
    assert "set -e" in support_probe
    assert "|| true" not in support_probe
    assert "HTTP ${http_status}; curl exit ${curl_status}" in workflow
    assert "REPOSITORY_VISIBILITY: ${{ github.event.repository.visibility }}" in workflow
    assert 'case "${REPOSITORY_VISIBILITY:-}" in' in support_probe
    assert 'public | private | internal)' in support_probe
    assert 'repository_visibility="$REPOSITORY_VISIBILITY"' in support_probe
    assert 'repository_visibility="unknown"' in support_probe
    assert (
        'DEPENDENCY_REVIEW_SUPPORT repository=${REPOSITORY} visibility=${repository_visibility} '
        'base_sha=${BASE_SHA} head_sha=${HEAD_SHA} http_status=${http_status} '
        'curl_exit=${curl_status}'
        in support_probe
    )
    assert "supported=false" not in workflow
    assert "skipping dependency-review hard gate" not in workflow
    assert (
        "steps.dependency_review_support.outputs.supported == 'true'" in workflow
    )
    dependency_review = workflow_step(workflow, "Dependency review")
    assert "comment-summary-in-pr: never" in dependency_review
    assert "comment-summary-in-pr: on-failure" not in dependency_review


def test_security_scan_binds_every_scan_to_immutable_pr_revisions() -> None:
    """Reject synthetic-merge evidence for head and dual-revision security scans."""
    workflow = workflow_text("security-scan.yml")

    for step_name, expected_sha, rev_parse in (
        (
            "Verify OSV base checkout",
            "github.event.pull_request.base.sha",
            'git -C source rev-parse HEAD',
        ),
        (
            "Verify OSV head checkout",
            "github.event.pull_request.head.sha",
            'git -C source rev-parse HEAD',
        ),
        (
            "Verify Dependency Review head checkout",
            "github.event.pull_request.head.sha",
            'git rev-parse HEAD',
        ),
        (
            "Verify Trivy head checkout",
            "github.event.pull_request.head.sha",
            'git rev-parse HEAD',
        ),
        (
            "Verify Scorecard head checkout",
            "github.event.pull_request.head.sha",
            'git rev-parse HEAD',
        ),
    ):
        step = workflow_step(workflow, step_name)
        assert f"EXPECTED_CHECKOUT_SHA: ${{{{ {expected_sha} }}}}" in step
        assert f'actual_sha="$({rev_parse})"' in step
        assert 'if [ "$actual_sha" != "$EXPECTED_CHECKOUT_SHA" ]; then' in step
        assert "exit 1" in step

    for checkout_name in (
        "Checkout exact dependency-review head",
        "Checkout exact Trivy head",
        "Checkout exact Scorecard head",
    ):
        checkout = workflow_step(workflow, checkout_name)
        assert (
            "repository: ${{ github.event.pull_request.head.repo.full_name }}"
            in checkout
        )
        assert "ref: ${{ github.event.pull_request.head.sha }}" in checkout
        assert "persist-credentials: false" in checkout

    dependency_review = workflow_step(workflow, "Dependency review")
    assert "base-ref: ${{ github.event.pull_request.base.sha }}" in dependency_review
    assert "head-ref: ${{ github.event.pull_request.head.sha }}" in dependency_review

    for upload_name in (
        "Upload OSV SARIF to code scanning",
        "Upload Trivy SARIF to code scanning",
        "Upload Scorecard SARIF to code scanning",
    ):
        upload = workflow_step(workflow, upload_name)
        assert (
            "ref: refs/pull/${{ github.event.pull_request.number }}/head" in upload
        )
        assert "sha: ${{ github.event.pull_request.head.sha }}" in upload


def test_dependency_review_transport_failure_cannot_hide_behind_http_200(
    tmp_path: Path,
) -> None:
    """A failed curl transport must not make HTTP 200 acceptable evidence."""

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_curl = fake_bin / "curl"
    fake_curl.write_text(
        "#!/usr/bin/env bash\nprintf '200'\nexit 18\n",
        encoding="utf-8",
    )
    fake_curl.chmod(0o755)
    github_output = tmp_path / "github-output"
    script = textwrap.dedent(
        workflow_step(
            workflow_text("security-scan.yml"),
            "Check dependency review support",
        ).split("        run: |\n", 1)[1]
    )

    result = subprocess.run(
        ["bash", "-c", script],
        env={
            **os.environ,
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
            "GITHUB_API_URL": "https://api.example.invalid",
            "GITHUB_OUTPUT": str(github_output),
            "GH_TOKEN": "synthetic-read-token",
            "BASE_SHA": "a" * 40,
            "HEAD_SHA": "b" * 40,
            "REPOSITORY": "ContextualWisdomLab/.github",
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "HTTP 200; curl exit 18" in result.stdout
    assert not github_output.exists()


def test_security_scan_preserves_base_output_across_cross_fork_checkout() -> None:
    """Limit cross-fork replacement to a child checkout directory."""
    workflow = workflow_text("security-scan.yml")

    assert workflow.count("--allow-no-lockfiles") == 4
    assert workflow.count("path: source") == 2
    assert workflow.count("--output=old-results.json") == 2
    assert workflow.count("--output=new-results.json") == 2
    assert workflow.count("source/") == 4
    assert "clean: false" not in workflow
    assert "test -s old-results.json" in workflow
    assert "test -s new-results.json" in workflow


def test_secret_scan_push_limits_gitleaks_to_current_branch_history() -> None:
    """Limit push secret scanning to the current branch history."""
    workflow = workflow_text("secret-scan.yml")

    assert "CURRENT_SHA: ${{ github.sha }}" in workflow
    assert "pull_request:" not in workflow.split("concurrency:", 1)[0]
    assert "BASE_SHA:" not in workflow
    assert "HEAD_SHA:" not in workflow
    assert 'log_opts="${CURRENT_SHA}"' in workflow
    assert '--log-opts="${log_opts}"' in workflow
    assert "unrelated remote refs are excluded" in workflow


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
    assert "steps.osv_base.outcome == 'failure'" in workflow
    assert "steps.osv_head.outcome == 'failure'" in workflow
    assert "Retry base OSV without transitive resolution" in workflow
    assert "Retry head OSV without transitive resolution" in workflow
    assert workflow.count("timeout-minutes: 8") == 2
    assert workflow.count("timeout-minutes: 4") == 2
    assert workflow.count("\n            --no-resolve\n") == 4
    assert workflow.count("failed or timed out before reporter output was trusted") == 2
    assert (
        "Direct manifest and lockfile vulnerability evidence remains enforced"
        in workflow
    )
    assert (
        "external transitive registry resolution is intentionally avoided" in workflow
    )
    assert (
        "Retry base OSV without transitive resolution\n        if: steps.osv_base.outcome == 'failure'\n        continue-on-error: true"
        in workflow
    )
    assert (
        "Retry head OSV without transitive resolution\n        if: steps.osv_head.outcome == 'failure'\n        continue-on-error: true"
        in workflow
    )
    assert "--output=old-results.json" in workflow
    assert "--output=new-results.json" in workflow
    assert "Print OSV findings being compared" in workflow
    assert "OSV {label} scan produced {len(findings)} finding(s)" in workflow


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
    assert "STRIX_FAIL_ON_MIN_SEVERITY" not in workflow
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
    workflow = workflow_text("security-scan.yml")

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
