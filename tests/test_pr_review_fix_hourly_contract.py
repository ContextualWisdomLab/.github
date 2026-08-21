"""Static and behavioral contracts for the hourly PR review-repair scheduler."""

from __future__ import annotations

import json
import os
import subprocess
import textwrap
from pathlib import Path

from scripts.ci import pr_review_fix_scheduler as scheduler


_REUSABLE_WORKFLOW = Path(".github/workflows/pr-review-fix-scheduler.yml")
_AUTOFIX_WORKFLOW = Path(".github/workflows/pr-review-autofix.yml")
_CLEARFOLIO_CALLER = Path(".github/workflows/clearfolio-hourly-review-repair.yml")
_CONTRACT_WORKFLOW = Path(".github/workflows/hourly-nvidia-nim-review-repair.yml")
_AUTOMATION_GUIDE = Path("docs/automation/hourly-review-repair.md")


def _read(path: Path) -> str:
    """Return one canonical workflow or guide as UTF-8 text."""
    return path.read_text(encoding="utf-8")


def _current_head_change_request(body: str) -> dict[str, object]:
    """Build one same-repository exact-head OpenCode change request."""
    head_sha = "a" * 40
    return {
        "number": 7,
        "isDraft": False,
        "baseRefName": "main",
        "baseRefOid": "b" * 40,
        "headRefName": "feature",
        "headRefOid": head_sha,
        "headRepository": {"nameWithOwner": "owner/repo"},
        "mergeStateStatus": "CLEAN",
        "reviews": {
            "nodes": [
                {
                    "state": "CHANGES_REQUESTED",
                    "author": {"login": "opencode-agent"},
                    "commit": {"oid": head_sha},
                    "body": body,
                }
            ]
        },
        "reviewThreads": {"nodes": []},
    }


def test_clearfolio_caller_runs_once_each_hour() -> None:
    """Clearfolio receives the requested hourly bounded repair heartbeat."""
    text = _read(_CLEARFOLIO_CALLER)

    assert 'cron: "23 * * * *"' in text
    assert "uses: ./.github/workflows/pr-review-fix-scheduler.yml" in text
    assert "target_repository: ContextualWisdomLab/clearfolio" in text
    assert "base_branch: main" in text
    assert 'max_dispatches: "1"' in text
    assert 'retry_hours: "1"' in text
    assert "COPILOT_GITHUB_TOKEN" not in text
    assert "NVIDIA_NIM_API_KEY" not in text


def test_clearfolio_caller_keeps_github_token_read_only() -> None:
    """The hourly caller delegates with explicit secrets and only OIDC elevation."""
    text = _read(_CLEARFOLIO_CALLER)
    workflow_scope, jobs_scope = text.split("\njobs:\n", maxsplit=1)

    assert "\npermissions:\n  contents: read\n" in workflow_scope
    assert "\n    permissions:\n      contents: read\n      id-token: write\n" in jobs_scope
    for permission in (
        "actions: write",
        "issues: write",
        "contents: write",
        "pull-requests: write",
        "statuses: write",
    ):
        assert permission not in text
    assert "id-token: write" in text


def test_reusable_scheduler_has_no_product_specific_timer() -> None:
    """The shared scheduler stays modular while the caller owns product cadence."""
    text = _read(_REUSABLE_WORKFLOW)
    target_expression = (
        "github.event.client_payload.target_repository || "
        "inputs.target_repository || "
        "vars.PR_REVIEW_FIX_TARGET_REPOSITORY || "
        "github.repository"
    )

    assert "\n  schedule:\n" not in text
    assert text.count(target_expression) == 2
    assert "ContextualWisdomLab/clearfolio" not in text


def test_reusable_scheduler_declares_only_required_caller_secrets() -> None:
    """The caller forwards only established secrets; OIDC supplies the app fallback."""
    reusable = _read(_REUSABLE_WORKFLOW)
    caller = _read(_CLEARFOLIO_CALLER)

    assert "PR_REVIEW_MERGE_TOKEN:" in reusable
    assert "OPENCODE_APPROVE_TOKEN:" in reusable
    assert "PR_REVIEW_MERGE_TOKEN: ${{ secrets.PR_REVIEW_MERGE_TOKEN }}" in caller
    assert "OPENCODE_APPROVE_TOKEN: ${{ secrets.OPENCODE_APPROVE_TOKEN }}" in caller
    assert "secrets: inherit" not in caller
    assert "Exchange OpenCode app token for scheduler mutations" in reusable
    assert "OIDC_AUDIENCE: opencode-github-action" in reusable
    mutation_token_line = next(
        line.strip() for line in reusable.splitlines() if line.strip().startswith("GH_TOKEN:")
    )
    assert mutation_token_line == (
        "GH_TOKEN: ${{ secrets.PR_REVIEW_MERGE_TOKEN || "
        "secrets.OPENCODE_APPROVE_TOKEN || steps.scheduler_app_token.outputs.token }}"
    )
    assert "github.token" not in mutation_token_line
    assert (
        "MUTATION_CREDENTIAL_AVAILABLE: ${{ secrets.PR_REVIEW_MERGE_TOKEN != '' || "
        "secrets.OPENCODE_APPROVE_TOKEN != '' || "
        "steps.scheduler_app_token.outputs.available == 'true' }}"
        in reusable
    )
    assert 'if [ "$MUTATION_CREDENTIAL_AVAILABLE" != "true" ]; then' in reusable
    assert "github.token remains read-only and is never accepted as the mutation authority" in reusable


def test_scheduler_validates_dispatch_authority_before_credentials() -> None:
    """Untrusted dispatch identity and targets fail before token materialization."""
    workflow = _read(_REUSABLE_WORKFLOW)
    validation_name = "Validate scheduler target and dispatch authority"
    validation = workflow.index(validation_name)
    exchange = workflow.index("Exchange OpenCode app token for scheduler mutations")
    assert validation < exchange

    step = workflow.split(f"      - name: {validation_name}\n", 1)[1].split(
        "      - name: Exchange OpenCode app token for scheduler mutations\n", 1
    )[0]
    assert "DISPATCH_ACTOR: ${{ github.triggering_actor }}" in step
    assert "DISPATCH_SENDER: ${{ github.event.sender.login || '' }}" in step
    assert (
        "ALLOWED_DISPATCH_ACTOR: "
        "${{ vars.OPENCODE_REPOSITORY_DISPATCH_ACTOR }}" in step
    )
    assert (
        "ALLOWED_TARGET_REPOSITORIES: "
        "${{ vars.OPENCODE_REPOSITORY_DISPATCH_TARGETS }}" in step
    )

    shell = textwrap.dedent(step.split("        run: |\n", 1)[1])
    base_env = {
        **os.environ,
        "EVENT_NAME": "repository_dispatch",
        "DISPATCH_ACTOR": "github-actions[bot]",
        "DISPATCH_SENDER": "github-actions[bot]",
        "ALLOWED_DISPATCH_ACTOR": "github-actions[bot]",
        "ALLOWED_TARGET_REPOSITORIES": (
            "ContextualWisdomLab/clearfolio,ContextualWisdomLab/disksage"
        ),
        "TARGET_REPOSITORY": "ContextualWisdomLab/clearfolio",
    }
    assert subprocess.run(
        ["bash"], input=shell, text=True, env=base_env, check=False
    ).returncode == 0
    # Reusable workflows retain the caller event payload. The scheduled
    # product callers therefore arrive as `schedule`, not `workflow_call`.
    assert subprocess.run(
        ["bash"],
        input=shell,
        text=True,
        env={
            **base_env,
            "EVENT_NAME": "schedule",
            "DISPATCH_ACTOR": "",
            "DISPATCH_SENDER": "",
        },
        check=False,
    ).returncode == 0

    for override in (
        {"DISPATCH_SENDER": "untrusted"},
        {"DISPATCH_ACTOR": "untrusted"},
        {"TARGET_REPOSITORY": "ContextualWisdomLab/unapproved"},
        {"ALLOWED_DISPATCH_ACTOR": ""},
        {"ALLOWED_TARGET_REPOSITORIES": ""},
    ):
        assert subprocess.run(
            ["bash"],
            input=shell,
            text=True,
            env={**base_env, **override},
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).returncode != 0


def test_reusable_scheduler_keeps_workflow_token_read_only() -> None:
    """Repository dispatch never depends on write-capable workflow-token permissions."""
    text = _read(_REUSABLE_WORKFLOW)
    workflow_scope, jobs_scope = text.split("\njobs:\n", maxsplit=1)

    assert "\npermissions:\n  contents: read\n" in workflow_scope
    assert "\n  id-token: write\n" in workflow_scope
    assert "\n    permissions:\n" not in jobs_scope
    for permission in (
        "actions: write",
        "issues: write",
        "contents: write",
        "pull-requests: write",
        "statuses: write",
    ):
        assert permission not in text


def test_review_fix_scheduler_retries_same_head_after_one_hour() -> None:
    """A blocked head can be retried on the next hourly cycle, not a day later."""
    text = _read(_REUSABLE_WORKFLOW)

    retry_block = text.split("retry_hours:", maxsplit=1)[1].split(
        "autofix_workflow:", maxsplit=1
    )[0]
    assert 'default: "1"' in retry_block
    assert "inputs.retry_hours || '1'" in text
    assert "inputs.retry_hours || '24'" not in text


def test_review_fix_scheduler_remains_bounded_and_single_flight() -> None:
    """Higher cadence keeps one mutation and supersedes only a stale queue scan."""
    reusable = _read(_REUSABLE_WORKFLOW)
    caller = _read(_CLEARFOLIO_CALLER)

    dispatch_block = reusable.split("max_dispatches:", maxsplit=1)[1].split(
        "target_repository:", maxsplit=1
    )[0]
    assert 'default: "1"' in dispatch_block
    assert "cancel-in-progress: true" in reusable
    assert "separately dispatched per-PR OpenCode worker" in reusable
    assert "MAX_DISPATCHES" in reusable
    assert "cancel-in-progress: false" in caller


def test_contract_workflow_tracks_the_product_caller() -> None:
    """Changes to the active Clearfolio caller always rerun the focused gate."""
    text = _read(_CONTRACT_WORKFLOW)

    assert text.count(".github/workflows/clearfolio-hourly-review-repair.yml") == 2


def test_contract_workflow_tracks_scheduler_implementation() -> None:
    """Scheduler source changes always rerun the focused contract gate."""
    text = _read(_CONTRACT_WORKFLOW)

    assert text.count("scripts/ci/pr_review_fix_scheduler.py") == 2


def test_autofix_agent_performs_rca_before_selecting_a_remediation() -> None:
    """The writer must diagnose the exact-head cause before it edits the tree."""
    text = _read(_AUTOFIX_WORKFLOW)

    assert "Establish the root cause from exact current-head evidence before editing." in text
    assert "List the smallest plausible remediation candidates" in text
    assert "Do not call a remediation feasible merely because it sounds reasonable." in text


def test_autofix_agent_proves_remediation_feasibility_before_writing() -> None:
    """A candidate action is executable only inside the sealed authority boundary."""
    text = _read(_AUTOFIX_WORKFLOW)

    for requirement in (
        "current repository-writer authority",
        "sealed allowed paths",
        "credential and protected-setting requirements",
        "stack and dependency order",
        "focused test or exact-head check can verify the result",
        "actually changes the root cause rather than only restating the blocker",
    ):
        assert requirement in text
    assert "If no repository edit is feasible within this worker's authority" in text
    assert "leave the tree unchanged" in text


def test_hourly_loop_continues_productive_work_around_external_latency() -> None:
    """Pending external gates block merge, not unrelated bounded progress."""
    workflow = _read(_AUTOFIX_WORKFLOW)
    guide = _read(_AUTOMATION_GUIDE)

    sentence = (
        "Queued reviews or checks remain merge blockers, but their latency is not a reason "
        "to invent a code change or stop the broader scheduler from processing other eligible work."
    )
    assert sentence in workflow
    assert "RCA and remediation-feasibility gate" in guide
    assert "continue with the next eligible bounded PR or buyer-visible product gap" in guide


def test_failed_check_review_is_dispatched_to_rca_mode() -> None:
    """A source-backed failed-check blocker reaches the RCA worker instead of stopping."""
    pr = _current_head_change_request(
        "Failed check evidence shows coverage-evidence failed on the exact current head."
    )

    assert scheduler.needs_rca_repair(pr) == (
        True,
        ("current-head failed-check blocker requires RCA",),
    )


def test_external_review_wait_is_not_invented_into_a_code_repair() -> None:
    """Provider exhaustion and missing approval remain external waits, not patch prompts."""
    for body in (
        "OpenCode could not establish approval sufficiency because the model pool exhausted.",
        "Independent approval is still required for this exact head.",
    ):
        assert scheduler.needs_rca_repair(_current_head_change_request(body)) == (
            False,
            (),
        )


def test_rca_dispatch_carries_an_explicit_worker_mode(monkeypatch) -> None:
    """The exact-head dispatch distinguishes failed-check RCA from ordinary review repair."""
    captured: dict[str, str | None] = {}

    def fake_run(args: list[str], *, stdin: str | None = None) -> str:
        captured["stdin"] = stdin
        return ""

    monkeypatch.setattr(scheduler, "run", fake_run)
    pr = _current_head_change_request("Failed check evidence reports Strix failed.")

    scheduler.dispatch_autofix(
        "owner/repo",
        pr,
        workflow="pr-review-autofix.yml",
        workflow_repository="ContextualWisdomLab/.github",
        dry_run=False,
        repair_mode="rca",
    )

    payload = json.loads(captured["stdin"] or "{}")
    assert payload["client_payload"]["repair_mode"] == "rca"


def test_rca_worker_collects_failed_check_evidence_before_editing() -> None:
    """RCA mode receives redacted logs and a separately sealed edit scope."""
    workflow = _read(_AUTOFIX_WORKFLOW)

    assert "REPAIR_MODE" in workflow
    assert "collect_failed_check_evidence.sh" in workflow
    assert "pr-review-autofix-failed-check-evidence.md" in workflow
    assert "--repair-mode \"$REPAIR_MODE\"" in workflow
    assert "--failed-check-evidence" in workflow
