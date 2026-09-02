"""Materialize PR #1706 one-shot admission and event-driven wake repair.

Temporary source-fix helper. The successful publication workflow deletes this
file and every other PR #1706 source-fix artifact from the final tree.
"""

from __future__ import annotations

from pathlib import Path


REQUIRED = Path(".github/workflows/opencode-review.yml")
DISPATCH = Path(".github/workflows/opencode-review-dispatch.yml")
SCHEDULER = Path(".github/workflows/pr-review-merge-scheduler.yml")
ACCEPTANCE = Path("tests/test_opencode_required_verdict_runner_release.py")
SELF = Path("tests/test_opencode_poll_self_retirement.py")
EVENT = Path("tests/test_opencode_event_driven_required_wake.py")
REGRESSION = Path("tests/test_opencode_required_verdict_regression.py")
ARCHITECTURE = Path("ARCHITECTURE.md")
DOCTORING = Path("docs/doctoring/opencode-stale-poll-self-retirement.md")
BASELINE = Path("docs/product-technical-gap-baseline.md")
CHANGELOG = Path("CHANGELOG.md")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    """Replace one exact fragment and fail closed on concurrent drift."""
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label} drifted: expected one exact match, found {count}")
    return text.replace(old, new, 1)


# The prior deterministic stage converts verdict admission to one authoritative
# PR read plus one complete Reviews read. Remove its temporary transport budget:
# repository policy must not turn GitHub I/O latency into review semantics.
required = REQUIRED.read_text(encoding="utf-8")
start = "      - name: Fail closed without a current-head OpenCode verdict\n"
end = "\n  cancel-superseded-opencode-review-runs:\n"
if required.count(start) != 1 or required.count(end) != 1:
    raise SystemExit("Required OpenCode verdict step boundaries drifted")
before, rest = required.split(start, 1)
step, after = rest.split(end, 1)
step = step.replace("timeout 30s gh api ", "gh api ")
if any(token in step for token in ("timeout ", "while :; do", "sleep ")):
    raise SystemExit("Required verdict admission still contains local wait allocation")
REQUIRED.write_text(before + start + step + end + after, encoding="utf-8")


# The formal-review receipt is already authenticated and exact-head validated by
# the preceding dispatch steps. Reconcile that new event against the immutable
# required run exactly once. If the run has not failed yet, do nothing here: the
# workflow_run completion reconciliation below owns the opposite event ordering.
dispatch = DISPATCH.read_text(encoding="utf-8")
wake_start = "      - name: Wake exact-head required OpenCode workflow\n"
wake_end = "\n      - name: Publish repository_dispatch OpenCode status\n"
if dispatch.count(wake_start) != 1 or dispatch.count(wake_end) != 1:
    raise SystemExit("OpenCode dispatch wake boundaries drifted")
d_before, d_rest = dispatch.split(wake_start, 1)
_old_wake, d_after = d_rest.split(wake_end, 1)
wake = r'''      - name: Wake exact-head required OpenCode workflow
        if: >-
          always()
          && github.event_name == 'repository_dispatch'
          && steps.formal_review_receipt.outcome == 'success'
          && needs.validate-pr-metadata.outputs.target_repository != ''
          && needs.validate-pr-metadata.outputs.pr_number != ''
          && needs.validate-pr-metadata.outputs.head_sha != ''
          && github.event.client_payload.required_run_id != ''
        env:
          GH_TOKEN: ${{ needs.validate-pr-metadata.outputs.target_repository == github.repository && github.token || secrets.PR_REVIEW_MERGE_TOKEN || secrets.OPENCODE_APPROVE_TOKEN }}
          GH_REPOSITORY: ${{ needs.validate-pr-metadata.outputs.target_repository }}
          PR_NUMBER: ${{ needs.validate-pr-metadata.outputs.pr_number }}
          PR_HEAD_SHA: ${{ needs.validate-pr-metadata.outputs.head_sha }}
          REQUIRED_RUN_ID: ${{ github.event.client_payload.required_run_id }}
          WAKE_TOKEN_SOURCE: ${{ needs.validate-pr-metadata.outputs.target_repository == github.repository && 'github-token' || secrets.PR_REVIEW_MERGE_TOKEN != '' && 'PR_REVIEW_MERGE_TOKEN' || secrets.OPENCODE_APPROVE_TOKEN != '' && 'OPENCODE_APPROVE_TOKEN' || 'unavailable' }}
        run: |
          set -euo pipefail
          if [ -z "${GH_TOKEN:-}" ] || [ "$WAKE_TOKEN_SOURCE" = "unavailable" ]; then
            echo "::error::Actions-capable wake credential is unavailable. Native runs use github.token; sibling runs require PR_REVIEW_MERGE_TOKEN or OPENCODE_APPROVE_TOKEN."
            exit 1
          fi
          [[ "$REQUIRED_RUN_ID" =~ ^[1-9][0-9]*$ ]] || { echo "::error::Required OpenCode run id is missing or non-canonical."; exit 1; }
          [[ "$PR_NUMBER" =~ ^[1-9][0-9]*$ ]] || { echo "::error::Required OpenCode PR number is missing or non-canonical."; exit 1; }
          [[ "$PR_HEAD_SHA" =~ ^[0-9a-fA-F]{40}$ ]] || { echo "::error::Required OpenCode PR head SHA is missing or malformed."; exit 1; }
          if ! run="$(gh api "repos/${GH_REPOSITORY}/actions/runs/${REQUIRED_RUN_ID}")"; then
            echo "::error::Exact required-run lookup failed; no retry policy is invented."
            exit 1
          fi
          required_run="$(printf '%s\n' "$run" | jq -r --arg head "$PR_HEAD_SHA" --arg pr "$PR_NUMBER" --argjson run_id "$REQUIRED_RUN_ID" '
            select(.id == $run_id)
            | select(.event == "pull_request_target")
            | select(.path == ".github/workflows/opencode-review.yml")
            | select(any((.pull_requests // [])[]?; ((.number // 0) | tostring) == $pr and ((.head.sha // "") | ascii_downcase) == ($head | ascii_downcase)))
            | [(.id // ""), (.status // ""), (.conclusion // "")]
            | @tsv
            ')" || required_run=""
          if [ -z "$required_run" ]; then
            echo "::error::Referenced Required OpenCode Review run does not match the exact PR/head/workflow identity."
            exit 1
          fi
          IFS=$'\t' read -r required_run_id required_status required_conclusion <<<"$required_run"
          if [ "$required_status" = "completed" ] && [ "$required_conclusion" = "success" ]; then
            echo "Exact-PR/head Required OpenCode Review run ${required_run_id} already succeeded."
            exit 0
          fi
          if [ "$required_status" != "completed" ] || [ "$required_conclusion" != "failure" ]; then
            echo "Exact required run is not a completed failure; workflow_run completion reconciliation owns any later transition."
            exit 0
          fi
          if gh api -X POST "repos/${GH_REPOSITORY}/actions/runs/${required_run_id}/rerun-failed-jobs" >/dev/null; then
            echo "Re-ran failed jobs for exact-PR/head Required OpenCode Review run ${required_run_id} after formal exact-head evidence."
            exit 0
          fi
          if ! advanced="$(gh api "repos/${GH_REPOSITORY}/actions/runs/${required_run_id}")"; then
            echo "::error::Rerun mutation failed and exact-run readback is unavailable; failing closed."
            exit 1
          fi
          advanced_state="$(printf '%s\n' "$advanced" | jq -r '[.status // "", .conclusion // ""] | @tsv')"
          if [ "$advanced_state" != $'completed\tfailure' ]; then
            echo "Exact required run advanced concurrently; no duplicate rerun is needed."
            exit 0
          fi
          echo "::error::Exact required run remains failed after the rerun mutation failed."
          exit 1
'''
DISPATCH.write_text(d_before + wake + wake_end + d_after, encoding="utf-8")


# workflow_run/completed closes review-before-failure. This path independently
# revalidates live PR/head authority and requires review.submitted_at to be newer
# than run.run_started_at, preventing an old verdict from driving a rerun cycle.
scheduler = SCHEDULER.read_text(encoding="utf-8")
job_marker = "jobs:\n  scan-pr-queue:\n"
if "  reconcile-opencode-required-verdict:\n" not in scheduler:
    reconcile_job = r'''jobs:
  reconcile-opencode-required-verdict:
    name: reconcile-opencode-required-verdict
    if: >-
      github.event_name == 'workflow_run'
      && github.event.workflow_run.name == 'Required OpenCode Review'
      && github.event.workflow_run.conclusion == 'failure'
      && github.event.workflow_run.event == 'pull_request_target'
      && github.event.workflow_run.path == '.github/workflows/opencode-review.yml'
      && github.event.workflow_run.pull_requests[0].number
    runs-on: ubuntu-slim
    permissions:
      actions: write
      contents: read
      pull-requests: read
    env:
      GH_TOKEN: ${{ github.token }}
      PR_NUMBER: ${{ github.event.workflow_run.pull_requests[0].number }}
      PR_HEAD_SHA: ${{ github.event.workflow_run.pull_requests[0].head.sha }}
      REQUIRED_RUN_ID: ${{ github.event.workflow_run.id }}
      REQUIRED_RUN_STARTED_AT: ${{ github.event.workflow_run.run_started_at }}
    steps:
      - name: Reconcile newer formal review evidence with the completed required run
        shell: bash
        run: |
          set -euo pipefail
          [[ "$PR_NUMBER" =~ ^[1-9][0-9]*$ ]] || { echo "::error::workflow_run PR number is missing or non-canonical."; exit 1; }
          [[ "$PR_HEAD_SHA" =~ ^[0-9a-fA-F]{40}$ ]] || { echo "::error::workflow_run PR head is missing or malformed."; exit 1; }
          [[ "$REQUIRED_RUN_ID" =~ ^[1-9][0-9]*$ ]] || { echo "::error::workflow_run id is missing or non-canonical."; exit 1; }
          if [ -z "$REQUIRED_RUN_STARTED_AT" ]; then
            echo "::error::workflow_run start provenance is missing; failing closed."
            exit 1
          fi
          if ! live_pr="$(gh api "repos/${GITHUB_REPOSITORY}/pulls/${PR_NUMBER}")"; then
            echo "::error::Live PR read failed during event-driven Required OpenCode reconciliation; failing closed."
            exit 1
          fi
          live_head="$(printf '%s\n' "$live_pr" | jq -r '.head.sha // empty')"
          live_state="$(printf '%s\n' "$live_pr" | jq -r '.state // empty')"
          live_draft="$(printf '%s\n' "$live_pr" | jq -r 'if (.draft | type) == "boolean" then (.draft | tostring) else empty end')"
          if [ "$live_state" != "open" ] || [ "$live_draft" = "true" ] || [ "${live_head,,}" != "${PR_HEAD_SHA,,}" ]; then
            echo "Required run is no longer authoritative for an open ready exact-head PR; no wake mutation is allowed."
            exit 0
          fi
          if ! reviews="$(gh api --paginate "repos/${GITHUB_REPOSITORY}/pulls/${PR_NUMBER}/reviews")"; then
            echo "::error::Reviews API read failed during event-driven Required OpenCode reconciliation; failing closed."
            exit 1
          fi
          latest_review="$(printf '%s\n' "$reviews" | jq -r -s --arg sha "$PR_HEAD_SHA" '
            (add // [])
            | [.[]
                | select((.user.login // "" | ascii_downcase) as $user | $user == "opencode-agent" or $user == "opencode-agent[bot]")
                | select((.commit_id // "" | ascii_downcase) == ($sha | ascii_downcase))
                | select(.state == "APPROVED" or .state == "CHANGES_REQUESTED")
                | select((.body // "" | ascii_downcase | contains("deterministic current-head evidence")) | not)
                | select((.body // "" | ascii_downcase | contains("deterministic fallback approval")) | not)
                | select((.body // "" | ascii_downcase | contains("model-unavailable evidence fallback")) | not)
                | select((.body // "" | ascii_downcase | contains("did not emit a usable current-head control block")) | not)
                | select((.body // "" | ascii_downcase | contains("scope: `unsupported`")) | not)
                | select((.body // "" | ascii_downcase | contains("model-pool outcome: `unknown`")) | not)]
            | sort_by(.submitted_at // "", .id // 0)
            | (last // {})
            | [(.state // ""), (.submitted_at // "")]
            | @tsv
          ')"
          IFS=$'\t' read -r review_state review_submitted_at <<<"$latest_review"
          if [ -z "$review_state" ]; then
            echo "No formal exact-head OpenCode review exists yet; the later review receipt event owns reconciliation."
            exit 0
          fi
          if [ -z "$review_submitted_at" ]; then
            echo "::error::Formal exact-head review lacks submission provenance; failing closed."
            exit 1
          fi
          new_evidence="$(jq -nr --arg review "$review_submitted_at" --arg started "$REQUIRED_RUN_STARTED_AT" 'try (($review | fromdateiso8601) > ($started | fromdateiso8601)) catch false')"
          if [ "$new_evidence" != "true" ]; then
            echo "Formal review predates this run attempt; the failure is not attributable to missing newer review evidence."
            exit 0
          fi
          if gh api -X POST "repos/${GITHUB_REPOSITORY}/actions/runs/${REQUIRED_RUN_ID}/rerun-failed-jobs" >/dev/null; then
            echo "Re-ran failed jobs for Required OpenCode Review run ${REQUIRED_RUN_ID} after newer formal exact-head evidence."
            exit 0
          fi
          if ! advanced="$(gh api "repos/${GITHUB_REPOSITORY}/actions/runs/${REQUIRED_RUN_ID}")"; then
            echo "::error::Rerun mutation failed and exact-run readback is unavailable; failing closed."
            exit 1
          fi
          advanced_state="$(printf '%s\n' "$advanced" | jq -r '[.status // "", .conclusion // ""] | @tsv')"
          if [ "$advanced_state" != $'completed\tfailure' ]; then
            echo "Exact required run advanced concurrently; no duplicate rerun is needed."
            exit 0
          fi
          echo "::error::Exact required run remains failed after the rerun mutation failed."
          exit 1

  scan-pr-queue:
'''
    scheduler = replace_once(scheduler, job_marker, reconcile_job, "event reconciliation job")
SCHEDULER.write_text(scheduler, encoding="utf-8")


# Replace transitional tests with causal state-machine contracts. These tests
# deliberately avoid brittle indentation parsing and execute the relevant shell
# paths where useful.
ACCEPTANCE.write_text(r'''"""Regression coverage for one-shot Required OpenCode verdict admission."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REQUIRED = Path(".github/workflows/opencode-review.yml")
DISPATCH = Path(".github/workflows/opencode-review-dispatch.yml")
HEAD = "a" * 40


def _required_script() -> str:
    """Return the production exact-head verdict-admission shell body."""
    text = REQUIRED.read_text(encoding="utf-8")
    step = text.split("      - name: Fail closed without a current-head OpenCode verdict\n", 1)[1]
    return textwrap.dedent(step.split("        run: |\n", 1)[1].split("\n  cancel-superseded-opencode-review-runs:\n", 1)[0])


def _wake() -> str:
    """Return the production formal-receipt exact-run wake step."""
    text = DISPATCH.read_text(encoding="utf-8")
    return text.split("      - name: Wake exact-head required OpenCode workflow\n", 1)[1].split("\n      - name: Publish repository_dispatch OpenCode status\n", 1)[0]


def test_missing_verdict_releases_runner_without_local_wait_allocation() -> None:
    """Admission performs complete state reads once and never polls or sleeps."""
    step = _required_script()
    assert step.count('gh api "repos/${TARGET_REPOSITORY}/pulls/${PR_NUMBER}"') == 1
    assert step.count('gh api --paginate "repos/${TARGET_REPOSITORY}/pulls/${PR_NUMBER}/reviews') == 1
    for token in ("while :; do", "poll_interval_seconds", "poll_deadline_epoch", "max_poll_transport_failures", "sleep ", "timeout "):
        assert token not in step


def test_receipt_wake_binds_exact_pr_head_and_run_without_polling() -> None:
    """Authenticated receipt wake is one exact-state transition."""
    step = _wake()
    for token in ("for attempt", "while :; do", "seq 1", "sleep ", "timeout ", "/12", "--paginate"):
        assert token not in step
    assert "pull_requests // []" in step
    assert "rerun-failed-jobs" in step
    assert "advanced concurrently" in step


def test_missing_verdict_fails_after_one_live_and_one_reviews_read(tmp_path: Path) -> None:
    """No formal verdict causes exactly two GitHub reads and an immediate failure."""
    bash = shutil.which("bash")
    jq = shutil.which("jq")
    if bash is None or jq is None:
        pytest.skip("bash and jq are required")
    calls = tmp_path / "calls"
    gh = tmp_path / "gh"
    gh.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\nprintf '%s\\n' \"$*\" >>\"$CALLS\"\n"
        "if [[ \"$*\" == \"api repos/ContextualWisdomLab/example/pulls/42\" ]]; then printf '%s\\n' \"$LIVE_PR\"; exit 0; fi\n"
        "if [[ \"$*\" == \"api --paginate repos/ContextualWisdomLab/example/pulls/42/reviews?per_page=100\" ]]; then printf '[]\\n'; exit 0; fi\n"
        "exit 97\n",
        encoding="utf-8",
    )
    gh.chmod(0o755)
    result = subprocess.run(
        [bash, "-c", _required_script()],
        env={**os.environ, "PATH": f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}", "CALLS": str(calls), "LIVE_PR": json.dumps({"head": {"sha": HEAD}, "draft": False, "state": "open"}), "GH_TOKEN": "token", "TARGET_REPOSITORY": "ContextualWisdomLab/example", "PR_NUMBER": "42", "HEAD_SHA": HEAD, "PR_ACTION": "synchronize", "PR_DRAFT": "false"},
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 1, result.stderr
    assert len(calls.read_text(encoding="utf-8").splitlines()) == 2
''', encoding="utf-8")

SELF.write_text(r'''"""Regression contract for self-releasing Required OpenCode verdict admission."""

from pathlib import Path

WORKFLOW = Path(".github/workflows/opencode-review.yml")


def _step() -> str:
    """Return only the one-shot exact-head verdict-admission step."""
    text = WORKFLOW.read_text(encoding="utf-8")
    return text.split("      - name: Fail closed without a current-head OpenCode verdict\n", 1)[1].split("\n  cancel-superseded-opencode-review-runs:\n", 1)[0]


def test_one_shot_revalidates_live_authority_before_review_evidence() -> None:
    """Live PR/head/draft/state authority precedes the complete Reviews read."""
    step = _step()
    live = 'gh api "repos/${TARGET_REPOSITORY}/pulls/${PR_NUMBER}"'
    reviews = 'gh api --paginate "repos/${TARGET_REPOSITORY}/pulls/${PR_NUMBER}/reviews'
    assert live in step and reviews in step and step.index(live) < step.index(reviews)
    assert "Could not validate live pull request state before verdict admission" in step
    assert "PR is still a draft" in step
    assert "fresh required-review run will bind the current head" in step


def test_one_shot_has_no_repository_authored_wait_retry_or_transport_deadline() -> None:
    """No elapsed-time or fixed-attempt policy governs formal verdict admission."""
    step = _step()
    for token in ("while :; do", "poll_interval_seconds", "poll_deadline_epoch", "max_poll_transport_failures", "sleep ", "timeout "):
        assert token not in step
''', encoding="utf-8")

EVENT.write_text(r'''"""Contracts for event-driven Required OpenCode Review wake reconciliation."""

from pathlib import Path

REQUIRED = Path(".github/workflows/opencode-review.yml")
DISPATCH = Path(".github/workflows/opencode-review-dispatch.yml")
SCHEDULER = Path(".github/workflows/pr-review-merge-scheduler.yml")


def _required() -> str:
    """Return only current-head formal-verdict admission."""
    text = REQUIRED.read_text(encoding="utf-8")
    return text.split("      - name: Fail closed without a current-head OpenCode verdict\n", 1)[1].split("\n  cancel-superseded-opencode-review-runs:\n", 1)[0]


def _wake() -> str:
    """Return only authenticated formal-receipt wake."""
    text = DISPATCH.read_text(encoding="utf-8")
    return text.split("      - name: Wake exact-head required OpenCode workflow\n", 1)[1].split("\n      - name: Publish repository_dispatch OpenCode status\n", 1)[0]


def test_required_verdict_admission_has_no_repository_authored_wait_allocation() -> None:
    """Missing verdict fails closed after authoritative reads, not elapsed time."""
    step = _required()
    for token in ("while :; do", "poll_interval_seconds", "poll_deadline_epoch", "max_poll_transport_failures", "sleep ", "timeout "):
        assert token not in step


def test_dispatch_receipt_wake_is_one_exact_state_transition() -> None:
    """A formal receipt never introduces a retry, sleep, transport, or review-read loop."""
    step = _wake()
    for token in ("for attempt", "seq 1", "sleep ", "timeout ", "/12", "--paginate"):
        assert token not in step
    assert "pull_requests // []" in step
    assert "rerun-failed-jobs" in step


def test_workflow_run_completion_closes_review_before_failure_race() -> None:
    """Failed completion reruns only when newer formal exact-head evidence exists."""
    scheduler = SCHEDULER.read_text(encoding="utf-8")
    job = scheduler.split("  reconcile-opencode-required-verdict:\n", 1)[1].split("\n  scan-pr-queue:\n", 1)[0]
    assert "github.event_name == 'workflow_run'" in job
    assert "github.event.workflow_run.name == 'Required OpenCode Review'" in job
    assert "github.event.workflow_run.conclusion == 'failure'" in job
    assert "github.event.workflow_run.run_started_at" in job
    assert "review_submitted_at" in job and "fromdateiso8601" in job
    assert "rerun-failed-jobs" in job
    for token in ("for attempt", "while :; do", "sleep ", "timeout "):
        assert token not in job
''', encoding="utf-8")


# Repair legacy regression assertions without weakening exact PR/head/run
# selection. v3 already migrates the selector to pull_requests[].head.sha.
regression = REGRESSION.read_text(encoding="utf-8")
regression = regression.replace('    assert "while :; do" in required\n', '    assert "while :; do" not in required\n', 1)
regression = regression.replace('    """The receipt wake path coexists with the unbounded required review wait."""\n', '    """The receipt wake path coexists with one-shot required verdict admission."""\n', 1)
REGRESSION.write_text(regression, encoding="utf-8")


architecture = ARCHITECTURE.read_text(encoding="utf-8")
heading = "### Required OpenCode event-driven verdict admission"
if heading not in architecture:
    architecture += f'''\n\n{heading}\n\nThe required workflow performs one live-PR read and one complete paginated formal-review read, then fails closed immediately if no exact-head verdict exists. The privileged formal-review receipt reconciles the immutable required-run id once. If that review arrives before the run finishes, GitHub's `workflow_run: completed` event performs the complementary reconciliation. The completion path admits a rerun only when exact PR/head/workflow identity holds and `review.submitted_at > run.run_started_at`; the same old evidence therefore cannot create an unbounded rerun cycle. No repository-authored polling cadence, retry count, sleep, transport timeout, or model reasoning deadline is part of this verdict-wake state machine.\n'''
    ARCHITECTURE.write_text(architecture, encoding="utf-8")

doctoring = DOCTORING.read_text(encoding="utf-8")
heading = "### 2026-09-02 event-driven wake supersedes fixed retry allocation"
if heading not in doctoring:
    doctoring += f'''\n\n{heading}\n\nRCA found that the intermediate PR #1706 repair replaced a runner-held verdict poll with a dispatch wake loop containing fixed `12` attempts, `5` second sleeps, and `30` second transport deadlines. Those values had no governing model, standard, experiment, or provider contract. The corrected state machine uses the authenticated formal-review receipt event plus GitHub's `workflow_run` `completed` event. Receipt-after-failure performs one exact-run transition; review-before-failure is reconciled on completion and requires `review.submitted_at > run.run_started_at`. Mutation readback only resolves concurrent state advancement and is not a retry loop.\n\nReference (APA 7): GitHub. (2026). *Events that trigger workflows*. GitHub Docs. https://docs.github.com/actions/using-workflows/events-that-trigger-workflows#workflow_run\n'''
    DOCTORING.write_text(doctoring, encoding="utf-8")

baseline = BASELINE.read_text(encoding="utf-8")
heading = "### OPENCODE-EVENT-DRIVEN-REQUIRED-WAKE-2026-09-02"
if heading not in baseline:
    baseline += f'''\n\n{heading}\n- Gap: Required OpenCode verdict admission occupied a hosted runner while waiting; an intermediate repair then introduced fixed dispatch retry/sleep/transport allocations (`12`, `5s`, `30s`) without a governing model or standard.\n- Causal owner: `ContextualWisdomLab/.github` required review and merge-control workflows.\n- Repair: one-shot exact-head verdict admission plus dual event reconciliation. A formal-review receipt handles review-after-failure; GitHub `workflow_run: completed` handles review-before-failure with exact PR/head/workflow identity and `review.submitted_at > run.run_started_at`.\n- Verification: executable regressions cover one-shot admission, `pull_request_target` PR-head identity rather than base `head_sha`, opposite event orderings, stale evidence, and absence of repository-authored retry/sleep/transport budgets.\n- Status: Proposed on PR #1706 until exact-head focused/full CI and independent review are GREEN.\n'''
    BASELINE.write_text(baseline, encoding="utf-8")

changelog = CHANGELOG.read_text(encoding="utf-8")
note = "- Required OpenCode verdict wake is event-driven: formal-review receipt and GitHub `workflow_run: completed` reconcile exact run/PR/head state, replacing runner polling and fixed wake retry/sleep/transport allocations.\n"
if note not in changelog:
    CHANGELOG.write_text(note + changelog, encoding="utf-8")
