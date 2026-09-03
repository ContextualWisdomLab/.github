# Scheduler stale-head cancellation: fail closed at the destructive boundary

## Incident

On 2026-09-02, `ContextualWisdomLab/naruon#1528` had Strix run `33581213829`
cancelled while head `cf472cf77fb93325858f485a22e967449d7c387a` was still the pull
request's sole current head. The run-local Strix supersession job was skipped;
the shared merge scheduler remained a separate cancellation authority.

## Root cause

`stale_pr_run_ids()` and `active_review_run_refs()` converted an unresolved or
malformed `headRefOid` into non-authoritative comparison state. Their downstream
destructive paths trusted an earlier snapshot. A push between classification and
cancellation could therefore make a newly current run appear stale. The direct
OpenCode and Strix dispatch paths also cancelled their classified stale refs
without refreshing run and pull-request identity.

## Repair contract

- Snapshot heads pass the canonical 40-hex SHA validator. Missing or malformed
  heads preserve all active runs.
- Every direct and central-review cancellation candidate is re-read immediately
  before its destructive cancellation call.
- The live pull request must still be open, expose an explicit live draft state, and
  expose a valid head SHA. Open drafts remain eligible for stale review-run cleanup
  because draft review-only dispatch is supported; merge admission stays independently draft-gated.
- The candidate run must still be queued/in-progress and retain the expected
  direct PR association or trusted central dispatch target.
- A candidate that now matches the live head, or whose identity/state cannot be
  proven, is preserved and blocks duplicate dispatch rather than being cancelled.
- Genuine older-head runs remain cancellable, including the bounded parallel
  multi-candidate path.

This aligns the Python scheduler with the live-reference race contract already
used by `scripts/ci/revalidate_queue_cancellation.sh`.

## Verification

The one-shot publisher first installs isolated regressions and requires each one
to finish as exactly one ordinary pytest failure (`exit=1`, `1 failed`) before
production transformation. Collection/environment failures are not accepted as
RED evidence. Final verification runs the focused scheduler suite, complete
repository suite with 100% statement/branch coverage, 100% `scripts/ci`
docstring coverage, compileall, and diff hygiene. The publisher, workflow, and
all temporary repair artifacts delete themselves from the published successor.
