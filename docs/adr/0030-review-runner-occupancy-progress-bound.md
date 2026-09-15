# ADR-0030: Review runner occupancy is bounded by progress, never by elapsed inference time

- **Status:** Proposed
- **Date:** 2026-09-13
- **Scope:** `scripts/ci/contextual_orchestrator_review_launcher.py` (the serving `ModelClient` construction and `_preflight_with_fallback`'s continuation choice), the vendored `contextual_orchestrator` transport, `.github/workflows/noema-review.yml` (the deliberately unbounded review job)
- **Amends:** nothing. Extends ADR-0003's 2026-08-31 amendment ("model inference has no repository- or run-level deadline") by naming what *may* be bounded, which that amendment left open. ADR-0005's fixed wall-clock budgets remain historical and are not restored.

## Problem

The vendored gateway is about to stop bounding a single provider call, and nothing below GitHub's six-hour job ceiling replaces it.

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

### Why the obvious fix is forbidden

Passing an explicit `timeout=` at the launcher's serving call site would reinstate the reverted cap under a different name. `docs/product-goal-directive.md` §8 accepts that a model path may take more than two hours and states that speed is not a core consideration; ADR-0005 records that fixed wall-clock budgets "failed for legitimately slow models." This ADR does not reopen that, and the same trace shows why it should not: `google/gemma-4-31b-it` was rejected at preflight after exactly 90.0 s with `TimeoutError`. Nothing in the evidence distinguishes that from a model that was simply going to take 91 seconds. The cap is discarding routes on no evidence of failure.

So the org currently has both defects at once: a cap that kills slow-but-working models, and, once it is removed, no explicit occupancy boundary for a request that makes no observable transport progress.

## Constraints

1. Elapsed inference time must never become a model-failure verdict (ADR-0003 2026-08-31; directive §8).
2. A route must not be dropped, penalised, or circuit-broken for being slow.
3. A review runner must not be held indefinitely by a provider that has stopped responding.
4. Whatever bound exists must be explainable from evidence in the sidecar artifact, not inferred from wall-clock alone.

Constraints 1–2 and 3 are only in tension if "how long has this taken" is the sole available signal. It is not.

## Decision

**Bound progress, not elapsed time.**

1. **Idle-socket bound, reset on every byte received.** Within the external job boundary, a response that is actively streaming is never interrupted by the idle-socket bound, regardless of total inference duration — a two-hour generation completes if that external boundary remains available. A job ceiling or a separately classified runner-reclamation event may still terminate the request; neither event is a model-failure verdict and neither may feed route ranking. Before the first response byte, absence of bytes is classified only as a **transport-level no-progress state**. It does not prove that the provider or model failed, and it does not distinguish a legitimately long time-to-first-byte from a stalled transport. If the transport idle bound expires in that state, the event is recorded as no-progress/occupancy release, not as model failure; it must not penalise, circuit-break, or rank the route. The threshold is a transport/runner-occupancy policy derived from observed time-to-first-byte evidence across the pool, not a claim about how long a model should take.

   This is the substantive question the reverts turned on, and it is settled here deliberately rather than in code review: **an idle-socket bound is not a model wall-clock deadline**, because active byte progress resets it and expiry is not a model-failure verdict. A total elapsed model deadline can terminate a progressing request and attribute duration to the model; that remains forbidden.

2. **Continuation admission.** When the breaker opens on an agent, its reset must not re-offer that agent while equally-ranked, preflight-`ready` alternatives remain untried for this request. The `#1884` trace spent 907 seconds on two routes while two ready routes on the same accounts sat unused. This is a ranking/continuation defect independent of any timeout and would have shortened that run on its own.

3. **Occupancy release is a job-boundary decision with its own event.** If a runner must be reclaimed, that is an operational decision about the runner, and it must be emitted as such — never attributed to the provider as a model failure, and never recorded in a way that feeds route ranking. This is the "admission/continuation boundary" the directive names.

Nothing here sets a total-duration limit on a review, a model, or a request.

## Consequences

- The pin advance in `#2137` becomes safe to land: the implicit 90 s cap goes away and a progress/occupancy boundary replaces it, rather than leaving a six-hour hole.
- Legitimately slow models stop being discarded as model failures. `gemma-4-31b-it`-class routes that need more than 90 s are not penalised merely for elapsed time, which also avoids shrinking the free pool's ready set — relevant to `#1915`, where readiness, not admission, is the concentration point (that run's catalog held 60 admitted routes across 3 accounts; only 4 were ready, all NVIDIA).
- The worst case changes shape rather than disappearing: a provider that dribbles one byte per interval defeats an idle bound. That is accepted. The observed #1884 case is narrower: attempts accepted a connection but emitted no response bytes within the measured window. That observation alone is not promoted to a provider/model-failure verdict.
- A threshold still has to be chosen for item 1. It is a transport/runner-occupancy property and should be derived from observed time-to-first-byte across the pool, not picked as a round number; until that measurement exists, this ADR deliberately does not name a value.
- Item 2 can land independently of item 1 and is the cheaper of the two.

## References

- Beyer, B., Jones, C., Petoff, J., & Murphy, N. R. (Eds.). (2016). *Site reliability engineering: How Google runs production systems*. O'Reilly Media.
- Fielding, R., Nottingham, M., & Reschke, J. (Eds.). (2022). *HTTP semantics* (RFC 9110). Internet Engineering Task Force. https://doi.org/10.17487/RFC9110 — HTTP defines no client-side completion deadline; how long a client waits is a local policy decision, which is why it has to be made explicitly here rather than inherited.
- Nygard, M. T. (2018). *Release it! Design and deploy production-ready software* (2nd ed.). Pragmatic Bookshelf. — Source of the circuit-breaker and bounded-resource patterns the gateway already implements; item 2 above is a gap in the continuation half of that pattern, not a new mechanism.
- ADR-0003, 2026-08-31 amendment (model inference has no repository- or run-level deadline) and 2026-09-13 amendment (the `012beaac` pin advance).
- ADR-0005 (historical: fixed wall-clock budgets, superseded).
- `#1889`, `#1890`, `#1892` (900-second caps) and `#1891`, `#1895` (their reverts).
- `ContextualWisdomLab/contextual-orchestrator#1118` (removal of the implicit 90-second default).
