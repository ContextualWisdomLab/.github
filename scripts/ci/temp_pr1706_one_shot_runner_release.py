"""Temporary exact-head repair driver for PR #1706; deleted after GREEN publication."""

from __future__ import annotations

from pathlib import Path


WORKFLOW = Path(".github/workflows/opencode-review.yml")
DISPATCH = Path(".github/workflows/opencode-review-dispatch.yml")
REGRESSION = Path("tests/test_opencode_required_verdict_regression.py")
RATE = Path("tests/test_opencode_poll_rate_budget.py")
SELF = Path("tests/test_opencode_poll_self_retirement.py")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    """Replace one exact stale contract and fail if concurrent edits changed it."""
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label} drifted: expected one exact match, found {count}")
    return text.replace(old, new, 1)


workflow = WORKFLOW.read_text(encoding="utf-8")
start = "      - name: Fail closed without a current-head OpenCode verdict\n"
end = "\n  cancel-superseded-opencode-review-runs:\n"
if workflow.count(start) != 1 or workflow.count(end) != 1:
    raise SystemExit("OpenCode required-verdict step boundaries drifted")
before, rest = workflow.split(start, 1)
_old_step, after = rest.split(end, 1)
replacement = r'''      - name: Fail closed without a current-head OpenCode verdict
        env:
          GH_TOKEN: ${{ github.token }}
          TARGET_REPOSITORY: ${{ github.event.pull_request.base.repo.full_name || github.repository }}
          PR_NUMBER: ${{ github.event.pull_request.number }}
          HEAD_SHA: ${{ github.event.pull_request.head.sha }}
          PR_ACTION: ${{ github.event.action }}
          PR_DRAFT: ${{ github.event.pull_request.draft }}
        run: |
          set -euo pipefail
          if [ "$PR_ACTION" = "closed" ]; then
            echo "PR closed; a current-head OpenCode verdict is not required."
            exit 0
          fi
          if [ -z "${PR_NUMBER:-}" ] || [ -z "${HEAD_SHA:-}" ]; then
            echo "::error::Missing PR number or head SHA; cannot verify a current-head OpenCode verdict."
            exit 1
          fi
          if ! live_pr="$(timeout 30 gh api "repos/${TARGET_REPOSITORY}/pulls/${PR_NUMBER}")"; then
            echo "::error::Live pull-request API read failed or exceeded the bounded transport deadline; failing closed and releasing the runner."
            exit 1
          fi
          live_head="$(printf '%s' "$live_pr" | jq -r '.head.sha // empty')"
          live_draft="$(printf '%s' "$live_pr" | jq -r 'if (.draft | type) == "boolean" then (.draft | tostring) else empty end')"
          live_state="$(printf '%s' "$live_pr" | jq -r 'if (.state | type) == "string" then .state else empty end')"
          if [ -z "$live_head" ] || [ -z "$live_draft" ] || [ -z "$live_state" ]; then
            echo "::error::Could not validate live pull request state before verdict admission."
            exit 1
          fi
          if [ "$live_state" != "open" ] && [ "$live_state" != "closed" ]; then
            echo "::error::Could not validate live pull request state before verdict admission."
            exit 1
          fi
          if [ "$live_state" = "closed" ]; then
            echo "PR is closed on the live exact head; a current-head OpenCode verdict is not required."
            exit 0
          fi
          if [ "$live_draft" = "true" ]; then
            echo "PR is still a draft on the live exact head; a current-head OpenCode verdict is not required until it is marked ready for review."
            exit 0
          fi
          if [ "${live_head,,}" != "${HEAD_SHA,,}" ]; then
            echo "Pull request head moved on the live open, ready-for-review PR; a fresh required-review run will bind the current head."
            exit 0
          fi
          if [ "$PR_DRAFT" = "true" ]; then
            echo "Event draft snapshot is stale; continuing one-shot verdict admission for the live ready PR."
          fi
          if ! reviews="$(timeout 30 gh api --paginate "repos/${TARGET_REPOSITORY}/pulls/${PR_NUMBER}/reviews?per_page=100")"; then
            echo "::error::Reviews API read failed or exceeded the bounded transport deadline during one-shot current-head verdict admission; failing closed and releasing the runner."
            exit 1
          fi
          verdict="$(printf '%s\n' "$reviews" | jq -r -s --arg sha "$HEAD_SHA" '
            (add // [])
            | [.[]
                | select((.user.login // "" | ascii_downcase) as $user | $user == "opencode-agent" or $user == "opencode-agent[bot]")
                | select((.commit_id // "" | ascii_downcase) == ($sha | ascii_downcase))
                | select(.state == "APPROVED" or .state == "CHANGES_REQUESTED")]
            | (last // {}) as $review
            | ($review.body // "" | ascii_downcase) as $body
            | if $review.state == "CHANGES_REQUESTED" then "CHANGES_REQUESTED"
              elif $review.state == "APPROVED"
                and ($body | contains("deterministic current-head evidence") | not)
                and ($body | contains("deterministic fallback approval") | not)
                and ($body | contains("model-unavailable evidence fallback") | not)
                and ($body | contains("did not emit a usable current-head control block") | not)
                and ($body | contains("scope: `unsupported`") | not)
                and ($body | contains("model-pool outcome: `unknown`") | not)
              then "APPROVED" else empty end
          ')"
          if [ -z "$verdict" ]; then
            echo "::error::No APPROVED or CHANGES_REQUESTED from opencode-agent on the current head. This required check is not a review and must not succeed until the authenticated dispatch posts a current-head verdict. The dispatch path wakes this exact failed run when the verdict arrives."
            exit 1
          fi
          echo "Current-head OpenCode verdict: ${verdict}."
'''
WORKFLOW.write_text(before + replacement + end + after, encoding="utf-8")

# A pull_request_target run is created from the protected base, so workflow-run
# head_sha is not the PR head. Bind the immutable Required OpenCode run id to the
# intended PR and exact PR head through the run's pull_requests association.
dispatch = DISPATCH.read_text(encoding="utf-8")ndispatch = replace_once(
    dispatch,
    '          PR_HEAD_SHA: ${{ needs.validate-pr-metadata.outputs.head_sha }}\n          REQUIRED_RUN_ID: ${{ github.event.client_payload.required_run_id }}\n',
    '          PR_NUMBER: ${{ needs.validate-pr-metadata.outputs.pr_number }}\n          PR_HEAD_SHA: ${{ needs.validate-pr-metadata.outputs.head_sha }}\n          REQUIRED_RUN_ID: ${{ github.event.client_payload.required_run_id }}\n',
    "required-run wake PR number binding",
)
dispatch = replace_once(
    dispatch,
    '          [[ "$REQUIRED_RUN_ID" =~ ^[1-9][0-9]*$ ]] || {\n            echo "::error::Required OpenCode run id is missing or non-canonical."\n            exit 1\n          }\n',
    '          [[ "$REQUIRED_RUN_ID" =~ ^[1-9][0-9]*$ ]] || {\n            echo "::error::Required OpenCode run id is missing or non-canonical."\n            exit 1\n          }\n          [[ "$PR_NUMBER" =~ ^[1-9][0-9]*$ ]] || {\n            echo "::error::Required OpenCode PR number is missing or non-canonical."\n            exit 1\n          }\n',
    "required-run wake PR number validation",
)
dispatch = replace_once(
    dispatch,
    '            run="$(gh api "repos/${GH_REPOSITORY}/actions/runs/${REQUIRED_RUN_ID}")"\n',
    '            if ! run="$(timeout 30 gh api "repos/${GH_REPOSITORY}/actions/runs/${REQUIRED_RUN_ID}")"; then\n              echo "::error::Required OpenCode run lookup failed or exceeded the bounded transport deadline."\n              exit 1\n            fi\n',
    "required-run wake bounded transport lookup",
)
dispatch = replace_once(
    dispatch,
    '            required_run="$(printf \'%s\\n\' "$run" | jq -r --arg head "$PR_HEAD_SHA" --argjson run_id "$REQUIRED_RUN_ID" \'\n              select(.id == $run_id)\n              | select(.event == "pull_request_target")\n              | select(.path == ".github/workflows/opencode-review.yml")\n              | select(.head_sha == $head)\n',
    '            required_run="$(printf \'%s\\n\' "$run" | jq -r --arg head "$PR_HEAD_SHA" --argjson pr_number "$PR_NUMBER" --argjson run_id "$REQUIRED_RUN_ID" \'\n              select(.id == $run_id)\n              | select(.event == "pull_request_target")\n              | select(.path == ".github/workflows/opencode-review.yml")\n              | select(any(.pull_requests[]?; (.number == $pr_number) and ((.head.sha // "" | ascii_downcase) == ($head | ascii_downcase))))\n',
    "required-run wake exact PR-head association",
)
DISPATCH.write_text(dispatch, encoding="utf-8")

RATE.write_text('''"""Request-budget regression for one-shot Required OpenCode verdict admission."""\n\nfrom pathlib import Path\n\nWORKFLOW = Path(".github/workflows/opencode-review.yml")\n\ndef _step() -> str:\n    workflow = WORKFLOW.read_text(encoding="utf-8")\n    return workflow.split("      - name: Fail closed without a current-head OpenCode verdict\\n", 1)[1].split("\\n  cancel-superseded-opencode-review-runs:\\n", 1)[0]\n\ndef test_admission_uses_one_reviews_read_without_runner_polling() -> None:\n    step = _step()\n    assert step.count('timeout 30 gh api "repos/${TARGET_REPOSITORY}/pulls/${PR_NUMBER}"') == 1\n    assert step.count('timeout 30 gh api --paginate "repos/${TARGET_REPOSITORY}/pulls/${PR_NUMBER}/reviews?per_page=100"') == 1\n    for token in ("while :; do", "poll_interval_seconds", "poll_deadline_epoch", "sleep "):\n        assert token not in step\n\ndef test_review_read_keeps_maximum_rest_page_size() -> None:\n    step = _step()\n    assert "/reviews?per_page=100" in step\n    assert "gh api --paginate" in step\n''', encoding="utf-8")

SELF.write_text('''"""Regression contract for one-shot Required OpenCode verdict admission."""\n\nfrom pathlib import Path\n\nWORKFLOW = Path(".github/workflows/opencode-review.yml")\n\ndef _step() -> str:\n    workflow = WORKFLOW.read_text(encoding="utf-8")\n    return workflow.split("      - name: Fail closed without a current-head OpenCode verdict\\n", 1)[1].split("\\n  cancel-superseded-opencode-review-runs:\\n", 1)[0]\n\ndef test_live_state_precedes_review_evidence() -> None:\n    step = _step()\n    live = 'live_pr="$(timeout 30 gh api "repos/${TARGET_REPOSITORY}/pulls/${PR_NUMBER}")"'\n    reviews = 'reviews="$(timeout 30 gh api --paginate "repos/${TARGET_REPOSITORY}/pulls/${PR_NUMBER}/reviews?per_page=100")"'\n    assert live in step\n    assert reviews in step\n    assert step.index(live) < step.index(reviews)\n\ndef test_stale_or_terminal_state_releases_runner_before_review_read() -> None:\n    step = _step()\n    assert 'if [ "$live_state" = "closed" ]; then' in step\n    assert 'if [ "$live_draft" = "true" ]; then' in step\n    assert 'if [ "${live_head,,}" != "${HEAD_SHA,,}" ]; then' in step\n    assert "fresh required-review run will bind the current head" in step\n\ndef test_transport_failure_is_one_shot_bounded_and_fail_closed() -> None:\n    step = _step()\n    assert "Reviews API read failed or exceeded the bounded transport deadline" in step\n    assert step.count("timeout 30 gh api") == 2\n    assert "exit 1" in step\n    assert "while :; do" not in step\n    assert "sleep " not in step\n\ndef test_semantic_review_has_no_repository_authored_wait_deadline() -> None:\n    step = _step()\n    for token in ("poll_deadline_epoch", "max_poll_transport_failures", "sleep "):\n        assert token not in step\n''', encoding="utf-8")

regression = REGRESSION.read_text(encoding="utf-8")
for old, new, label in [
    ('    assert "while :; do" in target_job\n    assert \'sleep "$poll_interval_seconds"\' in target_job\n', '    assert "while :; do" not in target_job\n    assert "poll_interval_seconds" not in target_job\n    assert "poll_deadline_epoch" not in target_job\n    assert \'sleep "$poll_interval_seconds"\' not in target_job\n', "legacy poll assertions"),
    ('a fresh poll will start for the current head.', 'a fresh required-review run will bind the current head.', "moved-head message"),
    ('def test_fail_closed_step_still_polls_for_a_non_draft_pr(', 'def test_fail_closed_step_reads_reviews_once_for_a_non_draft_pr(', "poll test name"),
    ('Reviews API read failed 3 consecutive times', 'Reviews API read failed or exceeded the bounded transport deadline during one-shot current-head verdict admission', "transport failure message"),
    ('"""The receipt wake path coexists with the unbounded required review wait."""', '"""The receipt wake path reawakens the fail-closed one-shot required review."""', "receipt wake docstring"),
    ('    assert "while :; do" in required\n', '    assert "while :; do" not in required\n    assert "poll_deadline_epoch" not in required\n', "receipt wake loop assertion"),
]:
    regression = replace_once(regression, old, new, label)
REGRESSION.write_text(regression, encoding="utf-8")

baseline = Path("docs/product-technical-gap-baseline.md")
text = baseline.read_text(encoding="utf-8")
marker = "### OPENCODE-ONE-SHOT-RUNNER-RELEASE-2026-09-02"
if marker not in text:
    text += f'''\n\n{marker}\n- Owner: `ContextualWisdomLab/.github` Required OpenCode Review control plane.\n- RCA: required-verdict occupied a runner while asynchronous model work continued, using repository-authored polling/retry/wall-clock allocation despite an authenticated exact-run wake contract.\n- GREEN: one bounded live PR transport read plus one bounded Reviews transport read; missing/unavailable exact-head verdict fails closed immediately and dispatch wakes the exact failed run after the verdict. Model reasoning receives no caller wall-clock timeout.\n- Exact-run binding: `pull_request_target` workflow-run `head_sha` is the protected base, so wake validation binds immutable run id to the intended PR number and exact PR head through `workflow_run.pull_requests[]`.\n- Regression: `tests/test_opencode_required_verdict_runner_release.py` plus one-shot request/state and dispatch-wake contracts.\n'''
    baseline.write_text(text, encoding="utf-8")

doctoring = Path("docs/doctoring/opencode-stale-poll-self-retirement.md")
text = doctoring.read_text(encoding="utf-8")
marker = "## 2026-09-02 one-shot runner-release supersession"
if marker not in text:
    text += f'''\n\n{marker}\n\nThe required-verdict job performs one bounded authoritative live-PR transport read followed by at most one bounded paginated Reviews transport read. Missing or unavailable exact-head verdict evidence fails closed immediately and releases the runner. Authenticated `opencode-review-dispatch.yml` wakes the exact failed run via `rerun-failed-jobs` when the formal verdict arrives; no repository-authored polling interval, retry count, or model wall-clock deadline bounds semantic review. Because `pull_request_target` run `head_sha` is the protected base, the wake path validates the immutable run id against its `pull_requests[]` PR-number/exact-head association instead.\n'''
    doctoring.write_text(text, encoding="utf-8")

changelog = Path("CHANGELOG.md")
text = changelog.read_text(encoding="utf-8")
note = "- Required OpenCode Review now releases its runner after one exact-head verdict admission read and wakes the immutable failed run through its PR/exact-head association instead of repository-authored polling or `pull_request_target` base-SHA matching.\n"
if note not in text:
    changelog.write_text(note + text, encoding="utf-8")
