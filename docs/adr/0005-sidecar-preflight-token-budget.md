# ADR-0005: Replace the sidecar's fixed-`max_tokens` gateway checks with diagnostic, bounded-retry readiness

- Status: accepted. Implemented in `ContextualWisdomLab/.github#1452`, stacked on this ADR's own PR
  (`ContextualWisdomLab/.github#1449`); pending merge of both, governed separately (OpenCode review
  approval required before merge, per this repo's governance model — this ADR's acceptance does not
  itself authorize merging either PR). The implementation went through four rounds of Devin Review
  scrutiny on PR #1452 after this ADR converged, each verified against actual code before fixing; two
  findings were accepted as known, tracked, non-blocking residual risks rather than fixed
  (`ContextualWisdomLab/.github#1454`, `#1455` — see Consequences).
- Date: 2026-08-30
- Scope: `ContextualWisdomLab/.github` central review pipelines' vendored `contextual-orchestrator`
  sidecar — `scripts/ci/contextual_orchestrator_review_launcher.py`'s existing
  `_preflight_review_agents`/`_preflight_with_fallback`, and
  `scripts/ci/contextual_orchestrator_review_sidecar.sh`'s separate gateway smoke request — plus two
  tracked upstream asks on `ContextualWisdomLab/contextual-orchestrator`.
- Decision: Keep both existing preflight layers (per-candidate launcher probing, and the shell
  script's separate end-to-end request to the virtual `orchestrator/free` model) — neither is being
  introduced, both already exist and each catches a failure class the other cannot. Fix what is
  actually wrong with each with **two distinct, explicitly-bounded retry mechanisms** — one for "got a
  response, it was empty because the budget was too small" (escalate budget), one for "got no response
  at all, or a transport-level failure" (retry for a possibly-different route) — each drawing from a
  small, explicit, shared attempt budget so worst-case latency is bounded and computed, not open-ended.
  Track two upstream `contextual-orchestrator` asks (`ContextualWisdomLab/contextual-orchestrator#926`,
  `#927`) as real, tracked, non-blocking follow-ups.
- Ownership: `.github` owns the sidecar/launcher script and this ADR; `ContextualWisdomLab/contextual-orchestrator`
  owns the gateway internals cited as evidence and the two follow-up issues.
- Figma File ID: N/A (no customer UI).

## Context

Central review (`noema-review`/`opencode-review`/`strix`) depends on two separate, already-existing
liveness checks in the vendored sidecar, run in sequence — this ADR fixes both, it introduces neither.
Citations below pin to the exact reviewed blob at `main`'s
`8b3235d22129035b49ac481a40a341002540e2af` so line numbers cannot rot as the files change later.

1. **Per-candidate launcher probing** (bounded by the sidecar's own 180-second healthz-readiness wait —
   see the family-cap comment in the sidecar script; this happens *before* the process can report
   healthy, one candidate at a time, within that budget).
   [`_preflight_review_agents()`](https://github.com/ContextualWisdomLab/.github/blob/8b3235d22129035b49ac481a40a341002540e2af/scripts/ci/contextual_orchestrator_review_launcher.py#L200-L271)
   sends one bounded `POST` to `client.proxy_send_once` for *each* candidate agent in the admitted
   catalog, with a fixed `max_tokens=REVIEW_MAX_OUTPUT_TOKENS` (currently `4096`,
   [L38](https://github.com/ContextualWisdomLab/.github/blob/8b3235d22129035b49ac481a40a341002540e2af/scripts/ci/contextual_orchestrator_review_launcher.py#L38))
   under a per-attempt
   [`REVIEW_PREFLIGHT_TIMEOUT_SECONDS = 10`](https://github.com/ContextualWisdomLab/.github/blob/8b3235d22129035b49ac481a40a341002540e2af/scripts/ci/contextual_orchestrator_review_launcher.py#L45)
   ceiling. It keeps every candidate whose response has non-empty text
   ([`_chat_response_has_text`](https://github.com/ContextualWisdomLab/.github/blob/8b3235d22129035b49ac481a40a341002540e2af/scripts/ci/contextual_orchestrator_review_launcher.py#L175-L189)
   — checks only `choices[0].message.content`, never inspects `finish_reason`) and raises
   `ReviewPreflightError` only if **zero** candidates pass — i.e. it is already an N-of-M ("at least one
   must work") design, not a single-candidate gate.
   [`_preflight_with_fallback()`](https://github.com/ContextualWisdomLab/.github/blob/8b3235d22129035b49ac481a40a341002540e2af/scripts/ci/contextual_orchestrator_review_launcher.py#L274-L291)
   wraps this with one fallback catalog tier.
2. **The shell script's own virtual-pool smoke request.** Once `/healthz` succeeds (a separate,
   already-completed budget — Layer 2 does not draw from Layer 1's 180s), the shell script sends one
   `POST /v1/chat/completions` with `"model":"orchestrator/free"` (the *virtual* pool id, not a
   specific candidate) and its own fixed `max_tokens`, currently `4096`, under a **120-second**
   `curl --max-time`. This 120s value is itself the outcome of a prior, real, evidenced fix in this
   exact file (raised from a too-tight 30s after live reproduction on
   `ContextualWisdomLab/contextual-orchestrator#921` showed a genuinely-healthy DeepSeek NIM route
   needing more than 30s to complete a real generation) — the comment there explicitly documents that
   this required-workflow job budgets **120 minutes** total (`timeout-minutes` in
   `strix.yml`/`noema-review.yml`) and that *"the org's own stated policy accepts multi-hour central
   review latency in favor of accuracy over speed."* This ADR's design deliberately **does not shorten
   that 120s value** — doing so would reintroduce the exact regression that prior fix corrected. The
   correct fix for a hang, per Devin Review (see Decision §1), is a bounded *retry*, not a shorter
   *timeout*.

`N` (the `max_tokens` literal) has already been tuned twice: 16 → 4096 (#1436), moving the failure
from "empty content at 16 tokens" (the provider's response consumed the whole budget on internal
reasoning before emitting visible content — see `ModelClient._response_content`'s own anticipated
error message, quoted below) to "120s timeout with zero bytes at 4096 tokens" on a separate run.
Direct owner feedback in response to that outcome, quoted verbatim because it is the reason this ADR
exists:

> "max_tokens 이걸 고정하는 게 말이 안 되는데" — hardcoding this max_tokens doesn't make sense.
> "모델마다 max_tokens 허용치가 다 다른데" — each model has a genuinely different max_tokens allowance.

`orchestrator/free` is a heterogeneous pool (`nvidia_nim`, `openai`, `opencode_zen`, `bytez`,
`openrouter`, ... — see `contextual_orchestrator_review_policy.py`'s `PROVIDER_FAMILIES`), and which
candidate a given preflight run draws varies. A fixed `max_tokens` is wrong on two independent,
evidenced axes for a pool like this:

1. **Reasoning-token overhead differs per model.** A model that spends internal reasoning tokens
   before emitting visible content can exhaust a small budget with zero visible output. OpenAI's own
   documentation of `finish_reason == "length"` describes exactly this: *"it's likely that max_tokens
   is too small and model runs out of tokens before it manages to [complete]"*
   ([OpenAI API guide](https://developers.openai.com/api/docs/guides/completions)).
2. **The provider's own hard ceiling on completion tokens differs per model**, and is a genuinely
   separate quantity from a model's context window (see Research §3 below). Some providers reject a
   request outright if `max_tokens` exceeds what that specific model supports; others support far more
   than a generic constant would ever request. A single number can therefore be simultaneously too
   small for one model's reasoning overhead and too large for another model's real ceiling.

The standing session principle governing this decision, also quoted verbatim: "어떠한 휴리스틱과 Rule
of thumbs도 금지" — no heuristics or rules of thumb; a parameter needs actual justification from real
data, not a constant that happens to work today.

## Research: three questions, checked directly against `contextual-orchestrator` source and, where the
## claim is about external provider behavior, against the providers' own current documentation

### 1. Does the gateway expose a way to separate a reasoning budget from a content budget?

**No.** `ReasoningEffortProfile`/`apply_request_profile()` (`reasoning_effort_profile.py`) is real but
**additive, not substitutive**: it always sets `payload["max_tokens"]` regardless of `reasoning_effort`.
OpenAI documents the analogous parameter the same way: `max_completion_tokens` is *"an upper bound for
the number of tokens that can be generated for a completion, **including** visible output tokens and
reasoning tokens"* (same OpenAI guide). The mechanism is also opt-in at `TaskOrchestrator` construction
(`_role_effort_profile(role)` returns `None` unless a `role_effort_catalog` was configured), and the
public `/v1/chat/completions`/`/v1/responses` endpoints this preflight and Strix use both treat a
caller-supplied `reasoning_effort`/`reasoning` field as a documented no-op (`server.py`'s own
docstrings: `_validate_chat_reasoning_effort`, `_validate_responses_reasoning`).

**Conclusion**: there is no lever, on any caller-facing surface this preflight (or Strix) can reach,
that separates "let the model think as long as it needs" from "cap what it can emit."

### 2. Is a real-generation preflight even the right liveness mechanism — is there a cheaper or more direct signal?

**A better-shaped mechanism exists in two places — one already in this sidecar, one further
upstream — but neither is a free non-generation signal.**

- **Already in this repo**: `_preflight_review_agents()` already probes every candidate individually
  and already tolerates any number of individual failures. What it lacks is not the *shape* but a way
  to tell "this candidate is down" apart from "this candidate is healthy but its probe's budget was
  wrong for it," and (separately) a way to survive a hang with no response at all — see Decision §1.
- **Further upstream, admin-scoped**: `ModelClient.probe()`/`provider_readiness_report()` are the
  gateway's own, more mature version of the same idea. Verified directly: `/api/v1/*` GET routes are
  authorized at **`admin` scope**, while `/v1/chat/completions` — what the sidecar's bearer token is
  scoped for today — is authorized at the narrower **`inference` scope**. Provisioning the sidecar with
  an admin-scoped token just for this would be a real privilege widening this ADR does not recommend.
  Tracked as `ContextualWisdomLab/contextual-orchestrator#926`.
- **Neither eliminates real generation, and neither eliminates the possibility of a hang.** `probe()`
  itself hardcodes `max_tokens: 1` and has no retry of its own.

**Conclusion**: reuse the shape that already exists in this sidecar; fix its calibration and add
bounded retries (Decision §1); track the upstream, better-tested version as a non-blocking follow-up.

### 3. If a numeric budget is still needed, can it be derived per-model from real discovered data?

**Not today.** Neither `DiscoveredModel` (`model_discovery.py`) nor `ModelAgent` (`orchestrator.py`)
carries any field for a model's output-token ceiling or context window — confirmed via full-dataclass
read and grep. This is **two distinct pieces of data, not one** — verified directly against
OpenRouter's current OpenAPI spec (`https://openrouter.ai/openapi.yaml`): `Model.context_length`
(required) is *"Maximum context length in tokens"*; `TopProviderInfo.max_completion_tokens` (nullable
— genuinely absent for some models) is *"Maximum completion tokens from the top provider. Input and
output tokens share the context window, so the effective maximum output for a request is further
limited by the context remaining after input tokens."* Only the second field can directly clamp a
`max_tokens` request parameter.

**Conclusion**: tracked as `ContextualWisdomLab/contextual-orchestrator#927`, not undertaken here.

## Decision

### 1. Two distinct, explicitly-bounded retry mechanisms, not one generic "retry" — and not the same behavior in both layers

Devin Review correctly found that a single "retry on empty content + `finish_reason == 'length'`"
predicate cannot fix the actual live outage this ADR is responding to: the reproduced failure (job
`99253418179`, cited in the Evidence trail) is a **120-second timeout with zero bytes received** —
there is no response object at all in that case, so there is no `finish_reason` to inspect, and the
original design's retry path would never trigger for it. Fixed by splitting into two independent
triggers. **Layer 1 and Layer 2 use these triggers differently, by structural necessity, not by
inconsistency — the difference is stated once here and referenced everywhere else, rather than
implied and then contradicted section to section (a real self-contradiction Devin Review's third pass
correctly caught in an earlier revision of this text):**

- **Trigger A — no usable response** (transport timeout, connection failure, or non-2xx status on the
  *first* attempt at a given budget).
  - **Layer 2**: retry with a fresh attempt at the same `4096` budget, up to the shared attempt cap
    (Decision §3). Layer 2 has exactly one check — there is no other candidate to fall back to — so a
    hang there must be survived by retrying, or the reproduced outage is not actually fixed. **This
    retry is justified even without any guarantee of hitting a different underlying candidate** — see
    the route-diversity note below — because it is bounded and strictly better than the current
    design's single unconditional attempt with no recovery path at all: worst case, the outcome is
    identical and the check still fails closed with the same accurate diagnosis; best case, a
    transient failure (a network blip, a momentarily overloaded connection) clears on retry.
  - **Layer 1**: **no retry**. Layer 1 already probes up to 12 distinct candidates
    (`REVIEW_PREFLIGHT_MAX_TOTAL_ROUTES`); one candidate's timeout simply consumes its existing 10s
    slot and the loop moves to the next candidate, exactly as it does today. A same-candidate retry
    here would add latency without adding resilience Layer 1's own multi-candidate design does not
    already provide.
- **Trigger B — a response was received, content is empty, and `choices[0].finish_reason == "length"`**
  (the OpenAI-documented signature of "budget too small," cited above).
  - **Layer 1**: retry that *same* candidate (`client.proxy_send_once(agent, ...)` pins the exact agent
    object, so this retry is genuinely attributable to that one candidate) once at a **materially
    larger** budget — `REVIEW_PREFLIGHT_ESCALATED_TOKENS` (`4096`, reusing `REVIEW_MAX_OUTPUT_TOKENS`),
    up from a `16`-token base probe (`REVIEW_PREFLIGHT_BASE_TOKENS` — a **new, smaller** value than the
    `4096` Layer 1 uses today; see Decision §3). This is the only place in either layer where the
    budget itself changes.
  - **Layer 2**: **no retry — this is a deliberate simplification made across this ADR's review, not an
    oversight.** Devin Review's fourth pass found the reason directly: a `finish_reason == "length"`
    response is still `HTTP 200` — the gateway's own routing layer already recorded that as a
    *successful* attempt before the sidecar ever inspects the content, so a subsequent identical
    request is not a fresh, independent draw against the pool; the gateway's routing is more likely to
    *repeat* the same "successful" candidate than to diversify away from it. Retrying at the same
    budget against the same likely candidate has no principled reason to produce a different outcome,
    so Layer 2 does not attempt it: an empty response with `finish_reason == "length"` at Layer 2 is
    recorded as not-ready immediately, with that `finish_reason` preserved in the report for diagnosis.

**Route diversity on Layer 2's Trigger-A retry is a best-effort hope, not a verified guarantee, and
this ADR stops trying to force it.** This is the fourth time a version of "does the retry actually
reach a different or better outcome" has come back reshaped across Devin Review's passes on this ADR
(round 2: a too-small budget; round 3: an escalated retry that could hit an unaccountable different
candidate; round 4: the specific case above). Checked directly rather than assumed before accepting
this as final: `contextual_orchestrator/server.py`'s request handling exposes no field to exclude,
deprioritize, or pin away from a specific candidate on a subsequent call — grepped for any such
parameter and found none. Given no verified mechanism to force diversity exists, and per this org's
convention to converge on an honestly-scoped decision rather than iterate indefinitely toward a fully
"solved" design, this ADR's final position is: **Layer 1's genuine N-of-M across truly distinct,
individually-addressed candidates is what does the real resilience and diversity work in this design.
Layer 2 remains what it always was — a single end-to-end smoke test proving the virtual-pool dispatch
path itself works at all — and its bounded retry (Trigger A only) is a modest, honest safety margin
against transient failures, not a pool-exploration mechanism.** If the gateway later exposes a real way
to exclude a specific candidate, that would improve Layer 2's retry meaningfully and should be
revisited then (a natural extension of `ContextualWisdomLab/contextual-orchestrator#926`); this ADR
does not invent that mechanism speculatively.
- **Both triggers draw from one small, shared, explicit retry budget per layer** (Decision §3), not
  "one retry per route" unconditionally.
- **A non-2xx rejection on a Layer 1 escalated (Trigger-B) retry** is recorded with the same sanitized
  exception-type/HTTP-status evidence the base probe uses, and that candidate is not retried further this
  run — **revised during implementation** (PR #1452, a later Devin Review pass): this ADR originally
  claimed such a rejection was "distinguishable evidence the escalated budget specifically exceeds that
  candidate's real ceiling," labeled `escalated_probe_rejected`. That over-claimed attribution — an HTTP
  status alone (401 auth, 429 throttle, 5xx server error, ...) is not evidence the token budget caused the
  rejection, only that some request failed, and this codebase deliberately never captures raw provider
  error text that could validate the distinction. The complete fix (knowing each model's real ceiling in
  advance, so a genuine budget-ceiling rejection could be told apart from any other) is
  `ContextualWisdomLab/contextual-orchestrator#927`, not this ADR.
- **A non-2xx rejection on a Layer 2 Trigger-A retry** is recorded as `gateway_retry_rejected` —
  deliberately **not** named or described as candidate-ceiling evidence, because Layer 2 structurally
  cannot confirm which candidate served the rejected attempt.
- **Every other outcome is not retried**: a non-2xx or empty-with-a-different-`finish_reason` result on
  an attempt that is not eligible for Trigger A or B for that layer (i.e., already the layer's one
  retry, or already past its shared budget) is recorded as not-ready immediately.

### 2. Keep both existing layers — neither replaces the other

Layer 1's per-candidate checks call `client.proxy_send_once` against explicit candidate agents directly
and structurally cannot detect a bug in the virtual pool's own dispatch/selection code, which is a
different code path. This is not hypothetical: the 2026-08-30 gap-baseline entry for PR #1433 records
exactly this split failure live — the launcher's own per-candidate preflight passed and the server
reported healthy, while the shell script's separate virtual-pool request still came back `HTTP 502`.
Layer 2 also independently reproduced the ADR's own motivating bug live on PR #1449 itself (Evidence
trail). Any redesign that dropped Layer 2 in favor of Layer 1 alone would silently reintroduce both.

### 3. Explicit, bounded, per-layer retry budgets and the resulting worst-case arithmetic

Devin Review's third finding is correct: `REVIEW_PREFLIGHT_MAX_TOTAL_ROUTES` (12) candidates each
retried once, unconditionally, would be a real, computed worst-case blowup against Layer 1's own
180-second healthz-readiness budget. Fixed with an explicit shared cap per layer, not an unbounded
"one retry per route":

- **Layer 1** (bounded by the existing 180s healthz-readiness wait, unchanged): keep the existing
  per-attempt timeout (`REVIEW_PREFLIGHT_TIMEOUT_SECONDS = 10`, unchanged). The **base probe budget
  changes from `4096` (today's value) to a new, smaller `REVIEW_PREFLIGHT_BASE_TOKENS = 16`** — cheap
  by design, because the escalation path below corrects for it being wrong, unlike today where a wrong
  first (and only) guess is fatal. Trigger A does not need its own retry allowance here (see Decision
  §1). Trigger B (escalate to `REVIEW_PREFLIGHT_ESCALATED_TOKENS = 4096`, reusing today's
  `REVIEW_MAX_OUTPUT_TOKENS`, on `finish_reason == "length"`) is capped by a new shared counter,
  `REVIEW_PREFLIGHT_MAX_ESCALATIONS = 4`, across the whole Layer 1 run (not per-candidate) — once 4
  candidates have consumed an escalation attempt, any further candidate that would otherwise qualify
  for Trigger B is instead recorded not-ready immediately with an explicit
  `escalation_budget_exhausted` reason. **Worst case**: 12 × 10s (base attempts) + 4 × 10s (escalation
  attempts) = **160s**, under the existing 180s ceiling with real margin, computed rather than assumed.
- **Layer 2** (bounded only by the job's own 120-minute ceiling, per the org's stated "accuracy over
  speed" policy already reasoned in this file — *not* by the 180s Layer 1 budget, which has already
  completed by the time Layer 2 runs): keep the existing per-attempt timeout (**120s, unchanged** — not
  shortened, per Context above) and the existing **`4096` budget, unchanged throughout — Layer 2 never
  escalates** (already proven working on a real hosted run, `contextual-orchestrator#921`; see Decision
  §1 for why an escalation tier was considered and dropped here). Allow up to
  `REVIEW_PREFLIGHT_GATEWAY_MAX_ATTEMPTS = 3` total attempts, consumed only by Trigger A (transport
  failure/hang/non-2xx) — Trigger B (empty + `finish_reason == "length"`) is not retried at Layer 2 at
  all (Decision §1). **Worst case**: 3 × 120s = **360s (6 minutes)** —
  explicit, bounded, and small relative to the job's 120-minute ceiling; the previous design's worst
  case was already 120s for one unconditional attempt with no chance of recovery, so this trades a
  bounded amount of additional worst-case latency for surviving exactly the transient-hang class of
  failure reproduced live on this ADR's own PR.
- **Initial values are reused precedent, not new guesses** (Devin Review's fourth finding): every
  number above is either already deployed in this exact codebase today (`10s`, `120s`, `4096`, `12`)
  or has direct external documentation backing it (`16` — the pre-#1436 value this codebase already
  ran with, and separately the floor OpenRouter's own schema documents: *"some providers enforce a
  minimum of 16"* for the deprecated `max_tokens` field). The two new counters
  (`REVIEW_PREFLIGHT_MAX_ESCALATIONS`, `REVIEW_PREFLIGHT_GATEWAY_MAX_ATTEMPTS`) are chosen to keep each
  layer's worst case under its own already-established ceiling, shown above, not picked by inspection
  of "what feels right." The implementation must have both preflight layers emit `finish_reason`,
  attempt count, and which trigger fired in their structured reports (`_preflight_review_agents`'s
  `routes[]`; the shell script's `preflight_report`/`gateway` JSON) — this ADR does not implement that
  itself (see Status) — specifically so that a **follow-up, evidence-driven pass** — after
  observing real hosted runs with this telemetry — can adjust these two counters and the base/escalated
  token budgets from real data, which is the methodology this ADR commits to for future tuning: initial
  values from direct precedent, refinement from telemetry this change itself introduces, never from
  inspection alone.

### 4. Upstream tracking and rejection of further constant-tuning

- **Track `ContextualWisdomLab/contextual-orchestrator#926`** (an `inference`-scoped variant of
  `provider_readiness_report`/`probe()`) so the sidecar can eventually retire its hand-rolled Layer 1
  loop. Not blocking for §1-3.
- **Track `ContextualWisdomLab/contextual-orchestrator#927`** (real, separately-provenanced
  `max_output_tokens`/`context_window` fields, fail-closed when unknown) so `max_tokens` selection can
  eventually be derived from real per-model data, including telling a genuine budget-ceiling rejection
  on an escalated attempt (§1) apart from any other cause with real evidence, instead of the generic,
  honestly-unattributed classification used today. Not blocking for §1-3.
- **Explicitly reject** further tuning of one global `max_tokens` constant, or of a single generic
  "retry," as a terminal fix for either layer. Every single-constant value tried so far (16, 4096) has
  failed for a different, evidenced reason tied to pool heterogeneity, and a single undifferentiated
  retry predicate does not cover the failure class (a hang) that actually reproduced live on this ADR's
  own PR.

## Consequences

**Implemented, in `ContextualWisdomLab/.github#1452` (stacked on this ADR's own PR #1449). The
consequences below describe the shipped behavior, verified against this ADR's design through four
rounds of Devin Review scrutiny on the implementation PR itself (each finding verified against actual
code before fixing) — not a hypothetical outcome. Both PRs remain pending merge, governed separately
(OpenCode review approval required); this ADR's `accepted` status is the design decision, not a merge
authorization.**

- Both preflight layers are now structurally tolerant of an individual attempt being wrong for a fixed
  token budget, or hanging/failing transiently, which is the actual shape of the problem — while keeping
  every worst case explicit and bounded rather than open-ended.
- Layer 1's worst case grew from ~120s to a computed 160s (probing/escalation alone — see the known,
  tracked gap on discovery's own time below), still under its existing 180s healthz-readiness ceiling.
  Layer 2's worst case grew from a single 120s attempt with no recovery path to up to 360s across bounded
  retries — small relative to the job's 120-minute ceiling and consistent with this file's own
  already-stated "accuracy over speed" policy.
- Keeping Layer 2 (not just Layer 1) means the preflight still proves the actual consumer-facing
  `orchestrator/free` route works, not only that individual candidates can respond in isolation —
  closing the PR #1433 gap class rather than reopening it. Giving Layer 2 a bounded retry (rather than
  either a single unconditional attempt or a shortened timeout) is what actually addresses the live
  120s-hang reproduction on this ADR's own PR (job `99253418179`) — a shortened timeout alone would not
  have, and would have regressed the prior, already-evidenced 30s→120s fix in the same file. Whether it
  would have *prevented* that exact reproduction is not claimed with certainty (Layer 2's retry has no
  verified route-diversity guarantee — see Decision §1); what it changes is that the check no longer
  fails after one unconditional attempt with zero chance of recovery.
- A Layer 1 candidate whose escalated probe is rejected outright (rather than merely still empty) is
  recorded as not-ready with a distinct, honest reason rather than silently retried indefinitely or
  misclassified — a known, accepted, documented residual limitation until
  `ContextualWisdomLab/contextual-orchestrator#927` lands. Layer 2's retry-diversity limitation
  (Decision §1) is accepted the same way, for the same reason: no verified mechanism exists today to
  do better.
- **Two more known, accepted, documented residual limitations, verified during implementation (PR #1452)
  and decided not to block it**, for the same reason as the two immediately above — this design is a
  genuine, verified improvement over the status quo it replaces, and does not need to close every
  residual failure mode to be worth shipping:
  - A Layer 1 candidate that succeeds at the cheap `REVIEW_PREFLIGHT_BASE_TOKENS` (`16`) base probe is
    admitted without ever being confirmed at the real serving budget
    (`REVIEW_MAX_OUTPUT_TOKENS`, `4096`) — escalation only fires on evidence of *failure*, not to
    *confirm* success at the real budget, so a candidate whose real ceiling sits strictly between the two
    could pass here and only fail later, on real review traffic. Mitigated in production (not eliminated)
    by `TaskOrchestrator`'s existing per-request failover and per-agent circuit breaker. Tracked as
    `ContextualWisdomLab/.github#1454`.
  - Layer 1's `160s` worst case (Decision §3) accounts only for probing/escalation, not for
    `discover_all_models()`'s own sequential network time, which runs first inside the *same* 180s
    healthz-readiness watchdog — verified against the vendored `contextual_orchestrator.model_discovery`
    source at up to ~7 sequential HTTP calls, each up to `DISCOVERY_TIMEOUT_SECONDS = 15s` (~105s worst
    case), for a combined real worst case of up to ~265s. This requires two unlikely conditions to
    coincide (discovery near its own worst case *and* probing separately needing close to its full
    escalation budget) to actually exceed the watchdog, making it a tail case rather than the common
    path; no real timing telemetry exists yet to justify a specific fix (a shared deadline, scaled-down
    probing, or an evidence-justified watchdog extension), consistent with this ADR's own rejection of
    picking a number from inspection alone (Context, "어떠한 휴리스틱과 Rule of thumbs도 금지"). Tracked as
    `ContextualWisdomLab/.github#1455`.
- Items in Decision §4 are real `contextual-orchestrator` feature work, now tracked as real issues, and
  remain explicitly not closed by this ADR now that the sidecar-side implementation has landed.
- No production routing default changes are proposed; this is scoped to the sidecar's own liveness
  checks.
- **This is currently active, not theoretical**: the live reproduction in the Evidence trail below is
  from `noema-review` failing on this ADR's own PR while this ADR was being written, presently
  blocking that required check org-wide on every repo that routes through this sidecar. The
  implementation follow-up applying this Decision should be prioritized accordingly, not treated as
  ordinary backlog.

## Evidence trail

All source citations below are permalinks to the exact reviewed blob at
`8b3235d22129035b49ac481a40a341002540e2af` (the `main` commit this research was performed against), so
line numbers cannot rot as these files are edited later.

- [`_preflight_review_agents`](https://github.com/ContextualWisdomLab/.github/blob/8b3235d22129035b49ac481a40a341002540e2af/scripts/ci/contextual_orchestrator_review_launcher.py#L200-L271),
  [`_preflight_with_fallback`](https://github.com/ContextualWisdomLab/.github/blob/8b3235d22129035b49ac481a40a341002540e2af/scripts/ci/contextual_orchestrator_review_launcher.py#L274-L291),
  [`_chat_response_has_text`](https://github.com/ContextualWisdomLab/.github/blob/8b3235d22129035b49ac481a40a341002540e2af/scripts/ci/contextual_orchestrator_review_launcher.py#L175-L189),
  [`REVIEW_MAX_OUTPUT_TOKENS`/`REVIEW_PREFLIGHT_TIMEOUT_SECONDS`/`REVIEW_PREFLIGHT_MAX_TOTAL_ROUTES`](https://github.com/ContextualWisdomLab/.github/blob/8b3235d22129035b49ac481a40a341002540e2af/scripts/ci/contextual_orchestrator_review_launcher.py#L36-L47)
  — the existing Layer 1 mechanism this ADR fixes, not introduces.
- [`scripts/ci/contextual_orchestrator_review_sidecar.sh`, the healthz-wait loop and its 180s budget comment](https://github.com/ContextualWisdomLab/.github/blob/8b3235d22129035b49ac481a40a341002540e2af/scripts/ci/contextual_orchestrator_review_sidecar.sh#L67-L69),
  and [the virtual-pool smoke request and its existing 30s→120s rationale](https://github.com/ContextualWisdomLab/.github/blob/8b3235d22129035b49ac481a40a341002540e2af/scripts/ci/contextual_orchestrator_review_sidecar.sh#L430-L475)
  — the existing Layer 2 mechanism this ADR fixes, not introduces or shortens.
- 2026-08-30 gap-baseline entry (PR #1433 evidence): *"the shell script's separate, subsequent real
  `/v1/chat/completions` gateway smoke request against the now-serving `orchestrator/free` virtual
  model came back HTTP 502. This is a different code path than the launcher's own preflight
  (`ModelClient.proxy_send_once` against explicit candidate agents)"* — the direct, already-documented
  precedent for why Layer 2 cannot be dropped in favor of Layer 1 alone.
- `ModelClient._response_content` (`orchestrator.py:1648-1660`) — the "reasoning without content"
  failure this investigation traces to, already anticipated in the codebase's own error message:
  *"provider {agent.id} returned reasoning without content; for mlx-lm set
  chat_template_args={"enable_thinking": false} or increase max_output_tokens."*
- `ModelClient.apply_effort_profile` / `reasoning_effort_profile.apply_request_profile` — confirms
  `max_tokens` is always set regardless of `reasoning_effort`.
- `server.py:3731-3758` (`_validate_chat_reasoning_effort`), `server.py:4775-4809`
  (`_validate_responses_reasoning`) — confirms both fields are validated, documented no-ops on the
  caller-facing surfaces this preflight and Strix use.
- `ModelClient.probe` (`orchestrator.py:1483-1561`), `TaskOrchestrator.provider_readiness_report`
  (`orchestrator.py:3441-3486`), `server.py:5711-5715` — the upstream mechanism, and its admin-scope
  gate vs. the `inference`-scoped `/v1/chat/completions`/`/v1/models` handlers.
- **External, directly-fetched citations** (verified live against the providers' own current
  documentation before citing, per this org's traceability convention):
  - OpenAI, [*Completions API guide*](https://developers.openai.com/api/docs/guides/completions):
    `finish_reason == "length"` — *"it's likely that max_tokens is too small and model runs out of
    tokens before it manages to [complete]"*; `max_completion_tokens` — *"an upper bound for the
    number of tokens that can be generated for a completion, including visible output tokens and
    reasoning tokens."*
  - OpenRouter, OpenAPI spec (`https://openrouter.ai/openapi.yaml`), `Model.context_length` —
    *"Maximum context length in tokens"* (required); `TopProviderInfo.max_completion_tokens` —
    *"Maximum completion tokens from the top provider. Input and output tokens share the context
    window, so the effective maximum output for a request is further limited by the context
    remaining after input tokens"* (nullable); the deprecated `max_tokens` field description —
    *"Note: some providers enforce a minimum of 16"* — the direct evidence for this ADR's `16`-token
    Layer 1 base probe value.
- `ContextualWisdomLab/contextual-orchestrator#926`, `#927` — the two tracked upstream follow-ups.
- **Live reproduction on this ADR's own PR**, verified directly against the job log rather than taken
  on report: `noema-review` on `ContextualWisdomLab/.github#1449` (job `99253418179`,
  `https://github.com/ContextualWisdomLab/.github/actions/runs/33310078256/job/99253418179`) —
  ```
  2026-08-30T11:58:29Z healthz and provider-route preflight confirmed after 30s (pid 3973)
  2026-08-30T12:00:29Z curl: (28) Operation timed out after 120002 milliseconds with 0 bytes received
  2026-08-30T12:00:29Z error: gateway preflight request could not reach the local sidecar
  ```
  Layer 1 (per-candidate) passed in 30s; Layer 2 (the virtual-pool smoke request) then hung for
  exactly the full 120s timeout with **zero bytes received** — no response, no `finish_reason`,
  nothing. This is exactly Decision §1's Trigger A case (not Trigger B, which requires a response to
  exist) — confirming why the two triggers had to be modeled separately, and why this specific evidence
  is what Decision §3's Layer 2 bounded-retry design (up to 3 attempts) exists to survive.
