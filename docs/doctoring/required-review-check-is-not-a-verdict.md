# Required OpenCode/Noema checks are not reviews

검토 기준일: **2026-08-14**

## Incident

On ContextualWisdomLab/contextual-orchestrator#176 the required
`opencode-review` and `noema-review` checks were green, but the Reviews
API had no APPROVE or REQUEST_CHANGES. Authors treated the check name as
a review verdict (GitHub, n.d.-a). That is weaker than the modern-review
expectation that a review is an explicit, current-head judgment
(Bacchelli & Bird, 2013).

## Decision

The required `opencode-review` job on
`.github/workflows/opencode-review.yml` never runs the model. Privileged
review stays in `opencode-review-dispatch.yml`. The required job now
reads current-head reviews with `pull-requests: read` and **fails
closed** unless `opencode-agent` / `opencode-agent[bot]` already posted
`APPROVED` or `CHANGES_REQUESTED` on that SHA. A COMMENTED review, a
review on an old SHA, or no review at all cannot make the check green.

`scripts/ci/noema_review_gate.py` no longer returns 0 when the current
head has no primary OpenCode approval. That skip was exit 0, so the
required `noema-review` check looked like a successful review. Draft
status is checked only after that primary-approval gate, so a draft
without an OpenCode verdict cannot turn `noema-review` green. The gate
also validates the primary approval before accepting an existing Noema
review; a secondary verdict cannot independently turn the required gate
green.

Human `repository_dispatch` as `seonghobae` remains rejected; only
`github-actions[bot]` may start the privileged dispatch. After a real
verdict is posted, re-run the required `opencode-review` job so the
fail-closed check can observe it.

The one-dispatch-per-run budget used to walk pull requests in created-at
order, so leftover increments that already had a previous-head verdict
consumed the slot while a later PR with an empty Reviews tab waited. The
scheduler now stable-sorts that budget: no OpenCode APPROVED or
CHANGES_REQUESTED on any commit first, then previous-head re-reviews,
then current-head verdicts. COMMENTED-only evidence is not a verdict and
keeps the empty-Reviews priority.

A second same-head `repository_dispatch` used to cancel the first through
workflow `cancel-in-progress` because `active_review_run_refs` compared
the GitHub `name` field to the short alias `OpenCode Review Dispatch`.
Live runs set `name` to the interpolated run-name. The matcher now
accepts that prefix so a queued or in-progress same-head review is
`already_running`.

## Exact CodeQL merge-preview contract

The central CodeQL pull-request workflow must analyze the merge tree formed by
the current base and head, not merely trust the event's
`pull_request.merge_commit_sha`. A live CodeQL failure showed that GitHub can
provide a merge commit whose parents and tree belong to an older pull-request
head. The workflow now verifies the supplied identity, computes
`git merge-tree --write-tree` for the current pair, and materializes a
deterministic two-parent local commit when the supplied metadata is stale or
structurally different. CodeQL receives the resulting analyzed SHA and the
workflow records both identities, so a stale preview cannot silently become
current-head evidence (GitHub, n.d.-b).

## Draft pull-request review contract

Draft status is a merge-readiness signal, not a request to suppress early
feedback. The central scheduler therefore dispatches same-head Strix first
and then authenticated OpenCode review for draft pull requests. The draft
path is deliberately review-only: it cannot update the head branch, enable
or disable auto-merge, merge, dismiss reviews, or resolve review threads.
Marking a pull request ready remains the explicit boundary for merge
automation.

## Verification contract

- `tests/test_opencode_required_verdict_gate.py` pins
  `current_head_opencode_verdict` and `decide_required_verdict_check`.
- `tests/test_noema_review_gate.py` requires exit 1 when there is no
  primary OpenCode approval, even when the current head already has a Noema
  review, while retaining the idempotent success path after a valid primary
  approval exists.
- `tests/test_opencode_agent_contract.py` pins the required workflow
  fail-closed error string.
- `tests/test_pr_review_merge_scheduler.py` proves that a draft pull request
  receives same-head Strix and OpenCode dispatch while branch updates,
  auto-merge mutation, direct merge, review dismissal, and thread cleanup
  remain unreachable, and that a never-reviewed pull request consumes the
  one-dispatch budget before a leftover increment that already has a
  previous-head OpenCode verdict.
- Both repairs were exercised test-first: the draft-dispatch contract failed
  against the old unconditional skip, and the Noema ordering contract failed
  against the old secondary-review-first branch. The exact repaired source
  then passed 988 tests, 7,056 production statements, 2,834 production
  branches, and the public-docstring gate at 100%.

## References (APA 7th)

Bacchelli, A., & Bird, C. (2013). Expectations, outcomes, and challenges of
modern code review. In *Proceedings of the 35th International Conference on
Software Engineering* (pp. 712–721). IEEE.
https://doi.org/10.1109/ICSE.2013.6606617

GitHub. (n.d.-a). *About status checks*. GitHub Docs. Retrieved
August 14, 2026, from https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/collaborating-on-repositories-with-code-quality-features/about-status-checks

GitHub. (n.d.-b). *About code scanning with CodeQL*. GitHub Docs. Retrieved
August 22, 2026, from https://docs.github.com/en/code-security/code-scanning/introduction-to-code-scanning/about-code-scanning-with-codeql
