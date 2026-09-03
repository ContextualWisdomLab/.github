# `noema-review.yml`'s cleanup job didn't cover `repository_dispatch`, and its concurrency group has an unmitigated pending-slot eviction race

## Trigger

An Autofix `<ci-monitor-event>` on `.github` PR #1661 surfaced a Devin Review
pass with two `BUG`-kind findings against `noema-review.yml`, both in the
concurrency/cleanup machinery this same PR had earlier fixed for a different
deadlock (see `docs/product-technical-gap-baseline.md`'s "concurrency
deadlock pattern" entries and the in-file comment on `noema-review`'s own
`concurrency:` block for that history).

## What was found (comment 4): the cleanup job never covered `repository_dispatch`

`noema-review.yml`'s `on:` block accepts two trigger types:

```yaml
on:
  pull_request_target:
    types: [opened, synchronize, reopened, ready_for_review, closed]
  repository_dispatch:
    types: [noema-review]
```

`repository_dispatch` is the documented "retry entrypoint" (see the file's
own `# Default-branch-only retry entrypoint` comment) — used when an agent
mention or a manual retry needs to re-run a review outside the normal PR-push
path (`agent-mention-noema-dispatch.yml` is the only sender today).

The `noema-review` job's concurrency group is scoped by **target repository +
PR number**, computed identically regardless of which trigger produced the
event:

```yaml
group: >-
  noema-review-${{
  github.event.pull_request.base.repo.full_name ||
  github.event.client_payload.target_repository || github.repository }}-${{
  github.event.pull_request.number ||
  github.event.client_payload.pr_number ||
  github.run_id }}
cancel-in-progress: false
```

So a `pull_request_target` push and a `repository_dispatch` retry for the
*same* PR land in the *same* group and can block each other. But
`cancel-superseded-noema-runs` — the job that live-reverifies and cancels a
genuinely stale *active* run so a newer one isn't stuck queued behind it
forever (Noema inference has no wall-clock deadline by design,
`docs/product-goal-directive.md` §8) — only ran for `pull_request_target`:

```yaml
if: >-
  github.event_name == 'pull_request_target'
  && github.event.action != 'closed'
  && github.event.pull_request.head.repo.full_name == github.repository
```

A `repository_dispatch` retry arriving while an older `pull_request_target`
push's `noema-review` job is still active had no path to ever cancel that
older run — it would sit pending indefinitely, exactly the failure mode the
whole cleanup-job split was built to prevent, just reached from an angle the
original fix didn't cover.

### Fix

Extended the `if:` to also match `repository_dispatch`, and the job's `env:`
to derive `TARGET_REPOSITORY`/`PR_NUMBER`/`EXPECTED_HEAD_SHA` from
`github.event.client_payload.*` as a fallback — the identical fallback chain
`noema-review`'s own `env:` block already uses, so both jobs agree on these
values for either trigger type. Added an explicit `if: env.PR_NUMBER == ''`
skip step (mirroring `noema-review`'s own "Skip events without pull request
context" step) so a malformed dispatch payload degrades to a warning instead
of the job crashing on an empty PR number mid-`jq` filter.

No new trust check was needed for the `repository_dispatch` branch:
`repository_dispatch` can only be sent by a principal with this repository's
write access (GitHub's own authorization boundary for the dispatches
endpoint) — the same trust level `noema-review`'s own `if:` already extends
to it without an additional `head.repo.full_name`-style check.

## What was found (comment 5): a delayed old-head trigger can evict the *current* head's pending job, not just cancel a stale active one

This is the harder finding, and it survives the fix above.

`noema-review`'s job-level concurrency group uses `cancel-in-progress:
false`, deliberately — the in-file comment explains this was chosen over
SHA-scoping specifically so a late, out-of-order event for an older head
could never preempt the *active* run for a genuinely newer head, without the
capacity cost of giving every push its own group under the org's saturated
Actions ceiling. That reasoning is correct as far as it goes, and independent
of `cancel-in-progress`, GitHub's concurrency groups still enforce a
**single pending slot**: at most one job may be queued behind the active one,
and a new trigger requesting the group evicts whichever job currently holds
that slot.

The existing in-file comment already acknowledges this eviction happens and
argues it's *safe*: "rapid pushes still coalesce down to 'at most one running
+ one pending' without any SHA segment." That argument implicitly assumes
arrival order matches push recency — i.e., whichever trigger arrives *last*
is the *newest* head, so evicting the previous pending job only ever discards
something already-superseded.

That assumption doesn't hold under delayed/out-of-order webhook delivery,
which is exactly the condition this org has been fighting all day under
Actions queue congestion. Concretely:

1. Push A (older head) → `noema-review` job A becomes **active** in the
   group.
2. Push B (current/newest head) → job B can't start (A is active); GitHub
   queues it as the single **pending** job.
3. A *delayed* webhook for some even-older event A′ (sent before A, delivered
   late) finally arrives → job A′ requests the same group. GitHub's rule
   evicts whichever job currently holds the pending slot — **B**, not A′ —
   because eviction is based on arrival order at the platform, not on any
   notion of which head is actually newest. Job B is gone before it ever ran
   a single step.
4. When A finishes, A′ is promoted to active. Its own "Reject a stale
   trigger before credential or model setup" step re-fetches the live PR
   head, correctly finds it doesn't match A′'s own head, and exits cleanly —
   so nothing gets falsely approved. But that self-check only protects a run
   that actually gets to *execute*. It cannot protect B, which was evicted
   before existing as anything the workflow can introspect.

Result: the PR's current head (B) can end up with no in-flight and no
completed Noema review, and nothing in the workflow observes this — the
required check may simply stay `queued`/`Waiting for status to be reported`
indefinitely, or silently miss coverage, depending on how GitHub renders an
evicted run's non-existent conclusion.

### Why this was not fixed outright in this pass

Two candidate complete fixes were considered, neither implemented here:

- **Self-dispatch a retry** (`cancel-superseded-noema-runs` detects the gap
  and re-sends a `repository_dispatch` for the live head) needs
  `contents: write` on this job. It currently runs on `pull_request_target`
  with only `actions: write`/`contents: read`/`pull-requests: read`.
  `docs/CWL-MASTER-CONTEXT.md`'s binding conventions caution against widening
  a `pull_request_target` job's token to repository-write permission — the
  immediate injection risk is mitigated by `pull_request_target` always
  running the *base* branch's workflow definition regardless of what a PR's
  own diff contains, but that's a narrower guarantee than "safe to grant
  write broadly," and this wasn't verified carefully enough to ship in the
  same pass as the detection work below.
- **A new `workflow_dispatch` trigger** would reuse the `actions: write`
  already granted (no permission widening), but needs matching `if:`/`env:`
  changes in at least the run-name, `cancel-superseded-noema-runs`'s own
  `if:`, `noema-review`'s `if:`/`env:`, and the concurrency group expression
  — a third event-type branch threaded through several places in an already
  dense file, not something to add and ship unreviewed in the same pass as
  everything else in this record.

Either is a genuine redesign, matching Devin's own framing of this finding
("Redesign pending admission...") rather than a one-line patch — the same
posture this session has taken consistently for comparably deep open design
questions (e.g. the naruon/keyverse WebAuthn-vs-Authorization-Code+PKCE
question tracked separately).

### What was done instead: detection, not recovery

Added a step, `Detect a current-push review evicted from its pending slot`,
to `cancel-superseded-noema-runs` (runs `if: always()`, after the existing
cancel loop). It reads this *same* run's own job list
(`GET /repos/{repo}/actions/runs/{run_id}/jobs`, already covered by the
job's existing `actions: write` permission — no elevation) and inspects the
sibling `noema-review` job's status.

This has a known, documented blind spot: it only catches an eviction that
has *already happened* by the time this step runs. `cancel-superseded-noema-runs`
runs quickly and unrestricted, so an eviction occurring after it exits (e.g.
while the *other* run is still active, possibly for a long time given no
wall-clock deadline) is not observed by this check. Closing that fully needs
either of the two redesigns above, or an external periodic reconciler (e.g.
extending `pr-review-merge-scheduler.yml`'s sweep to notice PRs whose current
head lacks any completed-or-in-flight Noema review) — confirmed via grep that
no such reconciler exists today; `agent-mention-noema-dispatch.yml` is the
only sender of the `noema-review` `repository_dispatch` type, and it's purely
mention-triggered, not periodic.

### Adversarial verification found the first version of the detection step was actively wrong, not just incomplete

Before committing, this exact diff was run through 3-lens adversarial
verification (`Workflow`, one agent per lens: GitHub Actions platform
semantics, bash/YAML correctness, completeness against the original
findings). All three independently converged on the same real, moderate-
severity bug in the first draft of the detection step: it treated the
sibling `noema-review` job's `conclusion == "cancelled"` as near-proof of a
pending-slot eviction, but that exact conclusion is *also* produced by two
entirely routine, non-buggy paths already in this file —

- a **later** run's own `cancel-superseded-noema-runs` job cancelling
  *this* run's `noema-review` job because a newer push legitimately
  supersedes it (the everyday multi-push case this whole system exists to
  handle), and
- `cancel-closed-pr-runs` cancelling this run because the PR simply closed.

Both leave `conclusion: cancelled` indistinguishable, in the first draft's
logic, from a genuine eviction — meaning the step as first written would
have fired misleading `::error::` alerts, with actively wrong "manually
re-trigger" guidance, on ordinary PR activity rather than only the rare race
it was built to catch. (One lens additionally found: the jq call reading the
conclusion was an unguarded command substitution under `set -euo pipefail`,
contradicting the step's own "never fails the job" claim if the Jobs API
ever returned an unexpected shape; and an unrelated, lower-severity
consistency gap — `TARGET_REPOSITORY`, now reachable from
`repository_dispatch`'s sender-controlled `client_payload` by this same
diff, was interpolated into `gh api` calls without the same
`^ContextualWisdomLab/[A-Za-z0-9_.-]+$` format check `noema-review`'s own
credential step already applies.)

Fixed by disambiguating on two signals the Jobs API already returns, rather
than on `conclusion` alone: `started_at` (a job cancelled while genuinely
*active* — the routine-supersession case — has one; a job evicted from the
pending slot before ever running does not), and, only when `started_at` is
absent, a live re-check of the PR's own state (a closed PR needs no review
regardless of why its run was cancelled — this also covers
`cancel-closed-pr-runs` directly cancelling a still-*queued*, never-started
run, which the `started_at` check alone cannot distinguish from a real
eviction, since GitHub's "Cancel a workflow run" endpoint documents
cancelling either an `in_progress` or a `queued` run). Only when the sibling
job never started **and** the PR is still open does the step now alarm. Also
added the missing `TARGET_REPOSITORY` format check and guarded the
previously-unguarded jq call with the same `if ! ...; then ::warning::;
exit 0; fi` pattern already used everywhere else in this job.

## Evidence

- `python3 -c "import yaml; yaml.safe_load(...)"` — the edited
  `noema-review.yml` parses as valid YAML.
- Every `run:` block in the file (not just the edited job) was extracted via
  PyYAML and checked with `bash -n` — all pass, including the bash blocks in
  the edited job, both before and after the adversarial-verification fixes.
- `scripts/ci/test_strix_quick_gate.sh` run in full before and after: the one
  pre-existing failure it reported (a stale scheduler assertion, see the
  sibling doctoring/gap-baseline entry for that fix) is unrelated to this
  file; re-run after all fixes in this pass confirmed clean.
- Full repository test suite (`PYTHONPATH=. python3 -m pytest tests -q`)
  passed both before this record was written (no Python source changed by
  the workflow-YAML-only finding) and again after fixing
  `test_pr_review_fix_hourly_contract.py`'s assertion to match the
  `requirements-opencode-review-ci-hashes.txt` lock-check fix from the
  sibling gap-baseline entry — 2730 passed, 1 skipped, 21 subtests passed.
- 3-lens adversarial verification (`Workflow`, `wf_8ceb0fdf-5ce`) re-confirmed
  the underlying detection mechanism is sound (the Jobs API does surface an
  evicted-while-pending job with `conclusion: cancelled` and no `started_at`;
  this is not dead code) and independently traced the real
  `repository_dispatch` sender (`agent-mention-noema-dispatch.yml`)'s actual
  `client_payload` shape against the new env-derivation fallback chain,
  confirming an exact key-name match.

## Suggested next steps (not yet started)

- Design and adversarially verify one of the two full-fix candidates above
  (self-dispatch with a narrowly-justified `contents: write` grant, or a new
  `workflow_dispatch` trigger) before attempting it live on a required,
  org-wide gate.
- Alternatively or additionally: extend `pr-review-merge-scheduler.yml`'s
  existing sweep machinery to detect "PR's current head has no completed or
  in-flight Noema review" and dispatch one — this would also close the
  blind-spot window the detection-only step above leaves open, and is a more
  natural fit for a periodic reconciler than cramming it into a per-push
  cleanup job.
- Consider whether `strix.yml`/`opencode-review.yml` share this same
  pending-slot eviction exposure — both also use `cancel-in-progress: false`
  with PR-scoped (not SHA-scoped) groups per this session's own earlier work
  on them. Not checked in this pass.
