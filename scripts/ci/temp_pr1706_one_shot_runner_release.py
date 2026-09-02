"""Temporary exact-head repair driver for PR #1706; deleted after GREEN publication."""

from __future__ import annotations

from pathlib import Path


WORKFLOW = Path(".github/workflows/opencode-review.yml")
REGRESSION = Path("tests/test_opencode_required_verdict_regression.py")
RATE = Path("tests/test_opencode_poll_rate_budget.py")
SELF = Path("tests/test_opencode_poll_self_retirement.py")


def replace_once(text: str, old: str, new: str, label: str) -> str:
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
          live_pr="$(gh api "repos/${TARGET_REPOSITORY}/pulls/${PR_NUMBER}")"
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
          if ! reviews="$(gh api --paginate "repos/${TARGET_REPOSITORY}/pulls/${PR_NUMBER}/reviews?per_page=100")"; then
            echo "::error::Reviews API read failed during one-shot current-head verdict admission; failing closed and releasing the runner."
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

RATE.write_text('''"""Request-budget regression for one-shot Required OpenCode verdict admission."""\n\nfrom pathlib import Path\n\nWORKFLOW = Path(".github/workflows/opencode-review.yml")\n\ndef _step() -> str:\n    text = WORKFLOW.read_text(encoding="utf-8")\n    return text.split("      - name: Fail closed without a current-head OpenCode verdict\\n", 1)[1].split("\\n  cancel-superseded-opencode-review-runs:\\n", 1)[0]\n\ndef test_one_reviews_read_without_runner_polling() -> None:\n    step = _step()\n    assert step.count('gh api "repos/${TARGET_REPOSITORY}/pulls/${PR_NUMBER}"') == 1\n    assert step.count('gh api --paginate "repos/${TARGET_REPOSITORY}/pulls/${PR_NUMBER}/reviews?per_page=100"') == 1\n    for token in ("while :; do", "poll_interval_seconds", "poll_deadline_epoch", "sleep "):\n        assert token not in step\n\ndef test_reviews_read_uses_full_page() -> None:\n    step = _step()\n    assert "/reviews?per_page=100" in step\n    assert "gh api --paginate" in step\n''', encoding="utf-8")

self_text = SELF.read_text(encoding="utf-8")
self_text = replace_once(self_text, '"""Regression contract for stale OpenCode poll self-retirement."""', '"""Regression contract for one-shot Required OpenCode verdict admission."""', "self-retirement module docstring")
self_text = self_text.replace("poll", "admission")
self_text = self_text.replace("Poll", "Admission")
self_text = self_text.replace("POLL", "ADMISSION")
# The behavioral tests execute production shell; keep them but remove retry/deadline assumptions.
for old, new in [
    ('a fresh poll will start for the current head.', 'a fresh required-review run will bind the current head.'),
    ('Reviews API read failed 3 consecutive times', 'Reviews API read failed during one-shot current-head verdict admission'),
]:
    self_text = self_text.replace(old, new)
SELF.write_text(self_text, encoding="utf-8")

regression = REGRESSION.read_text(encoding="utf-8")
for old, new, label in [
    ('    assert "while :; do" in target_job\n    assert \'sleep "$poll_interval_seconds"\' in target_job\n', '    assert "while :; do" not in target_job\n    assert "poll_interval_seconds" not in target_job\n    assert "poll_deadline_epoch" not in target_job\n    assert \'sleep "$poll_interval_seconds"\' not in target_job\n', "legacy poll assertions"),
    ('a fresh poll will start for the current head.', 'a fresh required-review run will bind the current head.', "moved-head message"),
    ('Reviews API read failed 3 consecutive times', 'Reviews API read failed during one-shot current-head verdict admission', "transport failure message"),
    ('"""The receipt wake path coexists with the unbounded required review wait."""', '"""The receipt wake path reawakens the fail-closed one-shot required review."""', "receipt wake docstring"),
    ('    assert "while :; do" in required\n', '    assert "while :; do" not in required\n    assert "poll_deadline_epoch" not in required\n', "receipt wake loop assertion"),
]:
    regression = replace_once(regression, old, new, label)
REGRESSION.write_text(regression, encoding="utf-8")

baseline = Path("docs/product-technical-gap-baseline.md")
text = baseline.read_text(encoding="utf-8")
marker = "### OPENCODE-ONE-SHOT-RUNNER-RELEASE-2026-09-02"
if marker not in text:
    text += f'''\n\n{marker}\n- Owner: `ContextualWisdomLab/.github` Required OpenCode Review control plane.\n- RCA: required-verdict occupied a runner while asynchronous model work continued, using repository-authored polling/retry/wall-clock allocation despite an authenticated exact-run wake contract.\n- GREEN: one live PR read plus one Reviews read; missing/unavailable exact-head verdict fails closed immediately and dispatch wakes the exact failed run after the verdict. Model reasoning receives no caller wall-clock timeout.\n- Regression: `tests/test_opencode_required_verdict_runner_release.py` plus one-shot request/state and dispatch-wake contracts.\n'''
    baseline.write_text(text, encoding="utf-8")

doctoring = Path("docs/doctoring/opencode-stale-poll-self-retirement.md")
text = doctoring.read_text(encoding="utf-8")
marker = "## 2026-09-02 one-shot runner-release supersession"
if marker not in text:
    text += f'''\n\n{marker}\n\nThe required-verdict job performs one authoritative live-PR read followed by at most one paginated Reviews read. Missing or unavailable exact-head verdict evidence fails closed immediately and releases the runner. Authenticated `opencode-review-dispatch.yml` wakes the exact failed run via `rerun-failed-jobs` when the formal verdict arrives; no repository-authored polling interval, retry count, or wall-clock deadline bounds model work.\n'''
    doctoring.write_text(text, encoding="utf-8")

changelog = Path("CHANGELOG.md")
text = changelog.read_text(encoding="utf-8")
note = "- Required OpenCode Review now releases its runner after one exact-head verdict admission read and relies on authenticated exact-run dispatch wake instead of repository-authored polling, retry-count, or waiting deadlines.\n"
if note not in text:
    changelog.write_text(note + text, encoding="utf-8")
