# strix.yml's repo-wide (not PR-scoped) concurrency group starves required-check evidence org-wide

## Trigger

Item 1 of the standing `/loop` operating prompt asked for a concurrency review
across every central workflow, prompted by the observation that the org-wide
PR queue keeps growing rather than shrinking despite many PRs sitting
`MERGEABLE`. A `<ci-monitor-event>` for `ContextualWisdomLab/.github` PR
#1667 reported `strix` as a failing check; investigating it live surfaced
this finding, which turned out to be much larger in scope than that one PR.

## What was found

`.github/workflows/strix.yml`'s `strix` job concurrency group, for
`pull_request_target` and `repository_dispatch` events, is:

```yaml
group: >-
  strix-${{
    (github.event_name == 'pull_request_target' || github.event_name == 'repository_dispatch') &&
    format('{0}-{1}', github.event_name, github.event.client_payload.target_repository || github.event.pull_request.base.repo.full_name || github.repository) ||
    format('{0}-{1}-{2}', github.event_name, github.repository, github.ref)
  }}
cancel-in-progress: false
```

For `pull_request_target`, this evaluates to `strix-pull_request_target-<repo>`
— **the same literal string for every PR in that repository**, with no PR
number or head SHA. By contrast, `opencode-review.yml` scopes its group by
repo + PR number + exact head SHA, and `noema-review.yml` scopes by repo + PR
number — both correctly isolate one PR's scan from another's. Strix is the
only one of the three central required-review workflows with this gap.

GitHub's documented semantics for `cancel-in-progress: false` allow at most
one **active** run and one **pending** run per group; a new run entering an
occupied group cancels whichever run was already occupying the pending slot
(LIFO for the pending seat, not FIFO). Because the group here is
repository-wide, **any PR's push evicts whatever other PR's Strix scan was
already queued in that same repository**, before it ever starts (zero steps
executed — confirmed directly via the Actions API for several cancelled
runs).

## This is not an oversight — it fixes a real, documented incident, which makes the correct fix harder than "just add the PR number"

`git log -G` on the concurrency block found commit `548a975` (PR #1297,
*"fix(strix): serialize scans and resolve live NVIDIA NIM models"*). Its
message states the root cause directly: *"the per-PR concurrency group let
sibling PRs in one repository scan concurrently; each run retried the shared
NVIDIA NIM key up to three times, producing `litellm.RateLimitError` storms
and fail-closed gate failures on every open PR (observed across
`ContextualWisdomLab/contextual-orchestrator` 2026-08-23/24)."* The
repository-wide group was the deliberate fix for that incident, matching the
inline comment still in the file today (`strix.yml:42-49`). Simply widening
the group back to per-PR (mirroring `opencode-review.yml`) would plausibly
reproduce that exact storm — and the blast radius today is larger than it
was on 2026-08-23/24, because Strix is now a *required* check (via the org's
`CWL Central required workflows` ruleset, id `18156473`) across essentially
every repository in the org, not just one.

## The starvation is real, severe, and confirmed org-wide (not a `.github`-only cosmetic issue)

`strix` is **not** in `.github`'s own required-status-checks list (confirmed
via `gh api repos/ContextualWisdomLab/.github/branches/main/protection`) —
so for `.github`'s *own* PRs, a cancelled Strix run is cosmetic, not
merge-blocking. But the org ruleset `18156473`
(`conditions.repository_name: {include: ["~ALL"], exclude: ["noema",
".github", "IRT-bibliography-set"]}`) makes `strix.yml` a required workflow
in every other org repository, and this same job is what runs for them
(dispatched centrally). Spot-checking three busy sibling repos confirmed the
identical signature:

| Repo | Open PRs | Sample | Result |
|---|---|---|---|
| `contextual-orchestrator` | 30 | #1030 / #1029 / #1028 | pending (in-flight) / **cancelled** / **cancelled** |
| `naruon` | 30 | #1544 / #1543 / #1542 | **cancelled** / **cancelled** / **cancelled** |
| `keyverse` | 24 | #133 / #132 / #130 | queued (in-flight) / **cancelled** / **cancelled** |

Dispatch-history evidence backs the mechanism directly: `contextual-orchestrator`
PRs #968/#964/#958 were all dispatched within the same minute
(2026-09-01 05:08) — #968 and #964 cancelled, #958 failed. `naruon`#1485 was
dispatched twice and cancelled both times.

**Worst-case concrete proof:** `ContextualWisdomLab/.github` PR #1492 has had
**7 of 7** `repository_dispatch` Strix re-attempts cancelled over 37+ hours
(2026-08-31T10:18Z → 2026-09-01T23:59Z), with **zero** successful or failed
(i.e. actually-completed) Strix evidence ever produced for it, and its
current head's check-runs list has no `strix` entry at all (a cancelled
attempt posts no status, since the status-posting step requires
`!cancelled()` at `strix.yml:949,1028`). Other PRs in the same repo do
eventually break through — #1438: 34 attempts (22 cancelled / 8 failure / 4
success); #1176: 25 attempts (21 cancelled / 1 failure / 3 success) — so the
failure mode is *probabilistic starvation*, not a universal deadlock, but for
an unlucky PR it can be indefinite.

## The claimed safety net does not reliably close the gap either

`strix.yml`'s own comment claims: *"the merge scheduler re-dispatches
exact-head evidence when a pending run is superseded... same-head Strix
evidence is still forced at merge time via `repository_dispatch`... so
merged code never loses evidence."* Verified against
`scripts/ci/pr_review_merge_scheduler.py`:

- `strix_evidence_state()` (`pr_review_merge_scheduler.py:1656-1707`) treats
  `cancelled` as a hard non-passing terminal state (grouped with
  failure/error/timeout), not as "pending, will retry" — a PR in this state
  fails the merge gate closed (`:2442`).
- Seeing state `missing`/`failed`, callers invoke `dispatch_strix_evidence()`
  (`:3335`), which fires `repository_dispatch { event_type: "strix-scan" }`
  — the sole place this event type is emitted anywhere in the repo (grep
  confirmed).
- That `repository_dispatch`'s own concurrency group is scoped by
  `event_name` + `target_repository` — **also with no PR number** — so
  different PRs in the same repository needing forced re-evidence still
  collide with *each other* in this "safety net" path, one level removed
  from the original collision. `dispatch_strix_evidence()` does have its own
  `busy_refs` check (`:3363-3382`) intended to avoid firing a second dispatch
  while one is already running for the target repo — but it is a
  check-then-act read (`active_workflow_runs()`), not an atomic lock, and
  (per the observed #1492 evidence) does not appear to account for a run
  already occupying the concurrency group's *pending* (not yet "active")
  slot — which is exactly the slot a colliding sibling PR's dispatch would
  evict.
- `scan-pr-queue`/`org-queue-sweep`'s `review_dispatch_limit` /
  `ORG_SWEEP_REVIEW_DISPATCH_LIMIT` (both default `1`) only bound how many
  *new* dispatches the scheduler fires per sweep — they do not pace or
  serialize the *primary* `pull_request_target` trigger at all (that trigger
  fires directly off GitHub's own PR events, with no scheduler
  intermediary), so they cannot be relied on as the de-facto concurrency
  control for the path that actually causes the storm risk.

Net: the documented guarantee ("merged code never loses evidence") is not
currently reliable — it is *usually* true (most PRs eventually get through,
per the #1438/#1176 evidence) but is not guaranteed, and #1492 is a live
counterexample.

## Why this was not fixed in the same tick that found it

GitHub Actions' native `concurrency:` primitive can express exactly three
regimes: unlimited parallelism (no group), single-flight-with-cancellation
(`cancel-in-progress: true`), or single-flight-with-one-evictable-pending-slot
(`cancel-in-progress: false`, the current choice). None of these can express
"bounded to N concurrent, first-in-first-out, no eviction of others" — the
actual shape needed here. Two considered options and why neither was shipped
without more evidence or design work:

1. **Just widen the group to per-PR** (mirror `opencode-review.yml`) — would
   very plausibly reproduce the exact `litellm.RateLimitError` storm
   documented in PR #1297, at a larger blast radius than that incident had
   (Strix is required org-wide now). Rejected without real evidence it's
   safe.
2. **Bucket the group into K parallel lanes** (hash PR number mod K) to
   bound concurrency to K instead of 1, trading some rate-limit risk for
   meaningfully better breakthrough odds — searched `docs/doctoring/`,
   `docs/adr/`, and the workflow/scripts themselves for any documented safe
   concurrent-request capacity for the shared `NVIDIA_NIM`/`orchestrator/free`
   path and found none. Picking a `K` without that data would be exactly the
   "arbitrary constant, not verified against real data" mistake this repo's
   own operating history has already flagged as a recurring error to avoid.

A genuine fix needs either (a) real capacity/rate-limit data for the
`orchestrator/free` → NVIDIA NIM path to size a bounded-concurrency lane
count responsibly, or (b) a deliberately designed fair-queueing mechanism
(e.g. an external per-repository lease/semaphore with TTL-based reclamation,
sized to whatever (a) determines) — both larger, correctness-and-security-
sensitive engineering efforts than an improvised same-tick diff to a
required check spanning the entire organization should attempt. This record
exists so that work can be scoped and picked up deliberately rather than
guessed at under time pressure.

## What NOT to do

- Do not PR-scope `strix.yml`'s `pull_request_target` concurrency group
  without first getting real capacity data or building a bounded-and-fair
  replacement — it will very likely reproduce the 2026-08-23/24 incident,
  now with org-wide blast radius.
- Do not treat the "forced re-dispatch at merge time" comment in
  `strix.yml` as a reliable guarantee — it is currently racy for PRs unlucky
  enough to keep colliding with siblings in the same repository (see #1492).
- Do not conclude backlog item 13 ("Strix/OpenCode/Noema concurrency
  cancel-on-push") is fully resolved on the strength of the *same-PR*
  cancel-on-push behavior alone (which genuinely is correct and already
  verified for all three) — this is a *different*, *cross-PR* concurrency
  defect, specific to Strix, not covered by that earlier verification.

## Suggested next steps (not yet started)

1. Obtain real concurrent-request capacity data for the `orchestrator/free`
   gateway path Strix uses (from CO's own metrics/logs, or a deliberate
   controlled load test), to responsibly size any bounded-concurrency
   change.
2. Design a genuine bounded-and-fair mechanism sized to that data — bucketed
   concurrency groups are the simplest fit for GitHub Actions' native
   primitives if a small K turns out to be safe; an external lease/semaphore
   is the more robust (but heavier) alternative if true FIFO fairness is
   required.
3. Independent of (1)/(2): fix `dispatch_strix_evidence()`'s busy-check to
   also treat a same-repository run already occupying the concurrency
   group's *pending* slot as busy (not just a run that is actively
   in-progress), so the safety-net path stops contributing to its own
   cross-PR collisions even before the harder primary-trigger question is
   resolved.
4. Consider whether repository_dispatch-triggered re-evidence dispatches
   should be prioritized by how long a PR has been waiting (oldest-starved
   first) rather than effectively randomly by dispatch order, once (2) or
   (3) provides a place to plug such a policy in.
