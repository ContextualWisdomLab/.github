# ADR-0005: Replace the sidecar's fixed-`max_tokens` gateway checks with diagnostic, tolerant readiness

- Status: proposed
- Date: 2026-08-30
- Scope: `ContextualWisdomLab/.github` central review pipelines' vendored `contextual-orchestrator`
  sidecar — `scripts/ci/contextual_orchestrator_review_launcher.py`'s existing
  `_preflight_review_agents`/`_preflight_with_fallback`, and
  `scripts/ci/contextual_orchestrator_review_sidecar.sh`'s separate gateway smoke request — plus two
  tracked upstream asks on `ContextualWisdomLab/contextual-orchestrator`.
- Decision: Keep both existing preflight layers (per-candidate launcher probing, and the shell
  script's separate end-to-end request to the virtual `orchestrator/free` model) — neither is being
  introduced, both already exist and each catches a failure class the other cannot. Fix what is
  actually wrong with each: replace their single fixed `max_tokens` value with a diagnostic,
  short-timeout, escalate-only-on-positive-evidence probe, so no single number has to be
  simultaneously right for every model in a heterogeneous pool, and a reasoning-heavy healthy
  candidate is no longer misclassified as down. Track two upstream `contextual-orchestrator` asks
  (`ContextualWisdomLab/contextual-orchestrator#926`, `#927`) as real, tracked, non-blocking follow-ups.
- Ownership: `.github` owns the sidecar/launcher script and this ADR; `ContextualWisdomLab/contextual-orchestrator`
  owns the gateway internals cited as evidence and the two follow-up issues.
- Figma File ID: N/A (no customer UI).

## Context

Central review (`noema-review`/`opencode-review`/`strix`) depends on two separate, already-existing
liveness checks in the vendored sidecar, run in sequence — this ADR fixes both, it introduces neither:

1. **Per-candidate launcher probing.** `scripts/ci/contextual_orchestrator_review_launcher.py`'s
   `_preflight_review_agents()` (line 200) sends one bounded `POST` to `client.proxy_send_once` for
   *each* candidate agent in the admitted catalog, with a fixed `max_tokens=REVIEW_MAX_OUTPUT_TOKENS`
   (currently `4096`, line 38) and a fixed `temperature=REVIEW_TEMPERATURE`. It keeps every candidate
   whose response has non-empty text (`_chat_response_has_text`, line 175 — checks only
   `choices[0].message.content`, never inspects `finish_reason`) and raises `ReviewPreflightError`
   only if **zero** candidates pass — i.e. it is already an N-of-M ("at least one must work") design,
   not a single-candidate gate. `_preflight_with_fallback()` (line 274) wraps this with one fallback
   catalog tier. This runs inside the Python process at server startup, before the sidecar can even
   report healthy.
2. **The shell script's own virtual-pool smoke request.** Once the server is up,
   `contextual_orchestrator_review_sidecar.sh` separately sends one `POST /v1/chat/completions` with
   `"model":"orchestrator/free"` (the *virtual* pool id, not a specific candidate) and its own fixed
   `max_tokens` — this is the request `N` below refers to.

`N` has already been tuned twice: 16 → 4096 (#1436), moving the failure from "empty content at 16
tokens" (the provider's response consumed the whole budget on internal reasoning before emitting
visible content — see `ModelClient._response_content`'s own anticipated error message, quoted below)
to "120s timeout with zero bytes at 4096 tokens" on a separate run. Direct owner feedback in response
to that outcome, quoted verbatim because it is the reason this ADR exists:

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
   ([OpenAI API guide](https://developers.openai.com/api/docs/guides/completions)). This is very
   likely what turned #1436's 4096-token raise into a 120-second timeout instead of a fix — a large
   budget lets a heavy-reasoning model legitimately run far longer than a fast, non-reasoning model
   would for the same request (see the 2026-08-30 gap-baseline entry's "third, distinct failure mode").
2. **The provider's own hard ceiling on completion tokens differs per model**, and is a genuinely
   separate quantity from a model's context window (see Research §3 below). Some providers reject a
   request outright if `max_tokens` exceeds what that specific model supports; others support far more
   than a generic constant would ever request. A single number can therefore be simultaneously too
   small for one model's reasoning overhead and too large for another model's real ceiling — there is
   structurally no number that is not wrong for some member of the pool.

The standing session principle governing this decision, also quoted verbatim: "어떠한 휴리스틱과 Rule
of thumbs도 금지" — no heuristics or rules of thumb; a parameter needs actual justification from real
data, not a constant that happens to work today.

## Research: three questions, checked directly against `contextual-orchestrator` source and, where the
## claim is about external provider behavior, against the providers' own current documentation

### 1. Does the gateway expose a way to separate a reasoning budget from a content budget?

**No — not on the endpoint this preflight uses, and not for how the preflight calls it.** Checked
directly in `contextual_orchestrator/orchestrator.py` and `server.py`, not assumed:

- `ReasoningEffortProfile`/`apply_request_profile()` (`reasoning_effort_profile.py`) is a real,
  capability-gated mechanism (`ModelAgent.reasoning_effort_supported: bool | None`, fail-closed unless
  proven `True`), but it is **additive, not substitutive**: `apply_request_profile()` always sets
  `payload["max_tokens"] = validated.max_output_tokens` regardless of whether `reasoning_effort` is
  also set. There is no "unbounded reasoning + bounded content" mode. This matches how OpenAI itself
  documents the analogous parameter: `max_completion_tokens` is *"an upper bound for the number of
  tokens that can be generated for a completion, **including** visible output tokens and reasoning
  tokens"* (same OpenAI guide) — reasoning and visible content already share one budget upstream, by
  design, not only in this gateway.
- This mechanism is **opt-in at `TaskOrchestrator` construction**, not caller-controlled:
  `_role_effort_profile(role)` returns `None` unless the server was constructed with an explicit
  `role_effort_catalog` (`orchestrator.py:5530-5534`).
- The **public `/v1/chat/completions` endpoint the sidecar and Strix's client both call does not
  thread a caller-supplied `reasoning_effort`/`reasoning` field into orchestration at all.**
  `server.py`'s own docstrings say so directly: `_validate_chat_reasoning_effort` — "This gateway
  never threads the knob into `ModelClient` on the orchestration path. Known levels are accepted as
  default-effort no-ops"; `_validate_responses_reasoning` (the `/v1/responses` equivalent) — "This
  gateway proxies Responses but does not interpret or enforce reasoning controls." Switching the
  preflight to `/v1/responses` would not gain anything here — the field is a documented no-op on both.

**Conclusion**: there is no lever, on any caller-facing surface this preflight (or Strix) can reach,
that separates "let the model think as long as it needs" from "cap what it can emit."

### 2. Is a real-generation preflight even the right liveness mechanism — is there a cheaper or more direct signal?

**A better-shaped mechanism than a single fixed-budget request exists in two places — one already in
this sidecar, one further upstream — but neither is a free non-generation signal.** Checked directly:

- **Already in this repo**: `_preflight_review_agents()` (described in Context above) already probes
  every candidate individually and already tolerates any number of individual failures — it fails the
  whole preflight only when literally none pass. What it lacks is not the *shape* (that already
  exists) but a way to tell "this candidate is down" apart from "this candidate is healthy but its
  first probe's budget was wrong for it" — seе Decision §1 below.
- **Further upstream, admin-scoped**: `ModelClient.probe()` (`orchestrator.py:1483`) and
  `TaskOrchestrator.provider_readiness_report()` (`orchestrator.py:3441`, exposed as
  `GET /api/v1/provider_readiness/latest?refresh=true`, `server.py:5711-5715`) are the gateway's own,
  more mature version of the same idea — per-candidate, isolated failure, real `failure_code`
  diagnostics. **Verified directly, and this is a real blocker to adopting it as-is**: `/api/v1/*` GET
  routes are authorized at **`admin` scope** (`server.py`'s `_admin_purpose()` /
  `self._authorize("admin", ...)`), while `/v1/chat/completions` — what the sidecar's bearer token is
  scoped for today — is authorized at the separate, narrower **`inference` scope**. Provisioning the
  CI review sidecar with an admin-scoped token just to call a readiness endpoint would be a real
  privilege widening this ADR does not recommend. Tracked as
  `ContextualWisdomLab/contextual-orchestrator#926`.
- **Neither eliminates real generation.** `probe()` itself still hardcodes `max_tokens: 1`
  (`orchestrator.py:1536`) — even more aggressive than either value this sidecar has tried, and
  vulnerable to the exact same reasoning-overhead misclassification described above. Adopting
  `provider_readiness_report`'s *shape* without also fixing this calibration problem would just move
  the bug, not fix it — which is Devin Review's finding on an earlier draft of this ADR (see Decision
  §1 for the actual fix).

**Conclusion**: reuse the shape that already exists in this sidecar (per-candidate, N-of-M-tolerant);
fix its calibration (Decision §1); track the upstream, better-tested version as a non-blocking
follow-up (`#926`) because it is currently out of reach at this token's privilege level.

### 3. If a numeric budget is still needed, can it be derived per-model from real discovered data?

**Not today — confirmed as a genuine, currently-open gap.** Checked both schemas directly:

- `contextual_orchestrator/model_discovery.py`'s `DiscoveredModel` dataclass and
  `contextual_orchestrator/orchestrator.py`'s `ModelAgent` dataclass carry no field for a model's
  output-token ceiling or context window — confirmed via full-dataclass read and grep.
- This is real, closeable data loss, and it is **two distinct pieces of data, not one** — verified
  directly against a live provider schema rather than assumed uniform. OpenRouter's current OpenAPI
  spec (`https://openrouter.ai/openapi.yaml`) defines the `Model` object's `context_length` field
  (required) as *"Maximum context length in tokens"*, and separately, `TopProviderInfo.max_completion_tokens`
  (nullable — genuinely absent for some models) as *"Maximum completion tokens from the top provider.
  Input and output tokens share the context window, so the effective maximum output for a request is
  further limited by the context remaining after input tokens."* Only the second field can directly
  clamp a `max_tokens` request parameter; the first constrains prompt+output together and is not a
  substitute for it — conflating them would let a large-context, small-output model's window size
  wrongly justify a `max_tokens` far beyond what that model can actually complete in.

**Conclusion**: deriving a real per-model ceiling is the *correct* long-term answer to the owner's
second axis, but requires a schema extension distinguishing `max_output_tokens` from `context_window`
as two separately-provenanced, independently-nullable fields, plus per-provider field-mapping research
(schemas are not uniform across the five configured providers). Tracked as
`ContextualWisdomLab/contextual-orchestrator#927`, not undertaken in this ADR.

## Decision

1. **Fix both existing preflight layers' probe calibration with diagnostic, escalate-on-evidence
   retries — do not introduce a new mechanism, and do not remove either existing layer.**
   - **Layer 1 (`_preflight_review_agents`, per candidate)**: for each candidate, send a first bounded
     probe at a modest token budget. If the response is empty/whitespace **and** its
     `choices[0].finish_reason == "length"` — the exact, provider-documented signature of "the
     budget was too small," not "the candidate is unreachable" — retry that *same* candidate once at
     a materially larger budget before recording it as rejected. Every other failure class (timeout,
     connection error, non-2xx status, or empty content with any other `finish_reason`) is **not**
     retried — those are not budget problems, and retrying would not fix them. This directly answers
     Devin Review's finding: a fixed tiny budget (whether `1`, matching upstream `probe()`'s own
     precedent, or any other single constant) would still misclassify a healthy reasoning-heavy
     candidate as down; escalating only on the specific evidence that the budget — not the candidate
     — was the problem does not have this failure mode, because a genuinely-down candidate never
     reaches the retry path.
   - **Layer 2 (the shell script's virtual-pool smoke request)**: apply the same diagnostic escalation
     to the real end-to-end `POST /v1/chat/completions` request against `"model":"orchestrator/free"`.
     This layer is **kept, not replaced by Layer 1** — Layer 1's per-candidate checks call
     `client.proxy_send_once` against explicit candidate agents directly and structurally cannot
     detect a bug in the virtual-pool's own dispatch/selection code, which is a different code path.
     This is not hypothetical: the 2026-08-30 gap-baseline entry for PR #1433 records exactly this
     split failure live — the launcher's own per-candidate preflight passed and the server reported
     healthy, while the shell script's separate virtual-pool request still came back `HTTP 502`. Any
     redesign that dropped Layer 2 in favor of Layer 1 alone would silently reintroduce that exact,
     already-documented gap. Bound Layer 2 to at most 2 total attempts (matching Layer 1's own retry
     bound) so a genuinely broken virtual-pool layer still fails fast.
   - **Keep each attempt's own wall-clock timeout short**, independent of the token-budget question.
     A candidate or route that is simply slow or hung should fail *that attempt* quickly and be
     recorded as not ready — tolerable under Layer 1's existing N-of-M design and Layer 2's bounded
     retry — rather than the preflight trying to avoid ever hitting a timeout by picking a "safer"
     token budget. This decouples the two previously-conflated failure modes (wrong budget vs. slow
     response) that made #1436's single-number tuning symptom-chase between them.
   - **This ADR deliberately does not fix specific numeric values** for the modest/escalated budgets
     or the per-attempt timeout. Committing to new constants here would repeat the same mistake at one
     remove — picking numbers by inspection rather than evidence. Both existing preflight layers
     already emit a structured per-route report (`_preflight_review_agents`'s `routes[]`, and the
     shell script's `preflight_report`/`gateway` JSON) — the follow-up implementation PR should add
     `finish_reason` and attempt-count to that evidence and let the actual values be set from real
     telemetry once deployed, not guessed in this document.
2. **Track `ContextualWisdomLab/contextual-orchestrator#926`** (an `inference`-scoped variant of
   `provider_readiness_report`/`probe()`) so the sidecar can eventually retire its hand-rolled Layer 1
   loop in favor of the gateway's own, better-tested mechanism. Not blocking for item 1.
3. **Track `ContextualWisdomLab/contextual-orchestrator#927`** (real, separately-provenanced
   `max_output_tokens`/`context_window` fields in `DiscoveredModel`/`ModelAgent`, fail-closed when
   unknown) so `max_tokens` selection can eventually be derived from real per-model data. Not blocking
   for item 1; this is the correct long-term closure of the owner's second axis.
4. **Explicitly reject** further tuning of one global `max_tokens` constant as a terminal fix for
   either layer. Every value tried so far (16, 4096) has failed for a different, evidenced reason tied
   to pool heterogeneity, confirming the owner's original objection rather than one bad guess needing
   one better guess.

## Consequences

- Both preflight layers become structurally tolerant of an individual attempt being wrong for a fixed
  token budget or briefly slow, which is the actual shape of the problem — instead of continuing to
  search for a number that fits every model in a heterogeneous pool, no single number is asked to, and
  a genuinely down candidate or route is still detected and reported, just no longer conflated with a
  merely-miscalibrated one.
- Total worst-case preflight latency grows modestly (up to one extra retry per candidate in Layer 1,
  up to one extra retry in Layer 2), bounded by the existing `REVIEW_PREFLIGHT_MAX_TOTAL_ROUTES` /
  `REVIEW_PREFLIGHT_TIMEOUT_SECONDS` ceiling and the new short per-attempt timeouts — this trades a
  small amount of latency for the diagnostic precision that avoids the false-outage misclassification
  Devin Review flagged.
- Keeping Layer 2 (not just Layer 1) means the preflight still proves the actual consumer-facing
  `orchestrator/free` route works, not only that individual candidates can respond in isolation —
  closing the PR #1433 gap class rather than reopening it.
- Items 2 and 3 are real `contextual-orchestrator` feature work, now tracked as real issues
  (`#926`, `#927`), and are explicitly not closed by this ADR.
- No production routing default changes; this is scoped to the sidecar's own liveness checks.
- **This is currently active, not theoretical**: the live reproduction in the Evidence trail below is
  from `noema-review` failing on this ADR's own PR while this ADR was being written, presently
  blocking that required check org-wide on every repo that routes through this sidecar. The
  implementation follow-up (a separate PR applying Decision §1) should be prioritized accordingly once
  this ADR is settled, not treated as ordinary backlog.

## Evidence trail

- `scripts/ci/contextual_orchestrator_review_launcher.py`: `_preflight_review_agents` (L200-271),
  `_preflight_with_fallback` (L274-291), `_chat_response_has_text` (L175-189),
  `REVIEW_MAX_OUTPUT_TOKENS = 4096` (L38) — the existing Layer 1 mechanism this ADR fixes, not
  introduces.
- `scripts/ci/contextual_orchestrator_review_sidecar.sh` — the existing Layer 2 virtual-pool smoke
  request this ADR keeps.
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
- **External, directly-fetched citations** (not from memory — verified live against the providers'
  own current documentation before citing, per this org's traceability convention):
  - OpenAI, [*Completions API guide*](https://developers.openai.com/api/docs/guides/completions):
    `finish_reason == "length"` — *"it's likely that max_tokens is too small and model runs out of
    tokens before it manages to [complete]"*; `max_completion_tokens` — *"an upper bound for the
    number of tokens that can be generated for a completion, including visible output tokens and
    reasoning tokens."*
  - OpenRouter, OpenAPI spec (`https://openrouter.ai/openapi.yaml`), `Model.context_length` —
    *"Maximum context length in tokens"* (required); `TopProviderInfo.max_completion_tokens` —
    *"Maximum completion tokens from the top provider. Input and output tokens share the context
    window, so the effective maximum output for a request is further limited by the context
    remaining after input tokens"* (nullable).
- `contextual_orchestrator/model_discovery.py`'s `DiscoveredModel` dataclass and
  `contextual_orchestrator/orchestrator.py`'s `ModelAgent` dataclass — confirmed absence of any
  context-window/max-output-tokens field via direct grep and full-dataclass read.
- `ContextualWisdomLab/contextual-orchestrator#926`, `#927` — the two tracked upstream follow-ups.
- 2026-08-30 gap-baseline entries ("sidecar-preflight outage: family_cap/max_tokens fixes confirmed
  working end to end...") for the live #1436→120s-timeout evidence this ADR responds to.
- **Live reproduction on this ADR's own PR**, verified directly against the job log rather than taken
  on report: `noema-review` on `ContextualWisdomLab/.github#1449` (job `99253418179`,
  `https://github.com/ContextualWisdomLab/.github/actions/runs/33310078256/job/99253418179`) —
  ```
  2026-08-30T11:58:29Z healthz and provider-route preflight confirmed after 30s (pid 3973)
  2026-08-30T12:00:29Z curl: (28) Operation timed out after 120002 milliseconds with 0 bytes received
  2026-08-30T12:00:29Z error: gateway preflight request could not reach the local sidecar
  ```
  Layer 1 (per-candidate) passed in 30s; Layer 2 (the virtual-pool smoke request) then hung for
  exactly the full 120s timeout with **zero bytes received** — not a slow response, not an error
  status, literally nothing back. This is a live, current instance of exactly the failure mode
  Decision §1's "keep each attempt's own wall-clock timeout short" design targets: under this ADR's
  design that hang would be capped at a short per-attempt timeout and recorded as one not-ready
  result, not a 120-second block on the whole required check. Confirms this ADR is fixing an active,
  currently-blocking defect, not a theoretical one.
