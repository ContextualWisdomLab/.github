# Strix all-429 startup continuation — 2026-09-27

## Evidence and cause

Current-head late-life-anxiety-reanalysis #257 (`3936039d8406275e754fc518f70fefa491d3d8bb`)
Strix job `108504580446` and #269 (`78617f3160cfe8fbf7a4dae2ca3f3fdaca44db8e`)
job `108303563901` failed before sidecar health. Sanitized producer evidence reported
`strix-plain-chat-preflight-v2`, ready=0, rejected=3, probed=3, and HTTP 429
for all selected routes. This was startup capacity loss, not a completed security review.

At main `23f36cd56fbe245a06e7a9727cb28d9511154645`, Strix's model retry
lives after sidecar startup and cannot recover this failure. PR #2440 repaired
Noema's corresponding boundary; this change reuses its stdlib-only classifier.

## Proposed boundary

The failed scan exports only typed capacity evidence. A separate job with minimal
Contents write permission sends at most two automatic `strix-scan` continuations.
It has no checkout, model inputs, or provider secrets. It rechecks the live open,
Ready PR's repository, head SHA, base SHA, and base ref after bounded scheduling
jitter, and retires if any changed. The payload includes all identity fields needed
by the existing Strix dispatch validator. The scan remains failed and its existing
status publication is unchanged. Cancellation cannot start a continuation.

Missing, malformed, non-429, linked, or oversized preflight reports are ineligible;
malformed retry counters exhaust the shared budget. Stale reports are removed
before startup. Private-target ZDR, free-route policy, gateway failover, and model
inference time limits are unchanged.

## Verification boundary

The actual dispatch shell is exercised with local GitHub/sleep stubs. It verifies
one exact payload for a valid Ready PR and zero dispatches for moved head/base ref,
Draft, malformed Draft, closed state, or invalid attempts. Existing classifier and
Strix sidecar contract tests also pass. This is local evidence only; fresh hosted
review and an observed same-head continuation are still required after deployment.
