import json
import shlex
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


def workflow_text(name: str) -> str:
    return (REPO_ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")


def test_merge_scheduler_dispatches_one_review_by_default() -> None:
    workflow = workflow_text("pr-review-merge-scheduler.yml")

    assert workflow.count('default: "1"') >= 2
    assert "vars.REVIEW_DISPATCH_LIMIT || '1'" in workflow
    assert "SCHEDULER_ALLOW_CROSS_REPO_WORKFLOW_DISPATCH" in workflow
    assert "secrets.PR_REVIEW_MERGE_TOKEN != '' || secrets.OPENCODE_APPROVE_TOKEN != ''" in workflow


def test_merge_scheduler_provides_same_repository_dispatch_credential() -> None:
    """Guard the runner-token dispatch credential for central review workflows.

    The OpenCode app installation has no Actions permission and no
    PR_REVIEW_MERGE_TOKEN / OPENCODE_APPROVE_TOKEN PAT is configured, so before
    this credential existed the org sweep deadlocked every PR needing current-head
    review evidence with "no cross-repository workflow-dispatch credential". The
    scheduler and the sweep both run inside ContextualWisdomLab/.github — the same
    repository the required workflows are dispatched on — so the runner's own
    github.token (actions: write) must be passed through SCHEDULER_DISPATCH_TOKEN
    in BOTH jobs; the scheduler only uses it when GITHUB_REPOSITORY equals the
    dispatch repository.
    """
    workflow = workflow_text("pr-review-merge-scheduler.yml")

    assert workflow.count("SCHEDULER_DISPATCH_TOKEN: ${{ github.token }}") == 2


def test_required_pull_request_workflows_cancel_superseded_runs() -> None:
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
        concurrency_contract = workflow.split("permissions:", 1)[0]

        assert "concurrency:" in workflow
        assert "github.event.pull_request.base.repo.full_name" in concurrency_contract
        assert "github.repository" in concurrency_contract
        assert "github.event.pull_request.number" in workflow
        assert "cancel-in-progress: true" in workflow
        if filename in {"close-empty-pr.yml", "opencode-review.yml", "security-scan.yml"}:
            assert "github.event_name == 'pull_request_target'" in concurrency_contract or (
                "github.event_name == 'pull_request'" in concurrency_contract
            )
        else:
            if filename in {"codeql-pr.yml", "osv-scanner-pr.yml", "scorecard-pr.yml"}:
                assert "github.event_name == 'pull_request'" in concurrency_contract
            else:
                assert "github.event_name == 'pull_request_target'" in concurrency_contract
        assert "github.event.pull_request.head.sha" not in concurrency_contract
        assert "format('pr-{0}-{1}'" not in concurrency_contract


def test_central_semgrep_logs_every_finding_and_distinguishes_engine_failure() -> None:
    workflow = workflow_text("sast-semgrep.yml")

    assert "Report every Semgrep finding in the job log" in workflow
    assert "--exclude='docs/research/**/standards'" in workflow
    assert "SEMGREP_FINDING_COUNT=" in workflow
    assert "SEMGREP_FINDING rule=" in workflow
    assert 'level=\\(.level // $levels[.ruleId] // "unknown")' in workflow
    assert 'path=\\($location.artifactLocation.uri // "unknown")' in workflow
    assert 'line=\\($location.region.startLine // 0)' in workflow
    assert "message=" in workflow
    assert "SEMGREP_ENGINE_FAILURE rc=" in workflow
    assert "semgrep_sarif.outputs.finding_count != '0'" in workflow
    assert 'if [ "${SEMGREP_FINDING_COUNT:-missing}" != "0" ]' in workflow
    assert "Every rule, path, line, and message is listed" in workflow
    assert "Semgrep engine/configuration failed with rc=${SEMGREP_RC}" in workflow


def test_strix_cancels_superseded_pr_head_security_evidence() -> None:
    workflow = workflow_text("strix.yml")
    concurrency_contract = workflow.split("permissions:", 1)[0]

    assert "concurrency:" in workflow
    assert "github.event.inputs.target_repository" in concurrency_contract
    assert "github.event.pull_request.base.repo.full_name" in concurrency_contract
    assert "github.repository" in concurrency_contract
    assert (
        "strix-${{ github.event_name }}-${{ github.event.inputs.target_repository || "
        "github.event.pull_request.base.repo.full_name || github.repository }}"
    ) in concurrency_contract
    assert "format('pr-{0}', github.event.pull_request.number)" in concurrency_contract
    assert "github.event.inputs.pr_number != '' && format('pr-{0}'," in workflow
    assert "format('pr-{0}-{1}'" not in concurrency_contract
    assert "github.event.pull_request.head.sha" not in concurrency_contract
    assert "github.event.inputs.pr_head_sha" not in concurrency_contract
    assert "cancel-in-progress: true" in workflow
    assert "manual workflow_dispatch evidence cannot cancel" in workflow
    assert "PR-number scope keeps the queue on the current HEAD" in workflow
    assert "refs/pull/<n>/head has already advanced before this queued run starts" in workflow


def test_pull_request_close_events_cancel_superseded_runs_without_heavy_jobs() -> None:
    workflows = (
        "close-empty-pr.yml",
        "codeql-pr.yml",
        "noema-review.yml",
        "opencode-review.yml",
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
        assert (
            'PR closed; this run only cancels older runs through workflow concurrency.'
            in workflow
        )
        assert "github.event.action != 'closed'" in workflow

    strix_workflow = workflow_text("strix.yml")
    assert "cancel-in-progress: true" in strix_workflow
    assert "PR-number scope keeps the queue on the current HEAD" in strix_workflow


def test_close_empty_pr_metadata_lookup_retries_and_fails_open() -> None:
    workflow = workflow_text("close-empty-pr.yml")

    assert "gh_api_json_with_retry()" in workflow
    assert "jq -e type" in workflow
    assert "did not return valid JSON; retrying" in workflow
    assert "did not return valid JSON after 4 attempts" in workflow
    assert "leaving it open because metadata could not be read" in workflow
    assert "exit 0" in workflow



def test_cancelled_review_workflow_runs_do_not_spawn_more_queue_work() -> None:
    for filename in ("noema-review.yml", "pr-review-merge-scheduler.yml"):
        workflow = workflow_text(filename)

        assert "github.event.workflow_run.conclusion != 'cancelled'" in workflow


def test_required_workflow_trusted_source_refs_are_not_input_controlled() -> None:
    for filename in ("opencode-review.yml", "noema-review.yml", "pr-review-merge-scheduler.yml"):
        workflow = workflow_text(filename)

        assert "canonical_ref:" not in workflow
        assert "INPUT_CANONICAL_REF" not in workflow
        assert "github.event.inputs.canonical_ref" not in workflow
        assert "inputs.canonical_ref" not in workflow
        assert "workflow_sha" in workflow
        assert "ref: ${{ steps.trusted_source.outputs.ref }}" not in workflow
        assert (
            "ref: ${{ github.workflow_sha }}" in workflow
            or "TRUSTED_SOURCE_REF: ${{ steps.trusted_source.outputs.ref }}" in workflow
        )
        assert "JOB_CONTEXT_JSON: ${{ toJSON(job) }}" in workflow
        assert "GITHUB_CONTEXT_JSON: ${{ toJSON(github) }}" in workflow


def test_noema_workflow_run_followup_cannot_cancel_required_pr_event_review() -> None:
    workflow = workflow_text("noema-review.yml")
    concurrency_contract = workflow.split("permissions:", 1)[0]

    assert "github.repository }}-${{ github.event_name }}-${{" in concurrency_contract
    assert "github.event_name == 'workflow_run'" in concurrency_contract
    assert "github.event_name == 'pull_request_target'" in concurrency_contract


def test_noema_review_skips_until_exchange_url_is_configured_then_fails_closed() -> None:
    workflow = workflow_text("noema-review.yml")

    assert "fail_unavailable()" in workflow
    assert "mark_unconfigured()" in workflow
    assert 'echo "::error::$message"' in workflow
    assert 'echo "::notice::$message"' in workflow
    assert "vars.NOEMA_TOKEN_EXCHANGE_URL || vars.NOEMA_EXCHANGE_URL || ''" in workflow
    assert (
        "Noema app token exchange unconfigured: NOEMA_TOKEN_EXCHANGE_URL or NOEMA_EXCHANGE_URL is not configured; "
        "Noema review skipped until the exchange service is deployed."
    ) in workflow
    assert "Noema app token exchange is not configured; review skipped until Noema is deployed." in workflow
    assert "Noema app token exchange unavailable: OIDC request environment is missing." in workflow
    assert "Noema app token exchange unavailable: OIDC token request did not complete." in workflow
    assert "Noema app token exchange unavailable: OIDC token response was empty." in workflow
    assert "Noema app token exchange unavailable: app token request did not complete." in workflow
    assert "Noema app token exchange unavailable: app token response was empty." in workflow
    assert "::error::Noema app token is unavailable; review cannot submit a verdict." in workflow
    assert "Noema app token is unavailable; review skipped." not in workflow


def test_noema_workflow_run_without_pull_request_skips_before_token_exchange() -> None:
    workflow = workflow_text("noema-review.yml")

    assert "Noema review skipped: no pull request number is associated with this event." in workflow
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
    assert "Noema reviewer using the NOEMA_REVIEW_TOKEN secret fallback identity." in workflow
    # The review step must prefer the PAT over the exchanged app token.
    assert (
        "GH_TOKEN: ${{ secrets.NOEMA_REVIEW_TOKEN || steps.noema_app_token.outputs.token }}"
        in workflow
    )
    # The unconfigured-exchange notice stays for the no-PAT, no-exchange-URL case.
    assert (
        "Noema app token exchange unconfigured: NOEMA_TOKEN_EXCHANGE_URL or "
        "NOEMA_EXCHANGE_URL is not configured" in workflow
    )


def test_noema_and_scheduler_trusted_checkouts_use_static_main() -> None:
    noema = workflow_text("noema-review.yml")
    scheduler = workflow_text("pr-review-merge-scheduler.yml")

    for workflow in (noema, scheduler):
        assert "workflow_sha" in workflow
        assert "workflow_repository" in workflow
        assert "Trusted" in workflow or "trusted" in workflow
        assert "Materialize trusted" in workflow
        assert "uses: actions/checkout" not in workflow
        assert "repos/ContextualWisdomLab/.github/tarball/${TRUSTED_SOURCE_REF}" in workflow
        assert "Trusted" in workflow and "source ref must resolve to the immutable workflow commit SHA" in workflow
        assert "repository: ContextualWisdomLab/.github" not in workflow
        assert "repository: ${{ steps.trusted_source.outputs.repository }}" not in workflow
        assert "TRUSTED_SOURCE_REF: ${{ steps.trusted_source.outputs.ref }}" in workflow
        assert "INPUT_CANONICAL_REF" not in workflow


def test_unassociated_review_workflow_runs_do_not_scan_the_whole_pr_queue() -> None:
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
    auto-updated/merged within ~15 minutes instead of idling for up to an hour.
    """
    workflow = workflow_text("pr-review-merge-scheduler.yml")

    assert "org-queue-sweep:" in workflow
    assert "- cron: \"*/15 * * * *\"" in workflow
    assert "github.repository == 'ContextualWisdomLab/.github'" in workflow
    assert "github.event.schedule == '*/15 * * * *'" in workflow
    assert "inputs.org_sweep == true" in workflow
    # The single-repository scan must not double-run on the sweep cron.
    assert "github.event.schedule != '*/15 * * * *'" in workflow
    assert "inputs.org_sweep != true" in workflow
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


def test_org_queue_sweep_manual_cadence_inputs_reach_the_sweep_job() -> None:
    """Manual full-sweep cadence must override repository variables and defaults."""
    workflow = workflow_text("pr-review-merge-scheduler.yml")

    assert (
        "ORG_SWEEP_REVIEW_DISPATCH_LIMIT: ${{ inputs.review_dispatch_limit || "
        "vars.ORG_SWEEP_REVIEW_DISPATCH_LIMIT || '1' }}"
    ) in workflow
    assert (
        "STALE_OPENCODE_MINUTES: ${{ inputs.stale_opencode_minutes || "
        "vars.STALE_OPENCODE_MINUTES || '90' }}"
    ) in workflow
    assert (
        "ORG_SWEEP_MAX_PRS: ${{ inputs.max_prs || vars.ORG_SWEEP_MAX_PRS || '1000' }}"
    ) in workflow
    assert "ORG_SWEEP_TRIGGER_REVIEWS: ${{ inputs.trigger_reviews == true }}" in workflow
    assert (
        "ORG_SWEEP_ENABLE_AUTO_MERGE: ${{ inputs.enable_auto_merge == true }}"
    ) in workflow
    assert "ORG_SWEEP_MERGE_MODE: ${{ inputs.merge_mode || 'direct_or_auto' }}" in workflow
    assert "ORG_SWEEP_UPDATE_BRANCHES: ${{ inputs.update_branches == true }}" in workflow
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
    payload = '{"workflow_runs":[]}\n{"message":"Resource not accessible by integration"}\n'

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
    workflow = workflow_text("pr-review-fix-scheduler.yml")

    assert "central-pr-review-fix-scheduler-" in workflow
    assert "cancel-in-progress: true" in workflow


def test_security_scan_skips_dependency_review_when_dependency_graph_is_unavailable() -> None:
    workflow = workflow_text("security-scan.yml")

    assert "id: dependency_review_support" in workflow
    assert "/dependency-graph/compare/${BASE_SHA}...${HEAD_SHA}" in workflow
    assert '"$status" = "403"' in workflow
    assert '"$status" = "404"' in workflow
    assert "steps.dependency_review_support.outputs.supported == 'true'" in workflow


def test_security_scan_allows_repositories_without_supported_lockfiles() -> None:
    workflow = workflow_text("security-scan.yml")

    assert workflow.count("--allow-no-lockfiles") == 4
    assert "--output=old-results.json" in workflow
    assert "--output=new-results.json" in workflow
    assert "test -s old-results.json" in workflow
    assert "test -s new-results.json" in workflow


def test_secret_scan_push_limits_gitleaks_to_current_branch_history() -> None:
    workflow = workflow_text("secret-scan.yml")

    assert 'CURRENT_SHA: ${{ github.sha }}' in workflow
    assert 'log_opts="${BASE_SHA}..${HEAD_SHA}"' in workflow
    assert 'log_opts="${CURRENT_SHA}"' in workflow
    assert '--log-opts="${log_opts}"' in workflow
    assert "unrelated remote refs are excluded" in workflow


def test_osv_pr_workflow_has_one_startup_safe_scan_args_block() -> None:
    workflow = workflow_text("osv-scanner-pr.yml")
    concurrency_contract = workflow.split("permissions:", 1)[0]

    assert "github.event_name == 'pull_request' && github.event.pull_request.base.repo.full_name" in concurrency_contract
    assert "github.event_name == 'pull_request' && github.event.pull_request.number" in concurrency_contract
    assert workflow.count("scan-args: |-") == 1
    assert "--no-resolve" in workflow
    assert "--maven-registry=https://maven-central.storage-download.googleapis.com/maven2" in workflow


def test_osv_scan_logs_and_retries_without_transitive_resolution_on_resolver_failure() -> None:
    workflow = workflow_text("security-scan.yml")

    assert "timeout-minutes: 25" in workflow
    assert "Explain OSV scan mode and timeout budget" in workflow
    assert "external transitive registry resolver stalls cannot hold the required-check queue indefinitely" in workflow
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
    assert "Direct manifest and lockfile vulnerability evidence remains enforced" in workflow
    assert "external transitive registry resolution is intentionally avoided" in workflow
    assert "Retry base OSV without transitive resolution\n        if: steps.osv_base.outcome == 'failure'\n        continue-on-error: true" in workflow
    assert "Retry head OSV without transitive resolution\n        if: steps.osv_head.outcome == 'failure'\n        continue-on-error: true" in workflow
    assert "--output=old-results.json" in workflow
    assert "--output=new-results.json" in workflow
    assert "Print OSV findings being compared" in workflow
    assert "OSV {label} scan produced {len(findings)} finding(s)" in workflow


def test_osv_sarif_upload_is_marked_comprehensive_after_clean_comparison(tmp_path: Path) -> None:
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
    workflow = workflow_text("security-scan.yml")
    step = "      - name: Upload OSV SARIF to code scanning\n"
    start = workflow.index(step)
    upload_step = workflow[start : workflow.index("\n      - name:", start + len(step))]

    assert "Checkout PR merge ref for OSV SARIF upload" not in workflow
    assert 'merge_ref="refs/pull/${PR_NUMBER}/merge"' not in workflow
    assert "commit_oid is not a merge commit" in upload_step
    assert "github/codeql-action/upload-sarif" in upload_step
    assert "sarif_file: results.sarif" in upload_step
    assert "ref: refs/pull/${{ github.event.pull_request.number }}/head" in upload_step
    assert "sha: ${{ github.event.pull_request.head.sha }}" in upload_step
    assert "category:" not in upload_step


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


def test_osv_findings_log_accepts_null_results_for_manifestless_repos(tmp_path: Path) -> None:
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
    workflow = workflow_text("opencode-review.yml")
    failed_check_evidence = (REPO_ROOT / "scripts/ci/collect_failed_check_evidence.sh").read_text(
        encoding="utf-8"
    )

    assert "skipping optional current-head Strix workflow-run lookup" in workflow
    assert "skipping optional manual Strix run lookup" in workflow
    assert "Optional workflow %s is not installed" in failed_check_evidence
    assert 'if target_workflow_available "strix.yml"; then' in failed_check_evidence


def test_strix_provider_outage_without_findings_is_neutralized() -> None:
    workflow = workflow_text("strix.yml")

    assert "RateLimitError|Too many requests" in workflow
    assert "exceeded your current quota" in workflow
    assert "billing details" in workflow
    assert "LLM warm-up failed" in workflow
    assert "zero_vulnerabilities_signal" not in workflow
    assert "(^|[^A-Za-z0-9_])severity[[:space:]]*:" in workflow
    assert "STRIX_FAIL_ON_MIN_SEVERITY: MEDIUM" in workflow
    assert "before producing a vulnerability report" in workflow
    assert "genuine findings still fail the check" in workflow
    assert '&& ! grep -Eiq "$reported_vulnerability_signal" "$strix_run_log"' in workflow


def test_pr_scorecard_sarif_delegates_sast_and_vulnerability_posture_to_hard_gates() -> None:
    """PR Scorecard SARIF should not duplicate CodeQL/OSV/Trivy hard gates."""
    for filename in ("scorecard-pr.yml", "security-scan.yml"):
        workflow = workflow_text(filename)

        assert 'PR_HARD_GATE_RULE_IDS = {"SASTID", "VulnerabilitiesID"}' in workflow
        assert 'PR_GOVERNANCE_RULE_IDS = {"FuzzingID"}' in workflow
        assert "PR_DELEGATED_RULE_IDS = PR_HARD_GATE_RULE_IDS | PR_GOVERNANCE_RULE_IDS" in workflow
        assert "Delegated " in workflow
        assert "CodeQL, OSV, Trivy, and dependency-review hard gates" in workflow
        assert "default-branch governance tracking" in workflow

    default_branch_scorecard = workflow_text("scorecard-analysis.yml")

    assert "PR_DELEGATED_RULE_IDS" not in default_branch_scorecard
    assert "FuzzingID" not in default_branch_scorecard
    assert "VulnerabilitiesID" not in default_branch_scorecard


def test_trivy_failure_log_prints_sarif_finding_details(tmp_path: Path) -> None:
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
                                            "artifactLocation": {"uri": "requirements.txt"},
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
