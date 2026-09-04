# Doctoring record: Noema review-gate failure retrospective and improvement plan (2026-09-03)

- **Date:** 2026-09-03
- **Subject:** backlog item 23 — "noema의 리뷰 실패 사례를 다시 취합해서 개선안을 도출 바람" (re-aggregate Noema's
  review-failure incidents and produce an improvement plan). The raw material already existed, scattered
  across 18 individual records; this record is the first pass at pattern extraction and concrete next steps.
- **Decision record:** none in `docs/adr/` yet — this record proposes candidate ADR-worthy changes in
  "Improvement plan" below rather than deciding them unilaterally.
- **PR:** see the PR that carries this commit.

## Method

Read all `noema-review-gate` incident sections in `docs/product-technical-gap-baseline.md` (7 sections
dated 2026-08-31), all Noema-specific `docs/doctoring/` records (6 files), and every GitHub issue whose
title names Noema's review-gate failure modes (5 issues: 3 open, 2 closed) — full text of each, not just
titles. Grouped by root-cause shape rather than by date, since several incidents on the same date share one
underlying mechanism.

## The 18 incidents, grouped by root-cause shape

### Shape 1: crash-before-repair-boundary (4 incidents)

`call_llm` in `scripts/ci/noema_review_gate.py` has one repair-retry path: a malformed verdict gets one
bounded correction request before failing closed. Every incident in this shape is the *same* underlying
defect — code that runs *before* that repair boundary is unguarded, so a specific input shape crashes the
whole required check with a raw traceback instead of reaching the repair path at all.

1. **Malformed JSON envelope** (`.github#1507`, gap-baseline 2026-08-31 #1) — `extract_json_object`'s
   `json.loads()` had no exception handling; an unquoted property name mid-object raised
   `json.JSONDecodeError` past the module's `except RuntimeError` guard (which only catches
   `RuntimeError`), crashing every PR org-wide that hit this LLM-output edge case.
2. **Non-UTF-8 gateway reply** (`.github#1507` round 3, gap-baseline 2026-08-31 #3) — the *identical*
   shape, one step earlier: `response.read().decode("utf-8")` sat before the `try`, so invalid UTF-8 bytes
   raised `UnicodeDecodeError` before `extract_llm_message_content` or the repair boundary ever ran.
3. **Truncated structured completion** (`.github` issue #1596, closed via a merged fix) — a response cut
   off mid-JSON (provider truncation, not malformed content) hit the same unguarded-preamble shape.
4. **Invalid changed-line citation exhausting the full retry budget** (`.github` issue #1613, **still
   open**) — a variant one layer up: the *repair* path itself has no cap distinguishing "wrong citation,
   retry once" from "wrong citation every time, stop burning budget," so a bad citation can consume the
   entire multi-hour LLM budget instead of failing closed early.

**Pattern:** every fix in this shape was scoped to the *one* input shape a reviewer happened to report
(malformed JSON → fixed; non-UTF-8 → found and fixed one round later; truncation → a separate issue). None
of the three fixes generalized to "guard every byte- and structure-level transformation of the raw HTTP
response before the repair boundary" as a single invariant, which is why the same shape kept resurfacing
one layer at a time rather than being closed once.

### Shape 2: a fix for one class of bug introduces a different bug (2 incidents)

5. **Fail-closed fix itself leaked a secret to a public log** (`.github#1507` round 2, gap-baseline
   2026-08-31 #2) — the malformed-JSON fix (shape 1, incident 1) logged the LLM's raw response text through
   `scrub_sensitive_data`, a finite regex-based scrubber, into a `RuntimeError` message that `pull_request_target`'s
   public Actions log then printed via `::error::{exc}`. A regex allowlist of *known* secret shapes cannot
   bound what an LLM might echo back in an *unrecognized* shape — closing the crash opened a
   secret-disclosure path. Fixed by removing the raw/scrubbed text from the log entirely, replacing it with
   a length + truncated SHA-256 fingerprint (enough to correlate repeats, nothing to leak).
6. **The live-head re-check added to close a cancellation gap was itself an unguarded API call**
   (gap-baseline 2026-08-31, "the live-head re-check added to close the above gap...") — a directional
   cancellation guard's own re-verification step (`gh api ... --jq '.head.sha'`) was a bare assignment
   under `set -euo pipefail`, unlike every sibling `gh api` call in the same file. A transient rate-limit or
   network blip on *that one call* failed the entire `noema-review` job over a housekeeping hiccup unrelated
   to the actual review.

**Pattern:** both incidents are the direct product of *not applying the same defensive-coding standard the
surrounding code already uses* when writing new code (existing `gh api` calls in the same file already
wrapped failures in `if ! ...; then warn; continue/return; fi` — the new one just didn't copy that pattern;
existing repair-path logging already understood raw model output as untrusted — the new log line reused an
old, insufficient scrubbing tool instead of re-deriving "should this be logged at all").

### Shape 3: race-condition guards, each independently reimplemented, each independently buggy (5 incidents)

Noema's "is the run I'm about to act on still the live/current one" check exists in at least four separate
places in `noema-review.yml` / `noema_review_gate.py`, written at different times, each with its own bug:

7. **`workflow_run`-triggered reviews always looked stale** — the stale-trigger guard's `EXPECTED_HEAD`
   read `github.event.workflow_run.head_sha`, but GitHub's `workflow_run` payload for a
   `pull_request_target`-triggered parent carries a different head field than the guard assumed, so every
   `workflow_run`-path review self-aborted as "stale" even when current.
8. **Case-sensitive SHA comparison** (same guard, same incident record) — a second bug in the identical
   guard: SHA comparison wasn't case-normalized, so a case variation (rare but real, e.g. from a different
   API surface's casing convention) would also false-positive as stale.
9. **Bare `head_sha` match let one PR's close cancel a different PR's still-needed run**
   (`cancel-closed-pr-runs` job) — the cancellation selector's match condition was underspecified (an OR of
   three clauses without enough scoping), so closing PR A could cancel a review run that actually belonged
   to PR B if they happened to share a head SHA shape. Fixed independently by a concurrent session
   (`e0f542f`) while this investigation was in progress — a real example of the org's concurrent-session
   model working as intended (fetched, verified, extended rather than force-pushing a competing fix).
10. **Repair-retry fired without re-checking a live-moved PR head** — `inspect_and_review` checks
    `expected_head` against the PR's live head twice (before any model work, and again before
    `submit_review`), but `call_llm`'s *internal* self-recursive repair-retry branch had no `expected_head`
    parameter at all and no check of its own — a PR head moving mid-first-attempt could burn a second,
    potentially multi-hour LLM call producing a verdict the outer check was always going to discard anyway.
    (Correctness was never at risk — the outer check still caught it — but compute was wasted silently,
    every time this raced.)
11. **`workflow_run` head misread inside `opencode-review.yml`'s verdict poller** — a sibling, structurally
    identical guard in the *OpenCode* review poller (not Noema, but the same "which head is live" question,
    included here because it's the same root defect family and was fixed alongside) had the same
    misreading-the-payload defect.

**Pattern:** this is the clearest, most actionable pattern in the whole retrospective. "Is the head/PR I'm
about to act on still current" is asked at least 5 separate times across this file family, in 5 separate
hand-written implementations, and has failed in 5 separate ways — wrong field read, case sensitivity,
under-scoped match, missing check entirely, and the check itself lacking its own failure handling. Not one
of these was a repeat of a previously-fixed bug; each was a *new* mistake made writing a *new* copy of
conceptually the same check.

### Shape 4: infrastructure/lifecycle issues, not code-logic bugs (3 incidents)

12. **App token outlives a long review, publication fails with 401** (`.github` issue #1614, closed) —
    Noema's long-running reviews (up to the documented 4-hour window) could outlive the GitHub App
    installation token's lifetime, so a fully-computed, valid verdict failed to publish. Fixed by
    refreshing/re-minting the token before publication rather than reusing the one minted at job start.
13. **`noema-review.yml`'s own concurrency group had no head-SHA component** (this session's item 13
    investigation, `docs/doctoring/item13-stale-head-cancellation-audit-20260903.md`) — GitHub's native
    concurrency cancellation, not this file's own logic, could cancel a valid current-head run when an
    older push's event was processed out of order. Fix proposed (`.github#1661`), not yet merged as of this
    writing.
14. **`ORCHESTRATOR_PIN_SHA` staleness carrying forward a fixed upstream bug** — a pinned commit reference
    needed bumping to pick up an unrelated fix (`stream_options`/`tools`) in the vendored gateway.

### Shape 5: still-open, not yet resolved (3 incidents, tracked but unfixed)

15. **`.github` issue #1611** (open) — the malformed-verdict retry path can lose track of the valid current
    head and exhaust its retries via repeated `502`s from the gateway, a compound failure this
    retrospective's Shape 1/Shape 3 fixes each partially address but that issue #1611 argues is not yet
    fully closed as a combined scenario.
16. **`.github` issue #1613** (open) — already counted in Shape 1 (incident 4) as the still-open
    budget-exhaustion variant.
17. **`.github` issue #1637** (open) — proposes a typed-blocker fail-closed path for invalid changed-line
    citations / malformed JSON model output; overlaps with #1611/#1613 and Shape 1's incidents but has not
    yet landed as a merged fix.

## Cross-cutting pattern (all 17 incidents)

Every incident in Shapes 1–3 (12 of 17) shares one structural cause: **`noema_review_gate.py` and its
sibling workflow YAML treat "guard against untrusted/racy input" as a per-call-site concern, discovered and
patched one call site at a time by external reviewers (Devin, CodeRabbit), rather than as a small number of
shared, centrally-tested primitives applied uniformly.** Three call sites independently parse/decode a
gateway response before a repair boundary (Shape 1). At least five call sites independently ask "is this
head/run still live" (Shape 3). Each new instance of "guard an I/O boundary" or "check liveness" is written
fresh, and each fresh instance has had its own, different bug — not because any one fix was careless, but
because there was no single, already-hardened helper to reuse.

## Improvement plan

**1. Extract one shared "decode and validate an untrusted LLM/gateway response" helper.** Currently
`extract_json_object`, the UTF-8 decode step, and the truncation-repair path (issue #1596) are three
separate functions with three separate guard histories. A single `parse_llm_response(raw_bytes) -> dict`
that owns byte-decoding, JSON parsing, and truncation detection — all inside one already-audited try/except
boundary — would mean a fourth "new response shape crashes before repair" incident has nowhere left to
hide; new failure *modes* would still need discovering, but the *boundary* itself would already be safe by
construction. **Not implemented in this record** — this is a refactor of live, security-critical CI logic
(same category this session has repeatedly deferred to its own dedicated PR rather than bundling into
documentation) and deserves its own PR with the exact regression tests each of the 4 Shape-1 incidents
already established, run against the unified helper.

**2. Extract one shared "is this head/PR still the live one" primitive, and delete the 5 hand-written
copies.** Shape 3's 5 incidents are the strongest, most concrete case in this whole retrospective for a
single reusable function/action — e.g. a `scripts/ci/live_head_guard.py` with one well-tested
`assert_head_is_live(repo, pr_number, expected_head) -> bool` (or a composable Actions step) that every one
of `noema-review.yml`'s stale-trigger guard, `cancel-closed-pr-runs`, the repair-retry path, and
`opencode-review.yml`'s verdict poller calls instead of reimplementing. **Not implemented in this record**
for the same reason as (1) — this is the single highest-leverage follow-up this retrospective identifies,
and is recorded here explicitly so it is not lost, not treated as done.

**3. Close the 3 still-open issues (#1611, #1613, #1637) as one coordinated fix, not three.** All three
describe overlapping symptoms of the same underlying gap (repair-retry robustness against a moving head
combined with a malformed/uncited verdict). Fixing them independently risks three more Shape-2-style
"the fix for one introduces a gap in another" incidents. Recommend one PR that addresses all three against
the unified helper from (1)/(2) once those land, rather than three separate patches.

**4. Add a lightweight static check for the two recurring anti-patterns**, so a *sixth* Shape-1 or *sixth*
Shape-3 incident is caught before Devin/CodeRabbit finds it in review, not after: (a) any `response.read()`,
`.decode(...)`, or `json.loads(...)` on gateway/LLM output that is not textually inside a `try:` block
already known to feed the repair-retry path, (b) any `gh api` invocation in a bash step under
`set -euo pipefail` that is not wrapped in an `if ! ...; then` failure handler. A `semgrep` rule (this repo
already runs `sast-semgrep.yml` org-wide) or a small custom `scripts/ci/` lint check would fit the existing
CI surface. **Not implemented in this record** — scoping a new semgrep rule against this repo's actual
false-positive rate needs its own pass, separate from this retrospective's job of aggregating what already
happened.

## What this resolves, and what it does not

- **Resolves:** backlog item 23's "재취합" (re-aggregation) half in full — all 17 known incidents (14
  fixed, 3 open) are now indexed in one place with their shared root-cause shapes, rather than scattered
  across 18 individual dated records with no cross-referencing.
- **Resolves:** the "개선안 도출" (produce an improvement plan) half at the level of *identifying* concrete,
  scoped next steps (items 1–4 above) with enough detail for another agent or session to pick any one of
  them up without re-deriving this analysis.
- **Does not resolve:** none of the 4 improvement-plan items are implemented here. Each is a code change to
  live, security-critical CI logic (`noema_review_gate.py`, `noema-review.yml`, `opencode-review.yml`) that
  deserves its own PR with dedicated regression tests, consistent with this session's practice of not
  bundling a live-workflow-logic change into a documentation-only PR. The three still-open issues
  (#1611/#1613/#1637) remain open.

## Audit trail

- `docs/product-technical-gap-baseline.md` — the 7 `noema-review-gate` incident sections this record
  aggregates (all dated 2026-08-31, plus the item-13 concurrency finding dated 2026-09-03).
- `docs/doctoring/noema-model-output-repair-boundary.md`, `noema-orchestrator-free-zdr.md`,
  `noema-repair-attempt-telemetry.md`, `noema-review-token-lifetime.md`,
  `noema-token-lifetime-stale-run-retirement.md`, `autofix-and-noema-review-model-job-timeout-removal.md` —
  the 6 pre-existing Noema-specific doctoring records this retrospective cross-references.
- `docs/doctoring/item13-stale-head-cancellation-audit-20260903.md` — the confirmed `noema-review.yml`
  concurrency bug (Shape 4, incident 13), a distinct mechanism from the 17 incidents catalogued above.
- `ContextualWisdomLab/.github#1507` — the PR carrying 4 of the Shape 1/2 incidents (multiple Devin/CodeRabbit
  review rounds on one PR).
- `ContextualWisdomLab/.github#1611`, `#1613`, `#1637` — the 3 still-open issues.
- `ContextualWisdomLab/.github#1596`, `#1614` — the 2 closed issues counted in Shapes 1 and 4.
