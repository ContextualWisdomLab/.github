# Owner brief: plan-ceiling residual after job folding (2026-09-18)

- **Date:** 2026-09-18
- **Audience:** org owner (billing / Actions concurrency decision)
- **Purpose:** one-page decision brief. Residual queue pain after folding and
  coalesce repairs is still the **plan concurrent-job ceiling**, not a missing
  workflow kill-switch.
- **Sources:** ContextualWisdomLab/.github#2252 (remeasure), #2249 (fail-open /
  re-enable gate grounding), #2233 (fail-open coalesce when tick is stale), plus
  the in-tree doctoring records those PRs cite.
- **Non-goals of this brief:** flipping `OPENCODE_REVIEW_COALESCE_ENABLED`,
  turning workflows off, adding symptom caps that weaken required gates, or
  claiming a new admission bug beyond what `#2242` already fixed.

### Owner options at a glance (headroom, not kill-switches)

Concrete concurrent-job headroom choices for the owner; full table below.

| ID | Owner action | Role |
|---|---|---|
| **A** | Raise plan concurrent-job quota (~60 today; verify Billing UI) | Direct ceiling lift |
| **B** | Add a separate runner pool for a defined heavy job class | Offload shared hosted slots |
| **C** | Keep ceiling; cut arrival via stale-PR supersede + proven superseded-head cancel only | Arrival hygiene (complements A/B) |
| **D** | Keep `OPENCODE_REVIEW_COALESCE_ENABLED=false` until A/B/C yield headroom (or explicit fail-open accept) | **Recommended default** |
| **E** | Cap/disable required review or security workflows | **Reject** — symptom kill-switch, weakens gates |

Do **not** treat workflow kill-switches or a coalesce flip under ~10³ queued as
the residual fix. Coalesce stays **false** from this brief.

## Snapshot (measured)

Full 66-repo REST census and job-level admission samples from the post-folding
remeasure carried by #2252
(`docs/doctoring/actions-queue-wait-24h-remeasure-post-2244-20260917.md`,
window closed ~`2026-09-17T20:15Z`, ~4h after `#2242`):

| Metric | Value |
|---|---|
| Org `in_progress` (sum of runs) | **34** |
| Org `queued` (sum of runs) | **~2,090** |
| Mid-day same day (`#2237` / earlier remasure) | 48 in_progress / 1,911 queued |
| Open PRs org-wide | **~4,256** (was ~4,288 mid-day) |
| Plan concurrent-job ceiling (billing UI, 2026-09-03 primary) | **~60** |
| `opencode-review-dispatch` first-job admission | **p50 ~3.2h / p95 ~3.3h** |
| Coalesce ticks with flag `false` after `#2242` | **skipped in ~1s** (not queued) |
| `OPENCODE_REVIEW_COALESCE_ENABLED` | **`false`** (unchanged) |

Shape is unchanged from
`docs/doctoring/actions-plan-concurrency-ceiling-20260903.md`: low-double-digit
concurrent work against ~10³ queued. That is the signature of a hard org-wide
concurrent-job quota, not of a single defective workflow.

## What engineering already did (cause-adjacent, not ceiling-lifting)

| Change | Effect | What it did **not** do |
|---|---|---|
| `#2228` / `#2230` job folding | Removed same-trust-level `needs:` hops on OpenCode Review Dispatch / required bootstrap; under saturation that hop previously cost **hours** of pure queue wait per edge (`actions-capacity-root-cause-20260917.md`: ~97.5% of a ~14h wall clock was inter-job wait). | Did not raise how many jobs can run at once. First-job admission remains ~**3.2h**. |
| `#2233` fail-open coalesce | When coalescing is on, synchronize dispatch does **not** wait forever on a missing recent successful tick (`DEFAULT_COALESCE_TICK_MAX_AGE_SECONDS=600`). Grounded further in #2249. | Does not drain the org backlog; irrelevant while the flag stays `false`. |
| `#2242` job-level coalesce gate | Disabled ticks skip **before** runner admission (1s `skipped`), so inert five-minute crons no longer sit multi-hour `queued` competing for the ~60 slots. | Does not add headroom for real review/dispatch work. |
| Hygiene / evidence merges same day | Strix/Noema correctness; schedule observability experiments | Not capacity. |

Net: engineering removed **repeatable multi-hour hops** and stopped **wasting slots on inert ticks**. The residual is **admission under the plan ceiling**.

## Why coalesce stays `false`

Re-enable criteria live in
`docs/doctoring/coalesce-tick-post-2242-live-verify-20260917.md` (and #2249's
contract/docs grounding of N=600). Must-haves for gate health are largely met
(job-level skip-before-admission proven live; fail-open present on `main` via
#2233). **Should-have capacity is not met:**

- Prefer enable when org `in_progress` is clearly below ceiling **and** queued
  depth is not order-of-10³, **or**
- Explicitly accept that enabled ticks may still queue for hours and that
  #2233 fail-open will temporarily bypass coalesce deferral until a `success`
  tick completes.

Today: **~34 in_progress / ~2,090 queued** against ~60. Enabling under that
depth without accepting fail-open-as-normal recreates "reviews never dispatch"
rather than "inert ticks clog the queue." This brief therefore **leaves the
variable false** and does not authorize a flip.

## Owner options (fix the cause, not the symptom)

Do **not** treat "turn off required workflows," "cap model jobs to hide wait,"
or "flip coalesce under saturation" as the decision. Those attack symptoms or
reintroduce known failure modes. Options that address **concurrent-job budget /
plan headroom**:

| Option | What the owner does | Expected effect on residual | Cost / risk | Notes |
|---|---|---|---|---|
| **A. Raise plan concurrent-job quota** | Confirm exact ceiling on org Settings → Actions / Billing; purchase higher included concurrency or a tier that lifts the ~60 job cap. | Directly increases concurrent throughput; only lever that lifts the hard ceiling documented since 2026-09-03. | Billing. | REST cannot read the quota; owner must verify the UI number before purchase. |
| **B. Add a separate runner pool** | Provision self-hosted / larger runners with their **own** capacity pool for a defined job class (e.g. long AI review dispatch), leaving hosted quota for everything else. | Moves a heavy class off the shared ~60 hosted slots. | Ops + trust boundary (who may run on those runners). | Hosted org runners API was `total_count=0` at remasure — no separate pool today. |
| **C. Accept ceiling; buy time with PR load** | Keep ~60; aggressively close/supersede stale open PRs (~4.2k feeding required workflows) and cancel only **proven** superseded-head queued runs (event-specific evidence — no org-wide sweep). | Reduces **arrival rate** into the same ceiling; does not raise concurrency. | Process discipline; wrong cancellation discards live work. | Complements A/B; does not replace them if admission p50 stays multi-hour. |
| **D. Defer coalesce enable until headroom** | Leave `OPENCODE_REVIEW_COALESCE_ENABLED=false` until A/B/C produce clearer headroom **or** owner explicitly accepts #2233 fail-open under deep queue. | Avoids recreating "dispatch waits on ticks that never admit." | Delayed coalesce benefit on push bursts. | **Recommended default** until A or B lands. |
| **E. Symptom caps / disable workflows** | Cap or turn off required review/security workflows to shrink queue depth. | Appears to drain queue; **weakens gates** and hides ceiling pressure. | Governance / security regression. | **Out of scope / reject** for this residual. |

### Recommended owner sequence

1. Re-attest the concurrent-job number on the billing UI (still ~60 from 2026-09-03
   primary evidence unless changed).
2. Choose **A** and/or **B** if multi-hour first-job admission (~3.2h) is
   unacceptable for product review SLA.
3. Use **C** in parallel for arrival-rate hygiene.
4. Keep **D** until census shows material headroom; then follow the flip
   procedure in the post-`#2242` verify record (watch for `conclusion=success`
   ticks; rely on #2233 fail-open if a tick queues).

## Explicit non-actions for agents

- Do **not** set `OPENCODE_REVIEW_COALESCE_ENABLED=true` from this brief.
- Do **not** disable or path-filter required workflows to "fix" queue depth.
- Do **not** add model-path timeouts or concurrency caps as a substitute for
  plan headroom (`docs/product-goal-directive.md` §8; ADR-0030 scope).
- Do **not** treat job folding as unfinished: the remaining cost is first-job
  admission under the ceiling, which folding cannot remove.

## Citations

| Ref | Role |
|---|---|
| ContextualWisdomLab/.github#2252 | Post-`#2228`–`#2244` remasure: **34 / ~2090**, ~**3.2h** first-job admission, coalesce 1s skip |
| ContextualWisdomLab/.github#2249 | Grounds coalesce fail-open N=600 + re-enable gate; flag left **false** |
| ContextualWisdomLab/.github#2233 | Fail-open coalesce when no recent successful tick |
| `docs/doctoring/actions-plan-concurrency-ceiling-20260903.md` | Original ~60 plan-ceiling diagnosis |
| `docs/doctoring/actions-capacity-root-cause-20260917.md` | Inter-job queue wait vs model time |
| `docs/doctoring/coalesce-tick-post-2242-live-verify-20260917.md` | Why enable is still blocked on capacity |
| `docs/adr/0030-ci-centralization-scope-given-plan-ceiling.md` | Centralization cannot lift the ceiling |

## Audit trail

- Numbers in the Snapshot table are copied from the #2252 doctoring remasure
  (measurement ~`2026-09-17T20:07Z`–`20:15Z`), not re-sampled in this docs-only
  brief.
- This file is documentation only; no workflow, variable, or gate change.
