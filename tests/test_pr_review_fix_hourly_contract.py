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
_CONSOLIDATED_CALLER = Path(".github/workflows/hourly-review-repair.yml")
_CONTRACT_WORKFLOW = Path(".github/workflows/agent-review-runtime-quality-ci.yml")
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


def test_clearfolio_caller_runs_once_each_day() -> None:
    """Clearfolio receives one bounded daily missed-event recovery.

    The consolidated caller resolves per-repository parameters through a
    ``github.event.schedule`` lookup table (see
    ``docs/doctoring/hourly-review-repair-single-file-consolidation.md``)
    rather than flat ``key: value`` lines, so Clearfolio's values are read
    from its JSON literal in that table instead of a bare substring.
    """
    text = _read(_CONSOLIDATED_CALLER)

    assert 'cron: "23 7 * * *"' in text
    assert "uses: ./.github/workflows/pr-review-fix-scheduler.yml" in text
    assert '"target_repository":"ContextualWisdomLab/clearfolio"' in text
    assert '"base_branch":"main"' in text
    assert 'max_dispatches: "1"' in text
    assert '"retry_hours":"1"' in text
    assert "COPILOT_GITHUB_TOKEN" not in text
    assert "NVIDIA_NIM_API_KEY" not in text


def test_clearfolio_caller_keeps_github_token_read_only() -> None:
    """The hourly caller delegates with explicit secrets and no token elevation.

    The former dedicated Clearfolio file was the sole one of the 18 original
    callers that omitted a job-level ``permissions:`` override (it fell back
    to the workflow-level ``contents: read`` only, silently withholding
    ``id-token: write`` from the reusable scheduler for Clearfolio alone --
    see the consolidation doctoring record). The consolidated file grants
    the same ``contents: read`` / ``id-token: write`` job permissions to
    every matrix target uniformly, matching the other 17 repositories and
    closing that latent gap; this test now checks that the grant stays
    narrow (no broader token permission is added) rather than absent.
    """
    text = _read(_CONSOLIDATED_CALLER)
    workflow_scope, jobs_scope = text.split("\njobs:\n", maxsplit=1)

    assert "\npermissions:\n  contents: read\n" in workflow_scope
    for permission in (
        "actions: write",
        "issues: write",
        "contents: write",
        "pull-requests: write",
        "statuses: write",
    ):
        assert permission not in text
    assert "\n    permissions:\n      contents: read\n      id-token: write\n" in jobs_scope


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
    caller = _read(_CONSOLIDATED_CALLER)

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

    # ALLOWED_DISPATCH_ACTOR is a comma-separated allowlist shared with the two
    # dispatch workflows; every listed identity passes when actor and sender
    # both equal it, whitespace around commas tolerated.
    allowlist = "github-actions[bot], opencode-agent[bot]"
    for identity in ("github-actions[bot]", "opencode-agent[bot]"):
        assert subprocess.run(
            ["bash"],
            input=shell,
            text=True,
            env={
                **base_env,
                "ALLOWED_DISPATCH_ACTOR": allowlist,
                "DISPATCH_ACTOR": identity,
                "DISPATCH_SENDER": identity,
            },
            check=False,
        ).returncode == 0

    for override in (
        {"DISPATCH_SENDER": "untrusted"},
        {"DISPATCH_ACTOR": "untrusted"},
        {"TARGET_REPOSITORY": "ContextualWisdomLab/unapproved"},
        {"ALLOWED_DISPATCH_ACTOR": ""},
        {"ALLOWED_TARGET_REPOSITORIES": ""},
        # A listed allowlist still rejects an unlisted identity.
        {
            "ALLOWED_DISPATCH_ACTOR": allowlist,
            "DISPATCH_ACTOR": "untrusted",
            "DISPATCH_SENDER": "untrusted",
        },
        # Actor and sender must be the SAME listed identity, not each some
        # listed identity.
        {
            "ALLOWED_DISPATCH_ACTOR": allowlist,
            "DISPATCH_ACTOR": "opencode-agent[bot]",
            "DISPATCH_SENDER": "github-actions[bot]",
        },
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
    caller = _read(_CONSOLIDATED_CALLER)

    dispatch_block = reusable.split("max_dispatches:", maxsplit=1)[1].split(
        "target_repository:", maxsplit=1
    )[0]
    assert 'default: "1"' in dispatch_block
    assert "cancel-in-progress: true" in reusable
    assert "separately dispatched per-PR OpenCode worker" in reusable
    assert "MAX_DISPATCHES" in reusable
    assert "cancel-in-progress: false" in caller


def test_product_recovery_admits_at_most_one_workflow_each_hour() -> None:
    """Native events own normal progress; recovery cron entries stay daily and spread."""
    caller = _read(_CONSOLIDATED_CALLER)
    cron_lines = [line.strip() for line in caller.splitlines() if "- cron:" in line]
    hours = [line.split()[3] for line in cron_lines]

    assert len(cron_lines) == 17
    assert all(" * * *" in line and "* * * *" not in line for line in cron_lines)
    assert len(hours) == len(set(hours))


def test_contract_workflow_tracks_the_product_caller() -> None:
    """Changes to the consolidated product caller always rerun the focused gate."""
    text = _read(_CONTRACT_WORKFLOW)

    assert text.count(".github/workflows/hourly-review-repair.yml") == 2


def test_contract_workflow_tracks_scheduler_implementation() -> None:
    """Scheduler source changes always rerun the focused contract gate."""
    text = _read(_CONTRACT_WORKFLOW)

    assert text.count("scripts/ci/pr_review_fix_scheduler.py") == 2


def test_contract_workflow_tracks_its_own_test_tooling_lock() -> None:
    """The lock the contract job installs from always reruns the gate.

    The job runs bare ``pytest -q``, which collects every test under
    ``tests/`` (not just the contract-scoped ones), so a change that drops a
    transitive dependency from this lock silently breaks collection unless
    the workflow reruns on that change too. Scoped to the ``on:`` trigger
    block specifically (not a whole-file substring count) so a step or
    comment that also mentions these filenames elsewhere in the job -- as
    the lock-freshness verification step below does -- cannot silently
    satisfy this assertion without the path actually being present in the
    trigger list. One occurrence each: this consolidated job has a single
    ``pull_request:`` trigger, not the separate ``pull_request:``/``push:``
    pair the pre-consolidation per-repository callers each had.
    """
    text = _read(_CONTRACT_WORKFLOW)
    trigger_block = text.split("\npermissions:", 1)[0]

    assert trigger_block.count("requirements-opencode-review-ci.txt") == 1
    assert trigger_block.count("requirements-opencode-review-ci-hashes.txt") == 1


def test_contract_workflow_verifies_its_pinned_requirements_are_locked() -> None:
    r"""A bumped exact pin without a regenerated lock must fail closed.

    Devin Review (`ContextualWisdomLab/.github#1661`) caught that this job
    installed only the existing hash lock with no check that it actually
    reflects `requirements-opencode-review-ci.txt`'s own pins -- a version
    bump committed without re-running the lock's own compile script would
    silently test against the stale, unreflected old version.

    A later Devin Review pass on the same PR caught two problems with that
    first check itself: a plain substring `grep -qF` could match a longer
    package name that happens to contain a shorter pinned one (e.g. a
    hypothetical `pytest==9.1.1` pin spuriously "found" inside an unrelated
    `not-pytest==9.1.1 \` lock entry), and it did not strip an inline
    `# comment` or `; marker` (both valid pip requirements-file syntax)
    before matching. Fixed with an exact whole-line match (`-x`) against the
    lock's literal `name==version \` rendering, after stripping any trailing
    comment/marker from the source line first.
    """
    text = _read(_CONTRACT_WORKFLOW)

    assert (
        "Verify exact-pinned test-tooling requirements are reflected in the hash lock"
        in text
    )
    assert 'grep -qxF -- "${pin} \\\\" requirements-opencode-review-ci-hashes.txt' in text
    assert 'pin="${line%%#*}"' in text
    assert 'pin="${pin%%;*}"' in text


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
    monkeypatch.setattr(scheduler, "live_head_matches", lambda _repo, _pr: True)
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
