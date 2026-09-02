# Doctoring record: product-goal-directive.md (the `/goal` 4000-character cap)

- **Date:** 2026-08-30
- **Subject:** `/goal`'s session-condition field truncates at 4000 characters.
  The owner's full nine-section autonomous PR review→fix→merge→develop loop
  directive is ~7900 characters and would lose specific, deliberate
  constraints if summarized to fit. Introduced
  [`docs/product-goal-directive.md`](../product-goal-directive.md) to hold the
  directive verbatim, with no length limit, and linked it from `AGENTS.md`,
  `CLAUDE.md`, and `docs/CWL-MASTER-CONTEXT.md` §10 so any agent reads it
  during normal onboarding regardless of how a loop was started.
- **Decision record:** none yet in `docs/adr/` — this is a documentation/process
  change, not an architecture decision; §7 of `docs/CWL-MASTER-CONTEXT.md`
  ("Durable knowledge lives in the repo / Project / KG, NOT in an agent's
  private memory") is the binding convention this follows.
- **PR:** ContextualWisdomLab/.github#1429.

## What changed

- New file `docs/product-goal-directive.md`: the nine-section directive
  recorded verbatim (Korean, as authored), each section given a short English
  heading, plus a `/goal`-sized pointer text a future session can paste in
  instead of the full directive.
- `AGENTS.md`'s `<!-- CWL-ENTRY -->` read-first block, `CLAUDE.md`'s "Read
  first" section, and `docs/CWL-MASTER-CONTEXT.md` §10 ("Current state") each
  gained one linking sentence to the new file.

## Review findings and reconciliation (Devin Review, PR #1429)

Devin Review's automated pass on this PR raised two findings against the new
file, both confirmed valid and fixed in place (not by editing the verbatim
quoted directive text, which is meant to preserve the owner's own wording
unmodified):

1. **Missing traceability record.** The PR introduced a new standing policy
   (the `/goal`-pointer mechanism itself) without a `docs/doctoring/` entry,
   contradicting the pattern this repo already follows for standing-policy and
   infra changes (e.g. `docs/doctoring/contextual-orchestrator-vendored-sidecar.md`,
   `docs/doctoring/noema-orchestrator-free-zdr.md`). This file is that record.
2. **Naming section (§5) contradicts existing binding conventions.** The
   verbatim directive text (a) uses "wardnet" as an example of an "old name"
   to rename away from, when `docs/CWL-MASTER-CONTEXT.md` §3/§10 records
   `waf-ids-ai-soc` → **wardnet** as an already-completed rename — wardnet is
   the current canonical name, not a legacy one; and (b) says all DB names
   violating the snake_case convention "shall be replaced entirely," which
   contradicts `docs/CWL-MASTER-CONTEXT.md` §7's explicit grandfather clause,
   "DB object names = 2+ word snake_case (don't rename existing Camel/Pascal)."
   Read literally and combined with this org's stated "full autonomy, do not
   ask the user" convention, an agent following §5's wording alone could
   force-rename the wardnet product or existing database objects and violate
   the canonical schema/naming contract that a completed rename already
   established.

   Resolved per `docs/product-goal-directive.md`'s own stated conflict
   policy ("Where this directive and those documents conflict, resolve the
   conflict and update whichever document is wrong — do not silently pick
   one"): added a reconciliation note directly after §5's quoted text (not
   inside the quote) stating that `docs/CWL-MASTER-CONTEXT.md` §7 governs,
   that the snake_case rule applies to **new** DB objects only, and that
   wardnet must not be treated as a rename target.

## Follow-up findings (CodeRabbit, PR #1429)

CodeRabbit's automated pass raised two further findings, both verified and
fixed:

3. **Markdown lint (MD040).** The `/goal` pointer example's fenced code block
   had no language identifier. Changed the opening fence to ` ```text ` since
   the block is a command example, not executable code.
4. **Section 8 read as CI routing policy.** Section 8's quoted text describes
   `contextual-orchestrator`'s general auto-discovery capability across all
   five provider secrets — a product-level design principle, not CI routing
   policy. Read in isolation, an agent could mistake it for license to loosen
   which pool `OpenCode`/`Noema`/`Strix` route through. Added a note (not
   inside the quote) stating that pool/credential-scope routing is governed
   exclusively by `docs/adr/0003-contextual-orchestrator-vendored-free-zdr.md`:
   `OpenCode`/`Noema` → fail-closed `orchestrator/free`; `Strix` →
   `orchestrator/auto`; private/internal targets require an attested
   ZDR-only catalog.

## Audit trail

- `docs/product-goal-directive.md` — the directive itself and the
  reconciliation note.
- `docs/CWL-MASTER-CONTEXT.md` §3, §7, §10 — the naming-history and DB-naming
  conventions this record reconciles against.
- ContextualWisdomLab/.github#1429 — the PR carrying this change and Devin
  Review's findings.

## 2026-09-01 revision: three sections gained new substantive content

- **Date:** 2026-09-01
- **Subject:** the owner re-issued the full nine-section directive verbatim via
  a `/loop` invocation in an active autonomous session. A word-for-word
  comparison against the stored text (saved to a scratch diff before editing,
  not committed) found sections 1, 2, 4, 5, 6, and 9 re-authored in
  substantially the same words — condensed phrasing, English terms swapped
  for Korean equivalents, no new obligation — so those sections were left
  untouched in `docs/product-goal-directive.md` to avoid rewriting stable
  wording for no substantive gain. Three sections contained genuinely new
  sentences, absent from every prior version of this file, and were added in
  place (inside the existing verbatim quote blocks, appended or inserted at
  the sentence they logically extend — not as a separate reconciliation note,
  since nothing here contradicts an existing binding convention):

  1. **§3 (research/documentation traceability)** gained an explicit
     decision-record standard: every decision must be written so that even
     the author having forgotten the context, or a reader seeing it for the
     first time, can reconstruct the problem, constraints, alternatives
     considered, why one was chosen and the others rejected, the supporting
     evidence, the risks, the expected effect, and the follow-up — with
     concrete, vivid scenarios (not bare conclusions or unstated premises),
     and links to the exact head SHA, logs, issues/PRs/ADRs, and experiment
     results so another agent can verify, revise, or continue the same
     judgment. This directly generalizes a discipline this session was
     already practicing informally (e.g. the RED→GREEN evidence, coverage
     numbers, and root-cause narratives recorded throughout
     `docs/product-technical-gap-baseline.md`'s 2026-08-30/31 and 2026-09-01
     entries) into an explicit, binding requirement for all future entries.
  2. **§7 (realistic verification / load / container testing)** gained a
     concrete, testable E2E acceptance criterion that did not exist before:
     p95 per-page processing time ≤ 20ms, checked across every page (not a
     sample), with any bottleneck removed and the page re-verified before it
     can be considered passing. No repository in this org's current scope
     (`.github`, `noema`, `contextual-orchestrator`, `naruon`) has this gate
     wired into CI yet — it is recorded here as a new, tracked requirement
     for whichever repo's web surface next needs an E2E load-test pass, not
     as a claim that it is already enforced anywhere.
  3. **§8 (LLM, orchestration, embedding)** gained two new principles, both
     absent from the 2026-08-30 text:
     - **Never hardcode an LLM provider *group* name.** Group/pool names
       (e.g. `orchestrator/free`, `orchestrator/auto`) are management/display
       aliases only; code, config, tests, and routing conditions must decide
       model selection, fallback, and feature availability from
       auto-discovered, verified model characteristics (modality, context
       window, reasoning capability/effort, tool calling, structured output,
       streaming, price/latency/availability/accuracy) so that a renamed or
       replaced provider/group never breaks a feature branch. This
       generalizes, and does not relax, the existing pool-routing note above
       (§8's first note, 2026-08-30): that note is about *which pool* each
       CI consumer is bound to (still governed by
       `docs/adr/0003-contextual-orchestrator-vendored-free-zdr.md`); this
       new sentence is about *how code decides behavior once bound to a
       pool* — never by matching the pool's string name.
     - **No uniform hardcoded LLM request timeout.** The application/agent/
       gateway layer must not impose a single timeout ceiling on LLM calls;
       the default is unlimited (`null`), since transport failures already
       terminate via the upstream provider's own timeout/error path (see
       `scripts/ci/noema_review_gate.py`'s unbounded design, reconciled
       against the now-superseded #1438 in the 2026-09-01 entries of
       `docs/product-technical-gap-baseline.md`, and the removed
       120-second/four-hour-window history in this same doctoring file's
       companion entries). Per-model timeouts become available only through
       an admin-facing web surface with full CRUD (query/set/clear/restore),
       units, priority, inheritance, input validation, and an audit trail as
       an explicit API contract; an admin-configured value is the *only*
       thing allowed to bound a call, and even then a bare elapsed-time
       cutoff must never cancel an in-progress reasoning/streaming/tool-call
       turn. Logs must distinguish user-initiated cancellation,
       provider-side termination, and admin-configured timeout as three
       distinct, separately recorded outcomes. No repository in this org's
       current scope has this admin timeout-management surface implemented
       yet — it is a new, tracked product gap (see
       `docs/product-technical-gap-baseline.md`'s 2026-09-01 entry), most
       naturally owned by `contextual-orchestrator`'s existing `/admin`
       console (`contextual_orchestrator/admin.py`) since that is where
       model/pool configuration already lives, not by any single CI
       consumer.
- **Decision record:** no `docs/adr/` entry yet for the admin-timeout-management
  surface (§8, second bullet above) — it is substantial enough to eventually
  need one once a repository begins implementing it; this doctoring entry and
  the gap-baseline entry are the interim record.
- **PR:** ContextualWisdomLab/.github (this change's own PR — see the PR
  description for the exact number).

## Audit trail (2026-09-01 revision)

- `docs/product-goal-directive.md` — §3, §7, §8, and the top-of-file revision
  note.
- `docs/product-technical-gap-baseline.md` — the 2026-09-01 entry tracking the
  two new, currently-unimplemented product gaps this revision introduced
  (E2E p95 20ms gate; admin per-model timeout management).
- `docs/adr/0003-contextual-orchestrator-vendored-free-zdr.md` — the still-
  governing pool-routing policy this revision's provider-group-name principle
  does not relax.

## 2026-09-01 follow-up: new §10 crystallizes the Strix pool pin

- **Date:** 2026-09-01 (same day, a second `/loop` invocation following the
  revision above)
- **Subject:** the owner added one new line — "orchestrator/free 로 고정"
  ("fix/pin to orchestrator/free") — as an explicit tenth numbered item,
  where §8 previously only carried this as an annotation below the verbatim
  quote (a CodeRabbit-flagged note describing `Strix` on the provider-diverse
  `orchestrator/auto` pool, followed by a second, superseding note recording
  that `.github/workflows/strix.yml` was later changed to hardcode
  `orchestrator/free` and fail closed on any other value). Verified this
  claim directly against the current `strix.yml` before writing the new
  section (not just trusting the prior note): both `STRIX_MODEL_REQUESTED`
  and `STRIX_MODEL`/`strix_llm` gating `case` statements accept only
  `orchestrator/free`/`contextual-orchestrator/orchestrator/free`, and
  `::error::` on anything else — confirming the pin is still in force at the
  time of this doctoring entry, not merely claimed by an older note that
  could itself have drifted.
- **What changed:** added `## 10. Contextual-orchestrator pool pin` to
  `docs/product-goal-directive.md`, quoting the new line verbatim, with a
  context paragraph (not inside the quote) explaining that this crystallizes
  an already-implemented decision rather than introducing a new one, and
  that it supersedes §8's first (CodeRabbit) note's "Strix →
  `orchestrator/auto`" framing specifically — that framing was already
  superseded by §8's second note; §10 now makes the current state
  discoverable without needing to read a superseded-vs-superseding note pair.
  Updated the "nine sections" → "ten sections" references in the file's
  intro and the `/goal` pointer text (which also gained the new section to
  its parenthetical list of the sections a `/goal` session must treat as
  applicable every cycle).
- **Decision record:** none new — this doesn't change the pool-routing
  policy itself, only where it is recorded; `docs/adr/0003-contextual-orchestrator-vendored-free-zdr.md`
  remains the ADR of record.
- **PR:** ContextualWisdomLab/.github (same PR as the 2026-09-01 revision
  above, or its immediate follow-up commit — see the PR description).

### Audit trail (this follow-up)

- `docs/product-goal-directive.md` §8 (both existing notes, read but not
  edited) and new §10.
- `.github/workflows/strix.yml` — the live source verified before writing
  §10, not merely cited from memory of the existing note.
