# ADR-0005: Replace the sidecar's single-shot, fixed-`max_tokens` gateway preflight with per-candidate readiness

- Status: proposed
- Date: 2026-08-30
- Scope: `ContextualWisdomLab/.github` central review pipelines' vendored `contextual-orchestrator`
  sidecar (`scripts/ci/contextual_orchestrator_review_sidecar.sh`), and a small upstream request to
  `ContextualWisdomLab/contextual-orchestrator`.
- Decision: Stop trying to pick a single, universally-correct `max_tokens` value for the sidecar's
  post-`healthz` gateway preflight. Replace the one hardcoded-budget completion request against the
  virtual `orchestrator/free` pool with a bounded, per-candidate probe over the catalog the sidecar
  already builds, using an **N-of-M "is at least one route usable" threshold** instead of a single
  request that must succeed. Track upstream extension of `contextual-orchestrator`'s existing
  `ModelClient.probe()` / `provider_readiness_report()` machinery with an inference-scoped variant, and
  track a separate, real per-model `max_tokens` ceiling in model discovery, as two follow-ups this ADR
  does not itself close.
- Ownership: `.github` owns the sidecar script and this ADR; `ContextualWisdomLab/contextual-orchestrator`
  owns the gateway internals cited as evidence and the two follow-up asks.
- Figma File ID: N/A (no customer UI).

## Context

`scripts/ci/contextual_orchestrator_review_sidecar.sh`'s gateway preflight sends one
`POST /v1/chat/completions` request against the virtual `orchestrator/free` model —
`{"model":"orchestrator/free","messages":[...,"Reply with just 'OK'."],"max_tokens":<N>,...}` — and
fails the whole sidecar (blocking `noema-review`/`opencode-review`/`strix` org-wide) unless that one
request returns non-empty `choices[0].message.content` within a fixed `curl --max-time`.

`N` has already been tuned twice in this investigation: 16 → 4096 (#1436), moving the failure from
"empty content at 16 tokens" (the provider's response consumed the whole budget on internal reasoning
before emitting visible content — see `ModelClient._response_content`'s own anticipated error message,
quoted below) to "120s timeout with zero bytes at 4096 tokens" on a separate run. Direct owner feedback
in response to that outcome, quoted verbatim because it is the reason this ADR exists:

> "max_tokens 이걸 고정하는 게 말이 안 되는데" — hardcoding this max_tokens doesn't make sense.
> "모델마다 max_tokens 허용치가 다 다른데" — each model has a genuinely different max_tokens allowance.

`orchestrator/free` is a heterogeneous pool (`nvidia_nim`, `openai`, `opencode_zen`, `bytez`,
`openrouter`, ... — see `contextual_orchestrator_review_policy.py`'s `PROVIDER_FAMILIES`), and which
candidate a given preflight run draws varies (family-cap admission is deterministic but
alphabetical-by-provider-then-model, and the catalog itself changes over time). A fixed `max_tokens`
is wrong on two independent, evidenced axes for a pool like this:

1. **Reasoning-token overhead differs per model.** A model that spends internal reasoning tokens before
   emitting visible content can exhaust a small budget with zero visible output, or (with a much larger
   budget) legitimately take far longer to finish than a fast, non-reasoning model would for the same
   budget — this is very likely what turned #1436's 4096-token raise into a 120-second timeout instead
   of a fix (see the 2026-08-30 gap-baseline entry's "third, distinct failure mode").
2. **The provider's own hard ceiling on `max_tokens`/`max_completion_tokens` differs per model.** Some
   providers reject a request outright (400) if `max_tokens` exceeds what that specific model supports;
   others support far more than a generic constant would ever request. A single number can therefore be
   simultaneously too small for one model's reasoning overhead and too large for another model's real
   ceiling — there is structurally no number that is not wrong for some member of the pool.

The standing session principle governing this decision, also quoted verbatim: "어떠한 휴리스틱과 Rule
of thumbs도 금지" — no heuristics or rules of thumb; a parameter needs actual justification from real
data, not a constant that happens to work today.

## Research: three questions, checked directly against `contextual-orchestrator` source

### 1. Does the gateway expose a way to separate a reasoning budget from a content budget?

**No — not on the endpoint this preflight uses, and not for how the preflight calls it.** Checked
directly in `contextual_orchestrator/orchestrator.py` and `server.py`, not assumed:

- `ReasoningEffortProfile`/`apply_request_profile()` (`reasoning_effort_profile.py`) is a real,
  capability-gated mechanism (`ModelAgent.reasoning_effort_supported: bool | None`, fail-closed unless
  proven `True`), but it is **additive, not substitutive**: `apply_request_profile()` always sets
  `payload["max_tokens"] = validated.max_output_tokens` regardless of whether `reasoning_effort` is
  also set. There is no "unbounded reasoning + bounded content" mode — `reasoning_effort` is a coarse
  enum (`none`/`low`/`medium`/`high`) that tells a supporting provider how to spend *within* the
  existing token budget, not a second, independently-sized budget.
- This mechanism is **opt-in at `TaskOrchestrator` construction**, not caller-controlled:
  `_role_effort_profile(role)` returns `None` unless the server was constructed with an explicit
  `role_effort_catalog` (`orchestrator.py:5530-5534`). It is also only reachable from role-based
  workflow steps; the sidecar's plain "Reply with just 'OK'" prompt against the virtual pool is not a
  role-scoped workflow call.
- Critically, the **public `/v1/chat/completions` endpoint the sidecar and Strix's client both call
  does not thread a caller-supplied `reasoning_effort`/`reasoning` field into orchestration at all.**
  `server.py`'s own docstrings say so directly: `_validate_chat_reasoning_effort` — "This gateway never
  threads the knob into `ModelClient` on the orchestration path. Known levels are accepted as
  default-effort no-ops"; `_validate_responses_reasoning` (the `/v1/responses` equivalent) — "This
  gateway proxies Responses but does not interpret or enforce reasoning controls." Both accept the
  field syntactically (so SDK defaults do not 400) and then discard it. Switching the preflight from
  `/v1/chat/completions` to `/v1/responses` would not gain anything here — the field is a documented
  no-op on both surfaces.

**Conclusion**: there is no lever, on any caller-facing surface this preflight (or Strix) can reach,
that separates "let the model think as long as it needs" from "cap what it can emit." This is the
honest "no" the coordinator's brief anticipated as a possible outcome.

### 2. Is a real-generation preflight even the right liveness mechanism — is there a cheaper or more direct signal?

**A better mechanism than the sidecar's hand-rolled curl probe already exists upstream, but it is not
"free" and it is not currently reachable at the sidecar's privilege level.** Checked directly:

- `ModelClient.probe(agent, timeout=...)` (`orchestrator.py:1483`) is a purpose-built liveness probe,
  documented as exactly the right idea: *"`/health` and `/v1/models` only prove process/model-registry
  liveness; this verifies the configured local model and deliberately exercises the chat path with one
  output token. It never retries, so a stuck local queue cannot be multiplied by the readiness check."*
  It isolates failures per agent (catches every exception, returns `status: "not_ready"` with a
  `failure_code` rather than raising) and runs against every agent type, not only local providers — the
  chat-probe payload construction is unconditional on `_is_local_provider_url`.
- `TaskOrchestrator.provider_readiness_report(refresh=True)` (`orchestrator.py:3441`) calls `probe()`
  across **every candidate agent in the pool**, isolating each candidate's outcome, and returns an
  aggregate plus a per-agent `items[]` list with `status`/`failure_code`/`latency_ms`. This is
  structurally exactly what the sidecar's single-shot "one candidate must work" curl probe is trying to
  approximate externally — except done per-candidate, with real diagnostics, instead of betting the
  whole preflight on whichever one candidate the pool router happens to draw. It is exposed as
  `GET /api/v1/provider_readiness/latest?refresh=true` (`server.py:5711-5715`).
- **This is not a free lunch, and the honest caveats matter as much as the discovery:**
  - `probe()` itself still hardcodes `max_tokens: 1` (`orchestrator.py:1536`) — even more aggressive
    than either value the sidecar has tried. It has the *same* reasoning-overhead vulnerability
    described above, per candidate. The win is not that this number is right for every model; the win
    is that the surface is already structured so one candidate's wrong-budget failure is an isolated,
    attributable `not_ready` entry (`failure_code: "provider_empty_probe_response"`), not an opaque
    all-or-nothing outage.
  - **Verified directly, and this is the one real blocker to adopting it as-is**: `/api/v1/*` GET
    routes, `provider_readiness/latest` included, are authorized at **`admin` scope**
    (`server.py`'s `_admin_purpose()` / the `self._authorize("admin", ...)` call guarding the
    `/api/v1/*` dispatch block), while `/v1/chat/completions` — what the sidecar's bearer token is
    scoped for today — is authorized at the separate, narrower **`inference` scope**
    (`self._authorize("inference")` on the chat/completions and `/v1/models` handlers). Provisioning
    the CI review sidecar with an admin-scoped token just to call a readiness endpoint would be a real
    privilege widening (full operator/admin surface, not merely "can it serve a chat completion") that
    this ADR explicitly does **not** recommend.

**Conclusion**: the right-shaped mechanism exists upstream, but adopting it exactly as-is would trade a
token-budget problem for a privilege-scope problem. The actionable move today is to replicate its
*shape* (per-candidate, isolated-failure, N-of-M) inside the sidecar itself, over the catalog it
already builds, using the same `inference`-scoped bearer token it already holds — see Decision below —
and separately ask upstream for an `inference`-scoped narrow readiness probe so the sidecar can retire
its own hand-rolled version later.

### 3. If a numeric budget is still needed, can it be derived per-model from real discovered data?

**Not today — confirmed as a genuine, currently-open gap, not assumed.** Checked both schemas directly:

- `contextual_orchestrator/model_discovery.py`'s `DiscoveredModel` dataclass carries `provider_name`,
  `model_id`, `credential_name`, `chat_base_url`, `auth_scheme`, `capabilities`, `input_modalities`,
  `output_modalities`, pricing (`prompt_price_per_1k`, `completion_price_per_1k`, `unit_prices`),
  `is_free`, and ZDR/privacy flags. **No field for context window, max output tokens, or max
  completion tokens exists anywhere in this dataclass** (a repo-wide grep for
  `context_length|context_window|max_output_tokens|max_completion_tokens|"limit"` inside this file
  returns nothing).
- `contextual_orchestrator/orchestrator.py`'s `ModelAgent` dataclass (the routing-time representation)
  likewise carries no such field — `reasoning_effort_supported` and `stream_usage_supported` are the
  only capability flags it has.
- This is real, closeable data loss: several of the providers this discovery pipeline already queries
  (e.g. OpenRouter's `/api/v1/models` response, `models.dev`'s `api.json`) commonly publish a per-model
  context-window / max-output-tokens field in the exact list responses `model_discovery.py` already
  fetches and parses — it is being read and then dropped, not unavailable.

**Conclusion**: deriving a real per-model ceiling is the *correct* long-term answer to the owner's
second axis, but it requires a schema extension to `DiscoveredModel`/`ModelAgent` plus per-provider
field-mapping research (a Ponytail-gate task in its own right — provider list-response shapes need
verifying individually, not assumed uniform) and a place in `ModelClient` to clamp a requested
`max_tokens` to `min(requested, discovered_ceiling)`, fail-closed the same way
`reasoning_effort_supported=None` already fails closed when support is unproven. This is real,
substantial `contextual-orchestrator` work, not a same-day sidecar patch — tracked as a follow-up below,
not undertaken in this ADR.

## Decision

1. **Replace the sidecar's single-shot preflight with a bounded per-candidate probe and an N-of-M
   threshold**, over the same catalog the sidecar's launcher already builds (the same candidate list
   `contextual_orchestrator_review_policy.py`'s family-cap selection admits). For each admitted
   candidate (bounded by the existing `REVIEW_PREFLIGHT_MAX_TOTAL_ROUTES`), send one bounded
   `POST /v1/chat/completions` request pinned to that specific model id (not the virtual
   `orchestrator/free` pool, so the sidecar controls exactly which candidate each probe exercises),
   with a small, deliberately conservative `max_tokens` (matching upstream `probe()`'s own precedent —
   this ADR does not invent a new number, it reuses the one the gateway's own author already chose for
   the same purpose). Treat the preflight as passed once **any** candidate returns real content, not
   only the first or only the one the pool router happens to draw. This does not require picking a
   number that is right for every model — it requires tolerating that some candidates will fail their
   probe for reasons unrelated to the gateway being down (token-budget mismatch among them), the same
   way `provider_readiness_report`'s own aggregate already tolerates partial `not_ready` results.
2. **File an upstream ask on `ContextualWisdomLab/contextual-orchestrator`** for an `inference`-scoped
   variant of `provider_readiness_report`/`probe()` (or a scope widening of the existing endpoint that
   the gateway's own security model is comfortable with) so the sidecar can eventually retire its
   hand-rolled per-candidate loop in favor of the gateway's own, better-tested mechanism. Not blocking
   for item 1.
3. **File an upstream ask on `ContextualWisdomLab/contextual-orchestrator`** to extend
   `DiscoveredModel`/`ModelAgent` with a real, provider-sourced max-output-tokens/context-window field,
   fail-closed when a provider does not publish one, so `max_tokens` selection (here and everywhere
   else in the codebase that currently uses a single constant) can eventually be derived from real
   per-model data rather than any constant. Not blocking for item 1; this is the correct long-term
   closure of the owner's second axis.
4. **Explicitly reject** further tuning of one global `max_tokens` constant as a terminal fix. Every
   value tried so far (16, 4096) has failed for a different, evidenced reason tied to pool
   heterogeneity, confirming the owner's original objection rather than one bad guess needing one
   better guess.

## Consequences

- The preflight becomes structurally tolerant of individual candidates being wrong for a fixed token
  budget, which is the actual shape of the problem — instead of continuing to search for a number that
  fits every model in a heterogeneous pool, no single number is asked to.
- The preflight's total worst-case latency grows with the number of candidates probed (bounded by the
  existing `REVIEW_PREFLIGHT_MAX_TOTAL_ROUTES` / `REVIEW_PREFLIGHT_TIMEOUT_SECONDS` ceiling already
  governing family-cap candidate counts) rather than being one fixed-cost request; this trades latency
  for the isolation that made the family-cap fix's own tolerant-of-partial-failure design work.
  Each candidate probe should stay short (small, conservative `max_tokens`, short per-candidate
  timeout) precisely because it no longer needs to prove one specific candidate works — only that one
  of several does.
- Item 1 is implementable now, inside `.github`, without upstream changes. Items 2 and 3 are real
  `contextual-orchestrator` feature work and are explicitly not closed by this ADR — they are the
  more complete answers the coordinator's brief asked to be surfaced honestly rather than invented.
- No production routing default changes; this is scoped to the sidecar's own liveness check.

## Evidence trail

- `ModelClient._response_content` (`orchestrator.py:1648-1660`) — the exact "reasoning without content"
  failure this whole investigation traces to, already anticipated in the codebase's own error message:
  *"provider {agent.id} returned reasoning without content; for mlx-lm set
  chat_template_args={"enable_thinking": false} or increase max_output_tokens"* — note even this
  upstream guidance is "increase the budget," the same reactive strategy #1436 tried and this ADR
  moves away from.
- `ModelClient.apply_effort_profile` / `reasoning_effort_profile.apply_request_profile` — confirms
  `max_tokens` is always set regardless of `reasoning_effort`.
- `server.py:3731-3758` (`_validate_chat_reasoning_effort`), `server.py:4775-4809`
  (`_validate_responses_reasoning`) — confirms both `reasoning_effort` and `reasoning` are validated,
  documented no-ops on the caller-facing surfaces this preflight and Strix use.
- `ModelClient.probe` (`orchestrator.py:1483-1561`), `TaskOrchestrator.provider_readiness_report`
  (`orchestrator.py:3441-3486`), `server.py:5711-5715` (`GET /api/v1/provider_readiness/latest`) —
  the existing per-candidate readiness mechanism, and its admin-scope gate
  (`server.py`'s `_admin_purpose` / `_authorize("admin", ...)` vs. the `inference`-scoped
  `/v1/chat/completions` and `/v1/models` handlers).
- `contextual_orchestrator/model_discovery.py`'s `DiscoveredModel` dataclass and
  `contextual_orchestrator/orchestrator.py`'s `ModelAgent` dataclass — confirmed absence of any
  context-window/max-output-tokens field via direct grep and full-dataclass read.
- 2026-08-30 gap-baseline entries ("sidecar-preflight outage: family_cap/max_tokens fixes confirmed
  working end to end...") for the live #1436→120s-timeout evidence this ADR responds to.
