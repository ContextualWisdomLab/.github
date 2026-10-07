# CodeQL terminal-proof settlement (#2352)

## Incident

On `.github#2352@f1a8dc813e6dba4e4905bf3e1b770b6d44344944`, required CodeQL
run `35805450471` initially failed pending and was later rerun. Attempt 2 jobs
`107353895415` (Actions) and `107353895562` (Python) became GREEN by reading
the successful `Enforce CodeQL Medium+ SARIF gate` step from producer run
`35841640640`.

The producer jobs were nevertheless terminal failures: the later
`Verify GHAS base/head CodeQL configuration identity` step received HTTP 403.
The gate-only fallback therefore hid the exact credential/permission defect
tracked by `#2275` and `#2276`.

## Root cause and boundary

The required receiver and settlement contract treated one successful SARIF
gate step as terminal success even when a later mandatory proof failed. This
was originally allowed so a wake-only API failure could not invalidate an
otherwise complete scan, but the contract did not distinguish that harmless
late failure from GHAS identity or SARIF-preservation failure.

A clean result recovered from a producer job whose overall conclusion is
failure now requires the same three proof units in both paths:

1. `Enforce CodeQL Medium+ SARIF gate` succeeds;
2. `Verify GHAS base/head CodeQL configuration identity` succeeds; and
3. `Preserve CodeQL SARIF evidence` succeeds.

A later failure confined to waking the exact required job remains outside the
scan verdict and may still be reconciled. A Medium+ gate failure remains a
terminal security failure and does not require a successful GHAS identity
step. A producer job whose overall conclusion is success remains authenticated
terminal proof because GitHub completed its non-optional steps successfully.
Missing, duplicate, skipped, cancelled, or failed proof on the failed-job clean
fallback stays fail-closed.

An independent review found a second boundary defect before merge: the
required receiver and coordinator trusted the legacy
`codeql-dispatch/<language>` commit status using only head SHA and publisher.
GitHub retains statuses on a commit, so the same head could reuse a success
from an earlier base, required run, or producer protocol after a PR retarget.
The current producer and consumers now use the v2 receipt exclusively:

- context: `codeql-dispatch/<language>/<live-base-sha>`;
- description: exact head SHA, required run ID, workflow identity, and live
  merge-source SHA; and
- publisher: the existing allowlisted app identity.

The coordinator dispatches `codeql-scan-v2` with the versioned `pr_head`
envelope and live merge source. A legacy or otherwise stale status is ignored,
so the exact run performs or reuses only its own base/source-bound scan.

## Verification and ownership

Executable regressions reproduce the direct receiver and run-wide settlement
false-GREEN surfaces plus stale trusted-status reuse. They are RED on protected
`main` and GREEN with the proof contract. Focused workflow tests pass 91/91;
the complete repository suite passes 3,372 tests with 28 skips and 40 subtests.

The central `.github` workflow remains the canonical owner. Do not copy the
workflow into a consumer, synthesize a status, accept clean SARIF alone, or
weaken the GHAS identity proof. `#2275`/`#2276` still own the real credential
and target permission repair; this change prevents that missing authority from
being mislabeled as a successful required check.
