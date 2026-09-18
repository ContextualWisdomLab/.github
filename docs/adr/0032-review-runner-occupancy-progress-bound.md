# ADR-0032: Review runner occupancy is bounded by progress and admission, never by elapsed inference time

- **Status:** Proposed
- **Date:** 2026-09-13 (reconstructed 2026-09-15 as #2207; renumbered and extended 2026-09-18 after ADR-0030 was assigned to CI centralization scope)
- **Scope:** `scripts/ci/contextual_orchestrator_review_launcher.py` (serving `ModelClient` construction and `_preflight_with_fallback` continuation), the vendored `contextual_orchestrator` transport, `.github/workflows/noema-review.yml` (deliberately unbounded review job), `.github/workflows/opencode-review-coalesce-tick.yml` (schedule admission under the plan concurrent-job ceiling)
- **Amends:** nothing. Extends ADR-0003's 2026-08-31 amendment ("model inference has no repository- or run-level deadline") by naming what *may* be bounded. ADR-0005's fixed wall-clock budgets remain historical and are not restored. Complements ADR-0030 (centralization cannot lift the plan ceiling) and ADR-0031 (capacity recovery is re-dispatch, not in-job model wait).
- **Numbering note:** Predecessor drafts used the number ADR-0030 for this decision. On current `main` that number is occupied by `0030-ci-centralization-scope-given-plan-ceiling.md`. This record is therefore ADR-0032; content succession from Draft #2140 / earlier #2207 heads is the decision and evidence, not the digit.

## Problem

Two distinct occupancy failures are easy to confuse, and both look like "the review took hours":

1. **Transport / model path.** The vendored gateway is about to stop bounding a single provider call, and nothing below GitHub's six-hour job ceiling replaces it.
2. **Actions admission.** Under the org plan concurrent-job ceiling (~60), scheduled and required workflows sit `queued` for hours before a runner is admitted — wall time that is not model work at all.

`contextual-orchestrator#1118` changed `ModelClient.__init__`'s `timeout` default from `int = 90` to `float | None = None`. That removal is correct: an implicit 90-second cap on the inference path is exactly what ADR-0003's 2026-08-31 amendment forbids, and it is the same class of decision `#1889`, `#1890`, and `#1892` were reverted for reintroducing (`#1891`, `#1895`). The removal is not the problem. What it exposes is.

Three layers each decline to bound the call, and the combination was never designed:

| layer | bound after the pin advance |
|---|---|
| `ModelClient` default | `timeout: float \| None = None` |
| `contextual_orchestrator_review_launcher.py:1240` (serving client) | passes no `timeout`, so it takes the library default |
| `.github/workflows/noema-review.yml:261` | *"No job-level `timeout-minutes` here, deliberately."* |
| GitHub job ceiling | 6 h |

### What the 90-second default is currently doing

`#1884` head `e85fc437`, [run 34732993973](https://github.com/ContextualWisdomLab/.github/actions/runs/34732993973), sidecar stderr artifact `10310273053`. Serving phase 02:41:17Z → 02:56:27Z, 907.3 s, terminal `HTTP 503`. The job log shows none of this; the uploaded `noema-sidecar-evidence` artifact carries the whole trace, and reading the job log instead is what makes this failure look like a single hung call.

Fifteen provider attempts inside that window, across two agents on two credential accounts:

```
10x  nvidia_nim     / deepseek-ai/deepseek-v4-flash-0731
 5x  nvidia_nim_sub / deepseek-ai/deepseek-v4-pro-0813
```

Measured attempt-to-failure durations:

```
  90.0s   90.0s   22.0s   90.0s   90.0s
  90.0s   90.0s   90.0s   90.0s    0.0s
```

Eight of ten land on exactly 90.0 s. That is not providers answering — it is the default expiring. Roughly 720 of the 907 seconds is the cap firing against endpoints that accepted a connection and then delivered nothing. **The cap is the only thing converting a no-observable-progress request into a bounded, diagnosable event**, and it is leaving.

Two further behaviours the same trace records, both relevant to the decision below:

- **The breaker resets straight back into the failing route.** `circuit_failure` ×10, `circuit_opened` ×2 (at `failures=3.0 threshold=3`), `circuit_reset` ×2 after `reset_seconds=30.0`, `circuit_cleared` ×1. After each reset the ranking hands back the same agent. `failures=4.0 threshold=3` also appears without a second open, so the counter accounting is worth its own look.
- **Two ready routes were never tried.** `nvidia_nim/meta/llama-3.2-11b-vision-instruct` and `nvidia_nim_sub/meta/llama-3.2-11b-vision-instruct` were both `ready` at preflight and appear zero times in the serving phase, while the two deepseek routes were cycled fifteen times.

### Why the obvious model-path fix is forbidden

Passing an explicit `timeout=` at the launcher's serving call site would reinstate the reverted cap under a different name. `docs/product-goal-directive.md` §8 accepts that a model path may take more than two hours and states that speed is not a core consideration; ADR-0005 records that fixed wall-clock budgets "failed for legitimately slow models." This ADR does not reopen that, and the same trace shows why it should not: `google/gemma-4-31b-it` was rejected at preflight after exactly 90.0 s with `TimeoutError`. Nothing in the evidence distinguishes that from a model that was simply going to take 91 seconds. The cap is discarding routes on no evidence of failure.

So the org currently has both defects at once: a cap that kills slow-but-working models, and, once it is removed, no explicit occupancy boundary for a request that makes no observable transport progress.

### Why scheduled workflows queue for hours (Actions layer)

This is a different failure mode with the same wall-clock symptom. Measured on 2026-09-17
([`docs/doctoring/actions-capacity-root-cause-20260917.md`](../doctoring/actions-capacity-root-cause-20260917.md)):

- OpenCode Review Dispatch run `34931908846` spent ~13h57m wall time of which **~21 minutes (2.5%)** was job execution and **~13h36m (97.5%)** was inter-job wait for a fresh runner between `needs:` edges.
- The same four-job chain on a lighter day (`34756591400`) finished in 14m40s. Workflow logic did not change; org-wide saturation did.
- Plan concurrent-job ceiling is ~60 (`docs/doctoring/actions-plan-concurrency-ceiling-20260903.md`); censuses show single-digit / low-double-digit `in_progress` against ~10³ `queued`. ADR-0030 already records that workflow consolidation cannot lift that ceiling.

Schedule delivery compounds this. Cron `*/5` does not guarantee a runner every five minutes: under saturation, GitHub delays schedule delivery itself (documented gaps of tens of minutes to hours in
[`docs/doctoring/coalesce-tick-post-2242-live-verify-20260917.md`](../doctoring/coalesce-tick-post-2242-live-verify-20260917.md)
and `docs/doctoring/actions-queue-24h-remeasurement-20260917.md`). Missed intervals are not backfilled as a stack of five-minute runs. A job that has already been admitted into the shared queue waits behind every other org job competing for the same ~60 slots — including an *inert* coalesce tick if its skip gate is evaluated only after admission (`#2232` → run `35219385415` queued ~3.5h with `OPENCODE_REVIEW_COALESCE_ENABLED=false`; repaired by `#2242`).

**Diagnosis rule:** multi-hour review duration is first presumed inter-job / schedule admission wait under the plan ceiling, not model API latency, until job-level timestamps prove otherwise. Model-path timeouts remain forbidden regardless of that wait.

## Constraints

1. Elapsed inference time must never become a model-failure verdict (ADR-0003 2026-08-31; directive §8).
2. A route must not be dropped, penalised, or circuit-broken for being slow.
3. A review runner must not be held indefinitely by a provider that has stopped responding.
4. Whatever bound exists must be explainable from evidence in the sidecar artifact, not inferred from wall-clock alone.
5. Actions occupancy is repaired at **admission / continuation** boundaries (job-level skip, concurrency coalescing, fail-open re-dispatch) — never by converting queue wait or inference duration into a model-failure verdict.
6. Schedule observability must not force inert work onto the runner queue.

Constraints 1–2 and 3 are only in tension if "how long has this taken" is the sole available signal. It is not.

## Decision

**Bound progress and admission, not elapsed inference time.**

### A. Transport / model occupancy (gateway and review jobs)

1. **Idle-socket bound, reset on every byte received.** Within the external job boundary, a response that is actively streaming is never interrupted by the idle-socket bound, regardless of total inference duration — a two-hour generation completes if that external boundary remains available. A job ceiling or a separately classified runner-reclamation event may still terminate the request; neither event is a model-failure verdict and neither may feed route ranking. Before the first response byte, absence of bytes is classified only as a **transport-level no-progress state**. It does not prove that the provider or model failed, and it does not distinguish a legitimately long time-to-first-byte from a stalled transport. If the transport idle bound expires in that state, the event is recorded as no-progress/occupancy release, not as model failure; it must not penalise, circuit-break, or rank the route. The threshold is a transport/runner-occupancy policy derived from observed time-to-first-byte evidence across the pool, not a claim about how long a model should take.

   This is the substantive question the reverts turned on, and it is settled here deliberately rather than in code review: **an idle-socket bound is not a model wall-clock deadline**, because active byte progress resets it and expiry is not a model-failure verdict. A total elapsed model deadline can terminate a progressing request and attribute duration to the model; that remains forbidden.

2. **Continuation admission.** When the breaker opens on an agent, its reset must not re-offer that agent while equally-ranked, preflight-`ready` alternatives remain untried for this request. The `#1884` trace spent 907 seconds on two routes while two ready routes on the same accounts sat unused. This is a ranking/continuation defect independent of any timeout and would have shortened that run on its own.

3. **Occupancy release is a job-boundary decision with its own event.** If a runner must be reclaimed, that is an operational decision about the runner, and it must be emitted as such — never attributed to the provider as a model failure, and never recorded in a way that feeds route ranking. This is the "admission/continuation boundary" the directive names.

Nothing in section A sets a total-duration limit on a review, a model, or a request.

### B. Actions admission under the plan concurrent-job ceiling (~60)

4. **Skip before runner admission for inert scheduled work.** When `OPENCODE_REVIEW_COALESCE_ENABLED` is not `true`, the coalesce tick job uses a **job-level** `if:` so the run concludes `completed`/`skipped` without competing for a hosted runner (`#2242`; live post-merge proof `35249460935` in 1s per
   [`docs/doctoring/coalesce-tick-post-2242-live-verify-20260917.md`](../doctoring/coalesce-tick-post-2242-live-verify-20260917.md)).
   A step-scoped gate that still admits the job (`#2232`) is rejected: it recreates multi-hour `queued` wait for an echo under the same ceiling as real review work.

5. **Dedicated concurrency group — yes; runner reservation — no (for this tick).**
   - **Keep** workflow concurrency group `opencode-review-coalesce-tick` with `cancel-in-progress: false`. The group caps stacking (at most one active + one pending) and protects an in-flight org-wide dispatch from being cut mid-repository. It does **not** mint a private runner pool or bypass the plan ceiling; hosted `ubuntu-24.04` still shares the ~60 org slots.
   - **Do not** treat a dedicated concurrency group, a different `runs-on` label, or a "reserved" self-hosted runner as the fix for inert-tick queueing. Those levers do not skip admission, and flipping `cancel-in-progress` to `true` would cancel mid-dispatch rather than shorten the active waiter's admission delay (`docs/doctoring/coalesce-tick-inert-runner-queue-20260917.md`).
   - **Do not** invent a model-path or job-level inference timeout to "free" runners stuck behind the ceiling. Capacity recovery for provider exhaustion is bounded re-dispatch (ADR-0031); capacity recovery for Actions saturation is admission shaping and plan-tier headroom (owner-only), not §8-violating model deadlines.

6. **Enabled ticks may still queue for hours; fail-open covers dispatch liveness.** When coalescing is on, a real tick competes for the same ~60 slots. Scheduler `recent_coalesce_tick_completed()` counts only `conclusion=success` and fail-opens when no fresh successful tick exists (`#2233`), so reviews are not deferred forever while a tick sits `queued`. Re-enable criteria for the repo variable remain operator criteria in the post-`#2242` live-verify record — not automatic with this ADR.

## Consequences

- The pin advance in `#2137` becomes safe to land: the implicit 90 s cap goes away and a progress/occupancy boundary replaces it, rather than leaving a six-hour hole.
- Legitimately slow models stop being discarded as model failures. `gemma-4-31b-it`-class routes that need more than 90 s are not penalised merely for elapsed time, which also avoids shrinking the free pool's ready set — relevant to `#1915`, where readiness, not admission, is the concentration point (that run's catalog held 60 admitted routes across 3 accounts; only 4 were ready, all NVIDIA).
- The worst case changes shape rather than disappearing: a provider that dribbles one byte per interval defeats an idle bound. That is accepted. The observed #1884 case is narrower: attempts accepted a connection but emitted no response bytes within the measured window. That observation alone is not promoted to a provider/model-failure verdict.
- A threshold still has to be chosen for item A.1. It is a transport/runner-occupancy property and should be derived from observed time-to-first-byte across the pool, not picked as a round number; until that measurement exists, this ADR deliberately does not name a value.
- Item A.2 can land independently of item A.1 and is the cheaper of the two.
- Agents stop mis-attributing multi-hour schedule/required-check wall time to model latency and stop proposing model timeouts as the repair (`#1889` class). The Actions-layer repair surface is admission (job-level skip, concurrency coalescing, fail-open) plus owner plan capacity — aligning with ADR-0030's "wrong layer" warning.
- Coalesce tick keeps its dedicated concurrency group for mid-dispatch safety; enabling the flag under deep saturation remains an explicit operator choice with documented fail-open acceptance.

## Alternatives considered

### Model-path wall-clock / `timeout-minutes` on review jobs

- **Description:** Cap serving calls or the Noema/OpenCode/Strix job at a fixed elapsed duration (including the reverted 900 s attempts).
- **Rejection:** Forbidden by directive §8, ADR-0003 2026-08-31, and ADR-0005's historical failure mode. Elapsed time is not evidence of model failure.

### Step-scoped coalesce gate for schedule run-record visibility

- **Description:** Always admit the tick job; skip work inside a step so every cron produces a visible run.
- **Rejection:** Forces inert jobs onto the shared runner queue (`35219385415`). Job-level skip still produces `completed`/`skipped` run records (`35191169833`, `35249460935`) without admission cost (`#2242`).

### Runner reservation / self-hosted pool for coalesce tick only

- **Description:** Dedicate runners so the five-minute tick always admits promptly.
- **Rejection:** Does not address org-wide ceiling pressure on the review chains that dominate queue depth; adds operational surface for a job that must usually be skipped. Dedicated **concurrency group** already provides the stacking/safety property without implying reserved capacity.

### Raising plan concurrent-job ceiling as the sole ADR outcome

- **Description:** Treat ~60 as the bug and stop at "buy more concurrency."
- **Rejection:** Owner-only lever; still required for relief under saturation, but does not define transport occupancy semantics or prevent inert work from competing. ADR-0030 already scopes what code changes can and cannot fix.

## References

- Beyer, B., Jones, C., Petoff, J., & Murphy, N. R. (Eds.). (2016). *Site reliability engineering: How Google runs production systems*. O'Reilly Media.
- Fielding, R., Nottingham, M., & Reschke, J. (Eds.). (2022). *HTTP semantics* (RFC 9110). Internet Engineering Task Force. https://doi.org/10.17487/RFC9110 — HTTP defines no client-side completion deadline; how long a client waits is a local policy decision, which is why it has to be made explicitly here rather than inherited.
- Nygard, M. T. (2018). *Release it! Design and deploy production-ready software* (2nd ed.). Pragmatic Bookshelf. — Source of the circuit-breaker and bounded-resource patterns the gateway already implements; item A.2 above is a gap in the continuation half of that pattern, not a new mechanism.
- ADR-0003, 2026-08-31 amendment (model inference has no repository- or run-level deadline) and 2026-09-13 amendment (the `012beaac` pin advance).
- ADR-0005 (historical: fixed wall-clock budgets, superseded).
- ADR-0030 (CI centralization cannot lift the plan concurrent-job ceiling).
- ADR-0031 (Noema transport-capacity recovery via bounded re-dispatch, not in-job model wait).
- `#1889`, `#1890`, `#1892` (900-second caps) and `#1891`, `#1895` (their reverts).
- `#2242` (job-level coalesce skip before admission), `#2244` (post-merge live verify + re-enable criteria).
- `ContextualWisdomLab/contextual-orchestrator#1118` (removal of the implicit 90-second default).
- [`docs/doctoring/actions-capacity-root-cause-20260917.md`](../doctoring/actions-capacity-root-cause-20260917.md) — multi-hour wall time is inter-job queue wait.
- [`docs/doctoring/coalesce-tick-post-2242-live-verify-20260917.md`](../doctoring/coalesce-tick-post-2242-live-verify-20260917.md) — post-`#2242` skipped tick in 1s; schedule lag ≠ model failure.
- [`docs/doctoring/coalesce-tick-inert-runner-queue-20260917.md`](../doctoring/coalesce-tick-inert-runner-queue-20260917.md) — inert tick queueing under the ~60 ceiling.
- [`docs/doctoring/actions-plan-concurrency-ceiling-20260903.md`](../doctoring/actions-plan-concurrency-ceiling-20260903.md).
