# Noema repair-attempt telemetry

## Incident

`ContextualWisdomLab/html4tree` run `33560972491`, job `100033086428`
(`noema-review` workflow, step 13 "Prepare Noema model verdict") failed on
2026-09-02, having run roughly 48 minutes (`01:40:17`-`02:28:31`). The
terminal diagnostic:

```
##[error]Noema bounded repair transport was exhausted; initial failure: Noema LLM
response was not valid JSON (Expecting property name enclosed in double quotes:
line 1 column 1530 (char 1529)). Raw model output is not logged here (this
pull_request_target workflow's logs are public and a finite secret-scrub
pattern list cannot guarantee an LLM-echoed or hallucinated credential in an
unrecognized shape is caught): response length=1890 chars, sha256=34a4258a883c7e74.;
repair failure: NoemaRepairDeadlineExceeded: Noema repair exceeded 900-second
absolute wall-clock deadline
```

The repo owner's complaint (2026-09-02, translated): the failure "just says
'900 second timeout'" with "absolutely no specifics" -- not even for
telemetry purposes could anyone tell *why* the repair attempt took 900
seconds.

## What the 900-second window actually contained (before this change)

`scripts/ci/noema_review_gate.py`'s `call_llm` makes **exactly one** HTTP
request per invocation and recurses **exactly once** (`is_retry=True`) after
the first attempt's verdict fails deterministic validation -- there is no
internal retry loop, no per-candidate backoff, and no multiple sub-attempts
inside the repair path. The single repair attempt is wrapped in
`_repair_wall_clock_deadline(NOEMA_REPAIR_DEADLINE_SECONDS)`, a SIGALRM-based
`ITIMER_REAL` bound covering the entire open/read/decode/validate sequence
(`scripts/ci/noema_review_gate.py:1128` area). Before this change, nothing
recorded *when* that one attempt started, how long it actually ran before the
alarm fired, which sub-phase (connecting, reading the response, decoding the
body, or validating the verdict) it was in, or which `orchestrator/free`
candidate model it ever reached. The only signal was the bare
`NoemaRepairDeadlineExceeded` message quoted above. Separately, the run's own
48-minute total duration against a 900-second (15-minute) repair budget
implies the *primary* (unbounded, per ADR-0003) call itself consumed roughly
33 minutes before ever reaching the repair path -- a fact the old diagnostic
also could not surface, because nothing timed the primary attempt either.

## Decision

1. **Telemetry.** `call_llm` now times every attempt (primary and repair)
   with `time.monotonic()`, tracks the furthest phase reached
   (`connecting`/`reading`/`decoding`/`validating`), and best-effort reads
   which model served the response via a new `_extract_served_model` helper
   (reads only the OpenAI-compatible envelope's top-level `model` field,
   never the untrusted `content` body). Every attempt emits exactly one
   `::notice::` (primary failure handing off to repair, or any success) or
   `::warning::` (a repair attempt that ultimately failed) GitHub Actions
   annotation, and the same duration/phase/attempt-count breakdown is folded
   into the raised `NoemaModelOutputError`/`NoemaTransportError`/`RuntimeError`
   message itself -- so the information survives even if only the final
   `::error::` line in `main()`'s trace is read. None of this logs raw model
   content, matching the existing no-raw-content discipline `extract_json_object`
   and `decode_llm_response_body` already established.
2. **Structured output request.** Both the primary and the repair call now
   declare `NOEMA_VERDICT_RESPONSE_FORMAT`, an OpenAI Chat Completions
   `response_format: {"type": "json_schema", "json_schema": {"strict": true, ...}}`
   envelope matching `validate_substantive_verdict`'s exact verdict shape.
   contextual-orchestrator's `orchestrator/free` sidecar is a proven
   OpenAI-compatible endpoint (ADR-0003), so this is the caller correctly
   declaring what it wants in that endpoint's own contract -- not a
   reimplementation of gateway-owned retry/candidate-exclusion policy. This
   should reduce how often the repair path is even entered, for any
   candidate whose backend genuinely honors structured outputs. Whether
   contextual-orchestrator's gateway correctly *translates* this
   OpenAI-shaped request for a routed backend that does not natively speak
   it (e.g. a raw Claude model needing forced tool-calling instead) is that
   gateway's own translation responsibility, not this caller's; building
   per-provider format detection here would recreate the layering violation
   the repo owner already rejected in PR #1602 (see below). This is a new,
   currently unobserved failure surface worth watching through the
   `served_model` telemetry this same change adds: if a specific candidate
   starts erroring on `response_format` instead of merely returning
   malformed JSON, that will now be visible per-attempt instead of
   collapsing into the same opaque failure class.
3. **Local, lossless JSON repair.** `extract_json_object` now makes one
   additional local attempt through `_strip_trailing_commas_outside_strings`
   before failing closed -- removing a comma that appears immediately before
   a closing `}`/`]` outside of any string literal. This is deliberately
   narrow: `{"a":1,}` and `{"a":1}` encode identical data, so this transform
   can never alter or fabricate verdict content the way a guess-based repair
   of an unrecognized malformation shape could. It is a pure local string
   transform on bytes already received -- no network call, no model
   re-prompt, no candidate selection -- so it does not reimplement the
   gateway-owned JSON-validation/repair policy either. It does **not**
   attempt to guess-repair the malformation class actually seen in the
   evidence above (`"Expecting property name enclosed in double quotes"` at
   char 1529 of 1890, mid-string -- not a trailing comma); that class stays
   correctly fail-closed, now with the added phase/duration telemetry from
   item 1.
4. **The 900-second bound itself is left unauthorized/arbitrary, not
   defended as intentional.** See "Owner correction on the 900-second bound"
   below.

## Layering: what was deliberately *not* implemented here

PR #1602 (closed 2026-09-01 by the repo owner) proposed adding truncation
recovery, `finish_reason`/usage-metadata tracking, and a compact retry
budget directly to `noema_review_gate.py`. The owner's closing reasoning
(translated): JSON validation of structured output, upstream (model-facing)
repair, candidate exclusion, bounded fallback to another model/provider, and
attempt-budget/usage-trace accounting belong to the shared gateway
`contextual-orchestrator`, because implementing them in the Noema caller
would make OpenCode, Strix, and other product-specific callers reimplement
the same policy with divergent retry counts and error classification. That
ruling moved the common repair contract to
`ContextualWisdomLab/contextual-orchestrator#998` (and its current
structured-output-validation successor, `#1004`, tracked separately in this
session -- not duplicated here).

This change respects that ruling: it adds a declared *request contract*
(`response_format`) and a *lossless local string fixup* on bytes already in
hand, neither of which selects between candidate models, retries against the
network, or accumulates any cross-call attempt budget. It implements no
model-exclusion or cross-candidate fallback logic; that stays entirely
`contextual-orchestrator`'s.

## Owner correction on the 900-second bound

The repo owner's follow-up (2026-09-02, translated), received while this
telemetry work was in progress: "I never specified 900 seconds." Checking
PR #1617 (which introduced `NOEMA_REPAIR_DEADLINE_SECONDS = 15 * 60`,
`docs/doctoring/noema-model-output-repair-boundary.md`) confirms the value
was picked with no repair-duration data behind it -- none existed yet, since
this telemetry change is what first starts recording real repair durations.
The owner identified this as exactly the class of unresearched heuristic
`docs/product-goal-directive.md` SS6 prohibits ("가중치는 임의로 정하지 말고
... 어떠한 휴리스틱과 Rule of thumbs도 금지").

Independently, this constant also textually collides with
`docs/adr/0003-contextual-orchestrator-vendored-free-zdr.md`'s 2026-08-31
amendment ("model inference has no repository- or application-configured
fixed wall-clock timeout ... including an initial completion ping, warm-up,
retry, **repair verdict**, or substantive review call") -- landed
2026-09-01T06:01:54Z, roughly 11.5 hours *before* PR #1617
(2026-09-01T17:33:47Z) added the fixed 900-second repair bound. PR #1617's
own doctoring entry asserts a repair/primary distinction ("The primary
review keeps the accepted contextual-orchestrator no-fixed-inference-timeout
contract. The *single corrective attempt* is different...") without citing
or amending ADR-0003, whose own enumerated list explicitly includes "repair
verdict." This reads as an unreconciled conflict, not a documented
carve-out.

**Resolution taken in this change:** the constant is kept (an unbounded
local retry loop is its own failure mode -- the owner's guidance was not to
remove the bound without a replacement), but is left explicitly and visibly
unresolved rather than re-justified after the fact:

- The value is unchanged at `15 * 60` -- picking a *different* round number
  would repeat the same mistake the owner flagged, not fix it.
- The module-level comment above `NOEMA_REPAIR_DEADLINE_SECONDS` now states
  plainly that this is a placeholder, not data-derived, and cites this
  document.
- The telemetry added in this same change (item 1 above) is what makes a
  future, data-derived revision possible: once real repair-attempt durations
  accumulate in Actions logs across runs, a follow-up change can set the
  bound from an actual measured distribution (e.g. an observed p99 plus
  margin) instead of a guess, and/or revisit whether ADR-0003's "no fixed
  timeout" amendment should simply extend to the repair path outright now
  that items 2-3 above should make reaching it materially rarer.
- This is flagged here as **still open** for the owner's explicit decision;
  this change does not decide it unilaterally.

## Verification

`tests/test_noema_repair_attempt_telemetry.py` is new and covers: the
OpenAI structured-output envelope appears identically on both the primary
and repair request; `_extract_served_model` is best-effort, scrubbed, and
length-bounded; `_classify_attempt_outcome` orders `NoemaRepairDeadlineExceeded`
before the broader transport-error class (it is itself an `OSError`
subclass); a simulated repair-deadline-exceeded run (mocked transport, no
real network call, matching this repo's existing convention) asserts the
full `::notice::`/`::warning::` pair and the enriched exception message
carry `repair attempts=1`, a `repair duration=`, and `phase=reading`;
`_strip_trailing_commas_outside_strings` is lossless and string-literal-safe;
`extract_json_object` recovers a trailing-comma malformation locally (with
its own notice) while still failing closed on the unrelated malformation
class the actual `html4tree` incident hit; and a successful repair attempt
still logs a success line with its served model. The full existing
`tests/test_noema_model_output_failure_classification.py` and
`tests/test_noema_review_gate.py` suites continue to pass unmodified against
the enriched messages (they assert with `in`, not exact equality).

## References

`docs/adr/0003-contextual-orchestrator-vendored-free-zdr.md` (2026-08-31
amendment on fixed wall-clock timeouts; 2026-08-31 amendment on independent
Noema review).

`docs/doctoring/noema-model-output-repair-boundary.md` (PR #1617's original
malformed-verdict repair boundary decision).

`docs/product-goal-directive.md` SS6 (prohibition on unresearched
heuristics/weights).

OpenAI. (2026). *Structured Outputs -- Chat Completions `response_format`
with `json_schema`*. OpenAI API documentation.

`ContextualWisdomLab/.github#1602` (closed 2026-09-01; the layering ruling
this change's scope respects).
