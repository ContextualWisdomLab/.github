import json
import subprocess
import sys
import textwrap
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def workflow_text(name: str) -> str:
    return (REPO_ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")


def test_merge_scheduler_dispatches_one_review_by_default() -> None:
    workflow = workflow_text("pr-review-merge-scheduler.yml")

    assert workflow.count('default: "1"') >= 2
    assert "vars.REVIEW_DISPATCH_LIMIT || '1'" in workflow
    assert "SCHEDULER_ALLOW_CROSS_REPO_WORKFLOW_DISPATCH" in workflow
    assert "secrets.PR_REVIEW_MERGE_TOKEN != '' || secrets.OPENCODE_APPROVE_TOKEN != ''" in workflow


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


def test_strix_cancels_superseded_pr_head_security_evidence() -> None:
    workflow = workflow_text("strix.yml")
    concurrency_contract = workflow.split("permissions:", 1)[0]

    assert "concurrency:" in workflow
    assert "github.event.inputs.target_repository" in concurrency_contract
    assert "github.event.pull_request.base.repo.full_name" in concurrency_contract
    assert "github.repository" in concurrency_contract
    assert (
        "strix-${{ github.event.inputs.target_repository || "
        "github.event.pull_request.base.repo.full_name || github.repository }}"
    ) in concurrency_contract
    assert "format('pr-{0}', github.event.pull_request.number)" in concurrency_contract
    assert "github.event.inputs.pr_number != '' && format('pr-{0}'," in workflow
    assert "format('pr-{0}-{1}'" not in concurrency_contract
    assert "github.event.pull_request.head.sha" not in concurrency_contract
    assert "github.event.inputs.pr_head_sha" not in concurrency_contract
    assert "cancel-in-progress: true" in workflow
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


def test_cancelled_review_workflow_runs_do_not_spawn_more_queue_work() -> None:
    for filename in ("noema-review.yml", "pr-review-merge-scheduler.yml"):
        workflow = workflow_text(filename)

        assert "github.event.workflow_run.conclusion != 'cancelled'" in workflow


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


def test_unassociated_review_workflow_runs_do_not_scan_the_whole_pr_queue() -> None:
    workflow = workflow_text("pr-review-merge-scheduler.yml")

    assert "github.event.workflow_run.pull_requests[0].number" in workflow


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

    assert "id: osv_base" in workflow
    assert "id: osv_head" in workflow
    assert "steps.osv_base.outcome == 'failure'" in workflow
    assert "steps.osv_head.outcome == 'failure'" in workflow
    assert "Retry base OSV without transitive resolution" in workflow
    assert "Retry head OSV without transitive resolution" in workflow
    assert workflow.count("timeout-minutes: 8") == 2
    assert workflow.count("timeout-minutes: 4") == 2
    assert workflow.count("\n            --no-resolve\n") == 2
    assert workflow.count("Maven Central 429") == 2
    assert workflow.count("failed or timed out before reporter output was trusted") == 2
    assert "Direct manifest and lockfile vulnerability evidence remains enforced" in workflow
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


def test_security_scan_osv_upload_uses_default_analysis_category() -> None:
    workflow = workflow_text("security-scan.yml")
    step = "      - name: Upload OSV SARIF to code scanning\n"
    start = workflow.index(step)
    upload_step = workflow[start : workflow.index("\n      - name:", start + len(step))]

    assert "github/codeql-action/upload-sarif" in upload_step
    assert "sarif_file: results.sarif" in upload_step
    assert "ref: refs/pull/${{ github.event.pull_request.number }}/merge" in upload_step
    assert "sha: ${{ github.sha }}" in upload_step
    assert "category:" not in upload_step


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
    assert "code owner review" in runbook
    assert "review thread resolution" in runbook
    assert "latest head commit" in runbook
    assert "cancel superseded runs" in runbook
    assert "Every central workflow failure must print the actionable reason" in runbook
