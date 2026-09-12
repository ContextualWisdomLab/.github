# Agent-mention sweep completion-order regression

Decision date: **2026-09-08**

## Problem

`list_recent_pull_requests` submits bounded repository fetches concurrently and
iterates them with `concurrent.futures.as_completed`. Its regression instead
claimed that results remain in repository order and asserted
`first, second` without controlling completion. The assertion therefore tested
thread timing rather than the production contract.

A slow first repository is an operational failure scene: if the already-finished
second repository is hidden behind it, the sweep wastes its bounded dispatch
window and may omit actionable mentions before the next rotation.

## Decision

Keep the production implementation unchanged. Replace only the stale regression
with a deterministic fixture. The first repository waits on an event; the caller
must receive the second repository before releasing that event. The test retains
the exact two-worker assertion.

This is the minimum owner repair. It adds no scheduler abstraction, timeout,
retry, ordering buffer, or dependency.

## Evidence

- RED `570da463b0ce7f4837727a91557187624a7b37db` makes the completion order
  deterministic while retaining the obsolete `first, second` expectation.
  The production iterator necessarily yields `second` first.
- GREEN replaces the expectation with `second, first` and names the latency
  contract directly.
- Exact-head hosted Checks remain the admission authority.

## Risks and rollback

The event wait has a 30-second failure ceiling so a broken executor produces an
actionable failure instead of hanging the suite. Rollback is removal of this
test-only successor; production behavior is unchanged.

## References

Python Software Foundation. (2026). *concurrent.futures — Launching parallel
tasks*. Python 3 documentation.
https://docs.python.org/3/library/concurrent.futures.html#concurrent.futures.as_completed
