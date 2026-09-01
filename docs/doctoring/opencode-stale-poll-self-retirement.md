# OpenCode stale-poll self-retirement

## Incident boundary

On 2026-09-02, `ContextualWisdomLab/fast-mlsirm` retained an in-progress `Required OpenCode Review` run for PR #1519 on predecessor head `5453d0df84e4e...` while the live PR head had already advanced to `3a3865f40da12211898c97cbd47e7460381736ae`. The predecessor run had entered the required workflow's Reviews API wait and continued occupying a runner. At the same observation, the repository had a fresh current-head OpenCode run queued and the organization-wide Actions fleet was heavily queued.

The protected central workflow intentionally keys concurrency by repository, PR number, and exact head SHA. That protects a newer authoritative run from a delayed old-head event, but it also means a new commit cannot cancel the previous head through the concurrency group. A separate `cancel-superseded-opencode-review-runs` job exists for that cleanup, yet it needs its own runner. Under saturation, the cleanup job can therefore wait behind the stale poll it is meant to retire.

## Root cause

`opencode-review-target` validated the live PR head/state/draft once before entering an unbounded `while` loop. The loop then queried only the Reviews API every 30 seconds. A head movement after the first validation was invisible to the occupied run, so an obsolete head could remain in progress until GitHub's job ceiling even though it could never receive an authoritative current-head verdict.

This is a control-plane capacity defect, not a reason to shorten semantic-review inference deadlines. A fixed short `timeout-minutes` would trade one failure mode for another and can kill legitimate long-running review work.

## Repair contract

The polling loop now re-fetches the live pull request before every Reviews API read. It:

- fails closed when live head/state/draft evidence is missing or malformed;
- exits non-passing when the live head no longer equals the workflow's immutable `HEAD_SHA`, allowing the stale run to release its runner itself;
- exits successfully when the PR closes or becomes Draft while the same head is waiting, because no verdict is required in those states;
- keeps exact-head formal `APPROVED` / `CHANGES_REQUESTED` review evidence as the only terminal substantive verdict; and
- retains the existing no-short-timeout contract for legitimate semantic reviews.

The sibling cancellation job remains defense in depth for queued/requested predecessor runs and for legacy workflow revisions that do not contain the in-loop self-retirement check.

## Regression evidence

`tests/test_opencode_poll_self_retirement.py` was committed before the production workflow change. The protected-main workflow did not contain the required in-loop live-state lookup, so the new contract is RED on `main@7d707b8abbb8a3fed95d0efe4121ed9b4f76bb2a`. The production repair follows on the same single-writer branch and is constrained to the existing required-workflow entrypoint plus the new regression and this doctoring record.

Hosted exact-head evidence remains authoritative for merge. Queue, predecessor, cancelled, skipped, or locally reasoned evidence is not promoted to a passing required check or formal review.

## Rollback and observability

Rollback is the ordinary revert of the workflow repair if exact-head evidence shows false retirement of an authoritative run. During operation, inspect the live PR head together with the workflow run's immutable head SHA. An old-head run that remains in progress after a poll interval indicates either a legacy workflow revision or a failure before the self-retirement loop; do not classify a queued replacement verdict as success.

After protected integration, re-observe affected leaf repositories. Acceptance requires predecessor-head OpenCode polls to release runner capacity without waiting for a separate cleanup runner, while unchanged current-head semantic reviews remain able to run beyond arbitrary short deadlines.
