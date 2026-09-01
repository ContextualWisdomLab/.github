# OpenCode stale-poll self-retirement

## Incident boundary

On 2026-09-01 UTC (2026-09-02 Asia/Seoul), `ContextualWisdomLab/fast-mlsirm` retained an in-progress `Required OpenCode Review` run for PR #1519 on predecessor head `5453d0df84e4e...` while the live PR head had already advanced to `3a3865f40da12211898c97cbd47e7460381736ae`. The predecessor run had entered the required workflow's Reviews API wait and continued occupying a runner. At the same observation, the repository had a fresh current-head OpenCode run queued and the organization-wide Actions fleet was heavily queued.

The protected central workflow intentionally keys concurrency by repository, PR number, and exact head SHA. That protects a newer authoritative run from a delayed old-head event, but it also means a new commit cannot cancel the previous head through the concurrency group. A separate `cancel-superseded-opencode-review-runs` job exists for that cleanup, yet it needs its own runner. Under saturation, the cleanup job can therefore wait behind the stale poll it is meant to retire.

## Root cause

`opencode-review-target` validated the live PR head/state/draft once before entering an unbounded `while` loop. The loop then queried only the Reviews API every 30 seconds. A head movement after the first validation was invisible to the occupied run, so an obsolete head could remain in progress until GitHub's job ceiling even though it could never receive an authoritative current-head verdict.

The first self-retirement repair added a live PR read before every Reviews read, but an external review then exposed a second capacity defect: keeping both reads on a 30-second cadence approximately doubled the steady-state REST pressure. Four simultaneous current-head polls would issue about 960 baseline REST calls per hour before Reviews pagination or other automation. That approaches the repository-scoped token budget too closely and turns the reliability repair into a rate-pressure risk.

This is a control-plane capacity defect, not a reason to shorten semantic-review inference deadlines. A fixed short `timeout-minutes` would trade one failure mode for another and can kill legitimate long-running review work.

## Repair contract

The polling loop re-fetches the live pull request before every Reviews API read and now uses a 60-second poll interval. It:

- fails closed when live head/state/draft evidence is missing or malformed;
- exits non-passing when the live head no longer equals the workflow's immutable `HEAD_SHA`, allowing the stale run to release its runner itself;
- exits successfully when the PR closes or becomes Draft while the same head is waiting, because no verdict is required in those states;
- bounds each individual live-state and Reviews API request to 30 seconds and permits at most three consecutive transport failures before failing closed and releasing the runner;
- revalidates live PR state before a Reviews retry, so a transport failure cannot let a stale head skip identity validation;
- requests Reviews with `per_page=100` and pagination, minimizing page count without dropping older review evidence;
- uses the same 60-second delay for healthy polling and transient retries rather than busy-retrying GitHub; and
- keeps exact-head formal `APPROVED` / `CHANGES_REQUESTED` review evidence as the only terminal substantive verdict while retaining the no-short-timeout contract for legitimate semantic reviews.

At four simultaneous polls, the two baseline REST reads per 60-second iteration are approximately 480 calls per hour before Reviews pagination or unrelated automation. This is a bounded pressure reduction, not a claim that pagination can never add calls: repositories with more than 100 reviews still require additional pages. The page-size regression exists to keep that unavoidable pagination as small as the REST endpoint allows.

The sibling cancellation job remains defense in depth for queued/requested predecessor runs and for legacy workflow revisions that do not contain the in-loop self-retirement check.

## Regression evidence

`tests/test_opencode_poll_self_retirement.py` was committed before the production self-retirement change and now executes the extracted production loop under Bash with deterministic fake-`gh` responses for moved-head, closed/draft, exact-head verdict, transient-recovery, and terminal transport-failure paths. `tests/test_opencode_poll_rate_budget.py` is the later RED-to-GREEN contract for 60-second polling and maximum Reviews page size. `tests/test_opencode_oidc_audience_contract.py` independently preserves the dispatch OIDC audience variable after a writer-side typo was caught and repaired during the rate-budget implementation.

The original protected-main workflow did not contain the required in-loop live-state lookup. Later review-derived regressions additionally prevent the self-retirement repair from regressing into excessive steady-state REST pressure or silently breaking the OIDC dispatch credential path.

Hosted exact-head evidence remains authoritative for merge. Queue, predecessor, cancelled, skipped, or locally reasoned evidence is not promoted to a passing required check or formal review.

## Rollback and observability

Rollback is the ordinary revert of the workflow repair if exact-head evidence shows false retirement of an authoritative run. During operation, inspect the live PR head together with the workflow run's immutable head SHA. An old-head run that remains in progress for materially longer than one 60-second poll interval indicates either a legacy workflow revision or a failure before the self-retirement loop; do not classify a queued replacement verdict as success.

Monitor both runner occupancy and GitHub API failure/rate-limit evidence. Repeated transport failures should terminate the required check after three bounded attempts rather than leave an immortal poll. A rate-pressure regression should be repaired by changing evidence acquisition/cadence without weakening exact-head review semantics.

After protected integration, re-observe affected leaf repositories. Acceptance requires predecessor-head OpenCode polls to release runner capacity without waiting for a separate cleanup runner, while unchanged current-head semantic reviews remain able to run beyond arbitrary short deadlines and current-head polls stay within a defensible REST request budget.
