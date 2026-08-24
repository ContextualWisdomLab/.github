# RankWeave hourly review-repair caller

## Decision

ContextualWisdomLab operates one protected hourly caller for
`ContextualWisdomLab/RankWeave`. The caller runs at minute 33, delegates to the
product-neutral central review-fix scheduler, inspects at most 50 open pull
requests, and dispatches at most one bounded repair per heartbeat.

The caller does not implement review or mutation logic itself. It keeps
RankWeave's standard-library-only runtime independently operable while
centralizing privileged automation in `ContextualWisdomLab/.github`. The
reusable worker performs exact-head root-cause analysis, tests remediation
feasibility, and edits only when one small reversible action can change the
diagnosed cause inside its sealed writer authority.

RankWeave previously attempted this role itself, from a `repair-review-feedback`
job inside its own `hourly-commercialization-loop.yml`, calling
`pr-review-fix-scheduler.yml` by a cross-repository pinned commit SHA. That
caller shape predates the same-repository trusted-source hardening in
`pr-review-fix-scheduler.yml` (`github.repository` must equal
`ContextualWisdomLab/.github`) and can never satisfy it, so every run failed
before any job was scheduled ("workflow file issue", zero jobs created). This
caller replaces that dead job with the same pattern already proven for
fast-mlsirm, DiskSage, and every other product repository.

## Root-cause analysis and remediation feasibility

The prior unbounded loop design combined complete queue drainage, indefinite
check polling, product-gap discovery, implementation, review, merge, and release
in one hourly invocation. That design was not operationally realistic: one
OpenCode or GitHub Actions cycle can outlive the next heartbeat, and external
approval, runner capacity, provider latency, or rate limits cannot be repaired
by inventing a repository change.

The replacement therefore enforces these transitions:

1. Refetch the exact live head, base, reviews, checks, changed paths, and writer
   state.
2. Establish the causal chain rather than repeat the terminal symptom.
3. Enumerate materially distinct minimal remedies.
4. Reject remedies that lack writer authority, cross sealed paths, require
   unavailable credentials or protected-setting changes, violate stack order,
   cannot be verified, or do not alter the diagnosed cause.
5. Dispatch at most one feasible repair. Otherwise leave the tree unchanged so
   another eligible pull request can be considered by a later heartbeat.

A queued or pending check remains a merge blocker but is not itself a code
finding. The independent non-author approval remains an external authorization
gate and is never synthesized by the repair worker.

## Cadence and concurrency

The caller uses a single concurrency group and `cancel-in-progress: false`.
This preserves an in-flight bounded RCA instead of discarding its evidence when
the next hourly heartbeat arrives. The reusable scheduler cancels only its own
superseded short queue scan; the separately dispatched per-PR repair worker and
this product caller remain non-cancelling. The central scheduler and per-PR
worker also retain exact-head leases and mutation limits.

The caller sets a **two-hour same-head retry floor**. Central OpenCode, Strix,
and NVIDIA NIM review can legitimately approach two hours, so an hourly
redispatch of the same unchanged head would create duplicate writer pressure
rather than faster remediation. A later hourly scan can still select another
eligible pull request.

GitHub scheduled workflows can be delayed under load and execute only from the
default branch. Consequently, the cron expression is a heartbeat rather than a
real-time service-level promise. Exact-head state, not elapsed wall-clock time,
controls every mutation and merge decision.

## Credentials

The caller forwards only `PR_REVIEW_MERGE_TOKEN` and `OPENCODE_APPROVE_TOKEN`
by name; it does not use `secrets: inherit` and never sees
`NVIDIA_NIM_API_KEY` or `COPILOT_GITHUB_TOKEN`. `COPILOT_GITHUB_TOKEN` remains
unused across every ContextualWisdomLab review and repair path.

## References

Cormack, G. V., Clarke, C. L. A., & Buettcher, S. (2009). Reciprocal rank
fusion outperforms Condorcet and individual rank learning methods.
*Proceedings of the 32nd International ACM SIGIR Conference on Research and
Development in Information Retrieval*, 758-759.
https://doi.org/10.1145/1571941.1572114

APA 7th references govern every scientific or standards claim documented for
this caller, matching the citation discipline already established across
ContextualWisdomLab's hourly review-repair doctoring.
