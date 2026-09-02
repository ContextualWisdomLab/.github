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

## 2026-09-01 second follow-up: §10 wording refined with an explicit scope qualifier

- **Date:** 2026-09-01 (same day, a third `/loop` invocation)
- **Subject:** the owner re-issued item 10 with an added qualifier:
  "Contextual-Orchestrator의 모델은 **GitHub Actions Workflow 이용에 관해**
  orchestrator/free 로 고정" ("...is fixed to orchestrator/free **with
  respect to GitHub Actions Workflow usage**"). The bare one-line version
  recorded in the prior follow-up above could be misread as pinning
  `contextual-orchestrator`'s pool choice for *every* caller, contradicting
  §8's own general-capability framing (broad model/modality support,
  five-secret auto-discovery as a product-level design principle for the
  orchestrator itself). The qualifier makes explicit what the live
  `strix.yml` evidence already implied: this pin governs the three
  required-check GitHub Actions Workflows (`OpenCode`, `Noema`, `Strix`),
  not the orchestrator's general product capability for other callers
  (e.g. a future non-CI consumer, or an end-user-facing integration).
- **What changed:** updated §10's verbatim quote to the fuller wording and
  expanded its context paragraph to state the CI-workflow-scoped reading
  explicitly, cross-referencing §8's own general-capability framing so the
  two sections read consistently rather than appearing to conflict.
- **Decision record:** none new — same as the prior §10 follow-up, this is
  a wording clarification of an already-implemented, already-recorded pin,
  not a policy change.
- **PR:** ContextualWisdomLab/.github (same PR as the two entries above).

## 2026-09-02 revision: five sections gained new substantive content

- **Date:** 2026-09-02
- **Subject:** the owner re-issued the full ten-section directive again, this time as a genuine
  chat-turn message (not a `/loop` invocation) titled "아래는 일반 지침" ("general guidance below").
  A section-by-section comparison against the stored text found §1, §3, §6, and §8 re-authored in
  visibly condensed form — same substance, shorter Korean, no new obligation — left untouched per
  the same policy as the 2026-09-01 revision. §2, §4, §5, §7, and §9 each contained genuinely new
  sentences absent from every prior version of this file, added in place (inside the existing
  verbatim quote blocks, or as a new quoted addition immediately following the existing block where
  the new material reads as a distinct addendum rather than an in-line insertion):

  1. **§2 (concurrent operation / root-cause fixes)** gained an explicit "immature core" protocol:
     when a needed core dependency is immature, the consumer must never duplicate, work around, or
     exclude it — instead develop the missing RED test, contract, feature, docs, and release *in the
     owner repo*, get it through that repo's own CI to GREEN, and only then connect the consumer to
     the resulting versioned release. Excluding a dependency is reserved for two cases only: the
     bounded context itself is wrong, or there is genuinely no shared need. This directly formalizes
     a discipline this session was already practicing (e.g. this same session's earlier passes fixing
     `contextual-orchestrator`'s discovery-retry gap at the owner rather than working around it in a
     consumer) into an explicit, binding rule — and it is the same principle §9 restates from the
     repository-selection angle ("공통 기능은 core owner로 추출해 통합 CI로 개발한다"), so the two
     additions cross-reference each other. Also gained one new reference tool:
     https://github.com/epoko77-ai/im-not-ai for Korean-language phrasing/documentation/translation
     polishing, explicitly scoped to preserve meaning, facts, figures, and proper nouns (not a
     free-form rewrite tool) — added alongside the existing ponytail/superpowers/code-review-graph/
     codegraph tool list already in this section, matching where the new text placed it.
  2. **§4 (UX/UI and customer-facing expression)** gained the largest single expansion in this
     revision: (a) an explicit UI-composition principle ("all UI is reusable objects, pages are
     compositions of them"); (b) a named list of Storybook states to isolate-develop and document
     (normal/loading/empty/error/permission/responsive/interaction) replacing the vaguer "scene- and
     edge-case-specific events" wording; (c) an explicit shadcn/ui-vs-Storybook clarification
     (shadcn/ui is a component *source*, not a Storybook substitute — the two are not in a
     replace-one-with-the-other relationship); (d) an explicit frontend-stack-flexibility principle
     (no fixed stack; React/Vite/shadcn/ui/jQuery 4 and others are acceptable when they meet
     security/maintainability/standards/accessibility/performance bars); (e) a specific Keyverse
     integration pattern not previously recorded anywhere in this file (Keyverse stays the
     authentication *backend* via Direct Grant/ROPC or the Keycloak REST API, but login/signup/
     account-recovery screens are the product's own forms, not a Keyverse-hosted redirect page); and
     (f) a genuinely new, concrete i18n architecture mandate: eight named languages (한국어·영어·
     일본어·중국어·베트남어·스페인어·독일어·프랑스어 — ko/en/ja/zh/vi/es/de/fr), per-language
     Storybook/E2E testing for width/wrap/CJK/text-expansion/font-fallback/locale-format issues
     (truncation, overlap, meaning-loss — not a single default-locale screenshot pass), and — the
     load-bearing part — **the translation ledger must be a versioned DB resource, never static
     files or a JS bundle**: server/native code fetches only the current screen's keys with caching,
     the browser is never handed the whole catalog or heavy i18n JavaScript, and no SPA architecture
     may be assumed. If no shared translation-management product exists yet, a new repository must be
     stood up to provide per-product translation review/approval/deploy/rollback API plus an admin
     UI. This i18n architecture requirement is recorded as a new, currently-unimplemented,
     concrete product gap — this session did **not** audit naruon's (or any other product's) current
     i18n implementation against it in this pass; that audit is deliberately deferred to a future Gap
     increment (see `docs/product-technical-gap-baseline.md`'s 2026-09-02 entry), consistent with
     this directive's own "one Gap increment at a time" philosophy rather than trying to verify every
     product's compliance in the same pass that records the requirement.
  3. **§5 (architecture, naming, and database conventions)** gained a concrete repo-responsibility
     split for the org's ontology pipeline, added as a quoted addendum after the existing
     Devin-Review naming reconciliation (not merged into the original 2026-08-30 quote block, since
     it reads as new material rather than a correction to it): ConceptWeave owns the
     observe→discover→propose→align→validate→review→publish pipeline and semantic release;
     semantic-data-portal owns catalog/governance/consumption; context-graph-contracts owns
     interop contracts; enterprise-architecture-core owns the Context Map and cross-cutting
     decisions — domain truth and Ubiquitous Language themselves stay with the product owner, not
     any of these four. Also new: an immutable-release data contract for ontology concepts
     (evidence/provenance/validity/confidence/status/deprecation/locale label required on every
     released concept/relation/dimension/measure/mapping); a consumer-boundary prohibition
     (consumers use only released API/contract/ACL — no file copies, no cross-service SQL, no
     unapproved publication); and an explicit rule that the UI translation ledger (§4, above) and the
     ontology label ledger (this section) must never share a store — two distinct versioned
     resources with two different owners. Cross-checked `semantic-data-portal`'s description here
     against its existing entry in `docs/CWL-MASTER-CONTEXT.md` (the higher ontology/catalog/
     governance plane above naruon's doc KG; SDP is not that store) — consistent, this addition just
     names the upstream pipeline stages and the two cross-cutting-decision repos that file does not
     yet name explicitly (see the §9 reconciliation note below for the same verification gap).
  4. **§7 (realistic verification, load, and container testing)** gained two anti-gaming clauses for
     the p95≤20ms criterion the 2026-09-01 revision introduced: never satisfy it by shrinking the
     sample, excluding measurements, or an unrealistic cache warm-up; and when the JS
     bundle/heap/DOM/hydration/main-thread/GC is the actual memory or latency driver, the fix is to
     replace the dependency or frontend stack rather than accept the slower ceiling. Both close off
     the two most tempting ways to make the existing gate pass without fixing anything real, and
     reinforce (not change) the section's existing profile-first-then-Rust-if-proven-necessary
     approach.
  5. **§9 (reference libraries, ecosystem repositories)** roughly tripled in size and gained explicit
     per-repo responsibility statements for most entries for the first time. New repos named:
     `.github`, `enterprise-architecture-core`, `context-graph-contracts`, `ConceptWeave`,
     `semantic-data-portal`, `noema`, `EgressWeave`, `OriginWeave`, `pingora-gateway`,
     `quarantine-sandbox-runtime`, `pg-llm-batch`, `EmbedRelay`, `inkspan`, `DiagramWeave`,
     `mhtml-etl-gateway`, `appguardrail`, plus an explicit "domain product/composition consumer, not
     core" classification for `naruon`, `LineageWeave`, `psychometrics-commons`, `disksage`,
     `PolicyWeave`, `CalendarWeave`, and `supply-chain-control-plane`. Cross-checked against
     `docs/CWL-MASTER-CONTEXT.md`: `semantic-data-portal`, `pg-llm-batch`, `appguardrail`, `inkspan`,
     `wardnet`, `keyverse`, `naruon`, `TEPP`, `fast-mlsirm`, `RankWeave`, `ThreadWeave`, `disksage`,
     `LineageWeave`, `contextual-orchestrator`, and `noema` already appear there and this section's
     descriptions are additive, not contradictory. `ConceptWeave`, `context-graph-contracts`,
     `enterprise-architecture-core`, `EgressWeave`, `OriginWeave`, `pingora-gateway`,
     `quarantine-sandbox-runtime`, `EmbedRelay`, `DiagramWeave`, `mhtml-etl-gateway`,
     `psychometrics-commons`, `PolicyWeave`, `CalendarWeave`, and `supply-chain-control-plane` could
     **not** be cross-checked: `CWL-MASTER-CONTEXT.md` does not yet name them, and this session's
     repository access (`.github`, `noema`, `contextual-orchestrator`, `naruon`) does not extend to
     them. Recorded verbatim anyway, per this file's own conflict/durability policy, with a tracked
     follow-up gap to add them to `CWL-MASTER-CONTEXT.md`'s catalog once an agent with access (or the
     owner) can confirm the responsibility split against their actual current state.

  Also updated §8 with a short note (not a change to the verbatim quote) observing that this
  revision's §8 restatement again mentions "`orchestrator/free` 고정" but as a bare clause inside
  §8's body rather than the separately scope-qualified §10 item, and that this compression does not
  reopen or loosen §10's already-evidence-verified "GitHub Actions Workflow 이용에 관해" scope
  qualifier — a shorter restatement omitting detail recorded elsewhere in the same document is not a
  reversal of that detail.
- **Decision record:** none yet in `docs/adr/` for the i18n-DB-versioned-resource architecture or the
  ontology-pipeline repo split — both are substantial enough to eventually warrant one once a
  repository begins implementing against them; this doctoring entry and the gap-baseline entry are
  the interim record, consistent with how the 2026-09-01 admin-timeout-management gap was handled.
- **PR:** ContextualWisdomLab/.github (same branch/PR as the 2026-09-01 revisions above —
  `docs/update-product-goal-directive-2026-09-01` — continued rather than forked into a new PR, since
  this is the same ongoing "keep the directive doc current" effort).

### Audit trail (2026-09-02 revision)

- `docs/product-goal-directive.md` — §2, §4, §5, §7, §9 (new content), §8 (new note), and the
  top-of-file revision summary.
- `docs/CWL-MASTER-CONTEXT.md` — cross-checked for every repo name in the new §5/§9 content; the
  entries it does and does not already carry are both recorded above.
- `docs/product-technical-gap-baseline.md` — the 2026-09-02 entry tracking the two new,
  currently-unimplemented product gaps this revision introduces (the i18n DB-versioned-resource
  translation-ledger architecture; the ontology-pipeline repo-responsibility split awaiting an
  `enterprise-architecture-core`/`context-graph-contracts`/`ConceptWeave` cross-check), plus the
  tracked follow-up to add the not-yet-cross-checked §9 repo names to `CWL-MASTER-CONTEXT.md`.

## 2026-09-02 Devin Review reconciliation: one real internal contradiction, one real misplaced quote

- **Date:** 2026-09-02
- **Subject:** Devin Review's automated review of this PR (`#1659`) flagged 5 findings against the
  2026-09-02 revision above. Two were `BUG`-severity and, verified directly against the file before
  acting (not taken at face value, per this session's standing verification discipline), both turned
  out to be real defects introduced by that revision's own edits:
  1. **§7's newly-added container-requirements sentences (Docker/Podman/Colima substitution,
     `shm_size`/PostgreSQL auto-tuning, compose-first k8s portability, fixed-then-overridable
     container project naming, MLX/CPU/CUDA/OpenCL ADR requirement) had been appended after the
     English "Addition (2026-09-02)" commentary paragraph instead of inside the `>` blockquote
     above it.** Confirmed by direct inspection: the quoted §7 block ends at "...점검한다." and the
     Korean container sentences sat at the tail of the English commentary that follows, with no `>`
     prefix. Since this file's own "How to point a `/goal` session at this directive" section frames
     the ten sections as extractable quoted blocks, any consumer pulling just the `>`-quoted text
     would silently miss binding directive content. **Fix:** moved the Korean sentences verbatim into
     the end of the §7 blockquote itself (no paraphrasing, no wording change), leaving the English
     commentary paragraph containing only the anti-gaming-clause explanation it was originally written
     for, with a short note recording the move and crediting Devin Review's finding.
  2. **§8's "LLM Provider group 이름을... 하드코딩하지 않는다" and §10's "orchestrator/free 로 고정"
     read as a direct contradiction in isolation** — Devin's own framing, "agents cannot satisfy both,"
     is accurate as far as it goes. Verified this was a genuine gap: the existing §8/§10 notes already
     explained the *scope* (CI-consumer workflows vs. general product capability) but never explicitly
     reconciled §8's literal "하드코딩하지 않는다" against §10's own admitted hardcoding of a group-name
     string in `strix.yml`'s `CONTEXTUAL_ORCHESTRATOR_POOL`. **Fix:** added a new note distinguishing
     §8's actual target — **behavioral feature branching** in application/Agent/gateway code (never
     select a model or change capability handling by string-matching a provider group name; drive
     behavior from auto-discovered model characteristics instead) — from §10's **CI admission-pool
     selection**, which changes no application code path or feature at all; it only tells a
     security-critical required-check workflow which cost/ZDR-governed pool it may draw candidates
     from, with every model inside that pool still chosen by the same auto-discovery §8 requires. No
     directive quote was weakened or reopened by this reconciliation — both `>` blocks are unchanged.
- **Not acted on:** Devin's other three findings were re-statements of gaps this same PR already
  records — "focused test remains unverified" (no pytest in Devin's own review sandbox; this session's
  actual `PYTHONPATH=. python3 -m pytest tests/test_product_technical_gap_baseline.py -q` run, `5
  passed`, is the real evidence, and no test in this repo pins `product-goal-directive.md`'s prose —
  confirmed via `grep -rln "product-goal-directive" tests/`, no matches), "master context remains
  unsynchronized" (already Gap 5 in the gap-baseline), and "unverified roles become binding policy"
  (already Gap 4). All three are accurate observations of already-tracked, already-labeled gaps, not
  new defects — no further action needed on them beyond what's already recorded.
- **Verification:** `PYTHONPATH=. python3 -m pytest tests/test_product_technical_gap_baseline.py -q`
  → 5 passed (this file's only executable contract, unaffected by directive-text edits); confirmed via
  `grep` that no test pins `product-goal-directive.md`'s literal prose.
- **PR:** `ContextualWisdomLab/.github#1659`.

## 2026-09-02 third revision (second same-day chat message): eight sections gained new substantive content

- **Date:** 2026-09-02.
- **Subject:** the owner re-issued the full directive a third time overall — a second genuine
  chat-turn message this same day, again titled "아래는 일반 지침." A section-by-section comparison
  against the then-current stored text (post the two prior 2026-09-02 reconciliations already recorded
  above) found §3 and §4 re-authored in condensed form with the same substance and no new obligation
  detected — left as-is, same policy as every prior revision. Every other section (§1, §2, §5, §6, §7,
  §8, §9, and §10's existing pin) gained genuinely new content, added in place inside the existing
  verbatim quote blocks or as new dated blockquote additions immediately following them, each with an
  explanatory English note in the same style as prior revisions:
  1. **§1** gained one new sentence closing a loophole in "reach 0 open PRs": doing so is legitimate
     only via merge or a verified successor's full delta takeover, never a bare Close. This directly
     sets up §2's much larger addition below.
  2. **§2** gained a detailed six-category PR close/repair taxonomy — single-writer/DDD violations,
     wrong base/merge conflicts, colliding ADR numbers, prematurely-Accepted reviews, unprotected
     dependencies, and missing test/fixture/contract are all **repair findings, never close reasons**.
     The repair path: downgrade to Draft/Proposed, non-force restack/retarget onto the owner's stack
     (never force-push). Single-writer resolution is explicitly framed as **delta integration, not
     discarding**: an unfixable PR needs a successor that fully inherits its delta and continues the
     work; a PR blocked on an unlanded foundation stays open while the prerequisite gets completed; a
     wrongful close gets recovered via reopen or successor. Close itself narrows to exactly four
     legitimate cases (explicit user instruction, no valid delta, a malicious change, or a verified
     successor's full takeover) — a "closed" label by itself is not closure without one of those four
     behind it.
  3. **§5** widened the existing two-or-more-word DB-object naming rule to cover essentially every
     named code entity (variables through directories), still snake_case-preferred, and added an
     explicit boundary-conversion rule (external language/framework/contract naming conventions get
     converted at an adapter/ACL boundary, not propagated inward — the same Anti-Corruption-Layer
     principle this section already states generally, now applied specifically to naming). The
     existing wardnet/grandfather-clause reconciliation from 2026-08-30 is explicitly noted as not
     reopened: it stays scoped to existing CamelCase/PascalCase **DB objects** specifically.
  4. **§6** sharpened the existing Rust-first mandate into an explicit "Python is disfavored, never
     chosen for LLM/agent convenience" rule with one narrow, ADR-tracked exception (a Python-only ML
     runtime with no practical Rust alternative, scope/rationale/removal-condition recorded, hot path
     still Rust), plus naming Rust as an explicit alternative to a Python-3.14 upgrade for GIL
     bottlenecks.
  5. **§7** added "rendering" to the list of things to replace when the JS bundle/DOM/GC is the
     memory/latency driver (previously "dependency·Frontend stack," now "dependency·rendering·Frontend
     stack").
  6. **§8** gained two things: a "connect via released API/client/schema" consumption pattern for
     `contextual-orchestrator` integration (the same "immature core" principle §2 and §9 already state,
     now stated a third time as the specific CO consumption contract — verified not to contradict the
     adjacent "가능하면 반입해 쓰고... 수정한다" sentence, which is about CO importing *its own* upstream
     dependencies, a different relationship); and a detailed CI integration architecture (`.github`
     reusable-workflow-plus-thin-caller composition; exact-SHA verification across build/API-schema-
     contract/E2E/model-behavior/security/SBOM/provenance; owner-side RED→fix→GREEN→release with a
     consumer version bump on defects; a ban on mutable-head/branch-URL/cross-repo-source/workflow
     duplication; an owner-issue-plus-expiration condition on any transitional bridge) — recorded as
     the standard, explicitly not asserted as already-verified everywhere (see Gap 7 below).
  7. **§9** gained three things: a definitional framing of what "core foundation" actually means (a
     selective, canonically-owned, versioned-contract-providing control plane — never a default
     install; role/maturity confirmed from the *protected branch's* evidence, not an open PR's own
     claims — directly matching this session's own established practice of treating "Current exact
     authority" PR-body language as a claim to verify, not a fact); a five-domain regrouping of the
     existing flat repo catalog (조직·계약 / 의미·데이터 / AI·운영 / Identity·보안·runtime / 재사용
     기능); and a concrete elaboration of the "immature core" protocol's waiting-period mechanics
     (a port/ACL/feature-flag/test-double boundary while waiting on an immature owner; an explicit
     prohibition on reading the owner's raw source/DB/temp branch directly, not previously stated).
  8. **§10** gained three specific architectural constraints on its existing `orchestrator/free` pin,
     each **verified against current source before being recorded**, not merely restated: free-pool
     discovery/routing/fallback stays inside CO (confirmed — the sidecar provisions an in-process CO
     instance; Strix talks to it only via a locally generated bearer token); the workflow itself has no
     live path to specify a provider/model/group and never sees a raw provider credential (confirmed —
     `strix.yml`'s `Gate Strix secrets` step hardcodes the model and rejects any override that isn't
     the same value); missing capability fails closed with no paid bypass (confirmed — the sidecar's
     `CONTEXTUAL_ORCHESTRATOR_POOL` validation is exactly this session's own earlier `auto`-removal
     fix). Like the original §10 addition, this is the existing implementation made explicit, not a
     new technical requirement.
- **Two new gaps recorded, not fabricated:** `docs/product-technical-gap-baseline.md`'s new 2026-09-02
  entry tracks two audit gaps this revision's new content surfaces but this reconciliation pass did not
  fully verify — Gap 6 (`contextual-orchestrator`'s stdlib-Python core against the newly sharpened §6
  Python rule; partial evidence found — `library_research.md` already exists and the one genuinely
  numeric hot path, LLM token accounting, already uses Rust via PyO3+`tiktoken-rs` — but full compliance
  against the new bar, and even whether the control-plane logic itself is in scope of the Rust mandate
  at all, is unverified) and Gap 7 (§8's CI integration architecture, plausibly already substantially
  met per this repo's own documented conventions, but not audited against every current owner/consumer
  relationship in this pass).
- **Verification:** `PYTHONPATH=. python3 -m pytest tests/test_product_technical_gap_baseline.py -q`
  → 5 passed; `grep -rln "product-goal-directive" tests/` → no matches (still no test pins this file's
  prose); `grep -n "�" docs/product-goal-directive.md` → no matches (no corruption introduced). §10's
  three new architectural-constraint claims were verified directly against
  `.github/workflows/strix.yml` (the `Gate Strix secrets` step's hardcoded `STRIX_MODEL` and its
  override-rejecting `case` statement) and `scripts/ci/contextual_orchestrator_review_sidecar.sh` (the
  locally generated `ORCHESTRATOR_TOKEN`/bearer-token pattern and the `CONTEXTUAL_ORCHESTRATOR_POOL`
  fail-closed validation) before being written, not merely asserted on the strength of the new
  directive text.
- **PR:** `ContextualWisdomLab/.github#1659`.

## 2026-09-02 Devin Review, round 2: one real §1/§2 self-contradiction, two acknowledged-not-actioned observations

- **Date:** 2026-09-02.
- **Subject:** a second Devin Review pass on this PR (after the third revision's commit `b3f96812`)
  found 3 new items. One `BUG`-severity finding was real and fixed; two `ANALYSIS`-severity
  observations are valid but deliberately not actioned in this pass, with reasoning recorded here.
  1. **"Last valid close cannot reach zero" (real, fixed).** §1's new "PR 0개는 병합이나 검증된
     successor의 유효 delta 완전 승계로만 만들고 단순 Close하지 않는다" and §2's four-case close policy
     (explicit user instruction / no valid delta / malicious change / verified successor takeover)
     conflict for exactly the case where the *last* open PR is legitimately closed under one of §2's
     other three cases — §1's shorthand names only "merge or successor takeover" as legitimate paths
     to zero, which taken literally would forbid ever reaching zero via a no-valid-delta, malicious, or
     user-directed close, directly contradicting §2's own policy one paragraph earlier. **Fix:** added
     a reconciliation note (not an edit to either verbatim quote) explaining the correct reading — §1's
     constraint targets specifically the disposition of a PR *with a valid, unmerged delta* (merge and
     successor-takeover are the two ways named because both preserve that delta, which a bare Close
     would silently lose); the other three legitimate close cases don't have that problem (no delta to
     lose, nothing worth preserving, or a supervening user instruction), so reaching zero through any
     of §2's four legitimate paths is consistent with, not a violation of, §1's actual intent.
  2. **"Obsolete routing guidance remains prominent" (acknowledged, not actioned).** The first
     (CodeRabbit, 2026-08-30) note under §8 still describes the superseded "Strix uses
     `orchestrator/auto`" framing prominently, even though two later notes in the same section already
     mark it superseded and explain why. Devin's suggestion (move the historical guidance to the
     doctoring record) is reasonable in isolation, but this file's own established convention — visible
     across every prior revision reconciled here — is to leave a superseded note in place with a clear
     "superseded by X" marker rather than relocate or delete it, so the in-place reasoning trail (why
     the old framing existed, what changed, when) survives for a reader working through the section
     top-to-bottom. Moving it to `docs/doctoring/` would break that in-place trail for a reader of
     `product-goal-directive.md` itself, who would then need to cross-reference a second file mid-
     section. Left as-is; noted here as a considered, not overlooked, decision.
  3. **"Revision history obscures current policy" (acknowledged, not actioned).** A broader structural
     observation: current rules now appear in three places (the top preamble's revision-history
     paragraphs, in-section commentary notes, and this doctoring file), and a future edit to one could
     leave the others stale. Valid, and a natural consequence of three same-day revision passes each
     appending its own preamble paragraph and section notes rather than restructuring the file. A full
     consolidation (e.g., collapsing the preamble to point at a single canonical changelog rather than
     narrating each revision inline) is a legitimate improvement but a materially larger, separate
     effort than a review-response fix — restructuring this file's organization is not something to
     do reactively inside an unrelated PR round. Not actioned here; worth a dedicated future pass if
     the preamble keeps growing at this rate.
- **Verification:** `PYTHONPATH=. python3 -m pytest tests/test_product_technical_gap_baseline.py -q`
  → 5 passed; `grep -n "�"` → no matches (no corruption).
- **PR:** `ContextualWisdomLab/.github#1659`.

## 2026-09-02 fourth restatement: verified duplicate, no edit made

- **Date:** 2026-09-02.
- **Subject:** the owner sent the full nine-section directive a fourth time this session, as another
  genuine chat-turn message with the same "1. 실행 목표와 지속 Loop..." structure as the prior same-day
  restatement (the "third revision," commit `b3f96812`, reconciled earlier in this same session).
- **Method:** rather than assume duplication, did a section-by-section comparison against the then-current
  stored text (grep for distinguishing phrases per section, then full manual read-through of every
  section). Findings:
  - §1, §2, §3, §5, §6, §7: every sentence already present verbatim or in already-reconciled substance.
  - §9: the five-domain repo regrouping block and the "immature core" waiting-period sentence both
    matched the stored text **character-for-character** — strong evidence this is a genuine repeat send,
    not independently re-authored paraphrase.
  - §4 and §8 each contained one or two surface reword candidates worth individually checking rather
    than waved through: §4's "shadcn/ui는 제품 소유 component source, Storybook은 검증 환경이다"
    (explicitly labels shadcn/ui "product-owned" and Storybook "the verification environment") versus
    the stored "shadcn/ui는 component source로 Storybook과 대체 관계가 아니다" (component source, not a
    Storybook substitute); §4's "측정 성능" (measured performance) versus stored bare "성능"; §8's "LLM
    작업은... CO Agent로 만든다" (LLM work generally) versus stored "LLM이 필요한 테스트는... OpenCode
    Agent로 만든다" (tests needing LLM specifically). None of the three appear as literal text in the
    stored file (confirmed by `grep -n "측정 성능\|제품 소유\|검증 환경\|LLM 작업은"` — no matches), but
    each is a positive restatement/labeling of a relationship or scope already thoroughly established by
    surrounding already-stored sentences (Storybook's role as the state-documentation/audit environment
    is already spelled out in detail two sentences earlier in the same blockquote; §8's own later
    test-time-compute/Fugu-Conductor-TRINITY content already applies to "LLM 사용 소프트웨어" broadly, not
    a narrower "tests" scope) — judged non-substantive paraphrase, not a new obligation, consistent with
    this file's established policy for condensed re-authored sections.
- **Action:** none. No edit to `docs/product-goal-directive.md`'s quoted sections or notes. This entry
  exists so a future pass that receives what looks like the same restatement again can check this record
  first rather than re-deriving the same section-by-section comparison from scratch.
- **Not a `/loop` invocation:** unlike some earlier restatements in this session, this one arrived as a
  plain chat-turn message with no `/loop` prefix or scheduling instruction — handled identically to a
  `/loop`-delivered restatement per this file's own directive-reconciliation convention, which does not
  distinguish delivery mechanism.

## 2026-09-02 Devin Review, round 3: two real findings (whitespace, §10 owner-authorization gap), one real precision correction to this session's own prior verification note

- **Date:** 2026-09-02.
- **Subject:** a third Devin Review pass on this PR (after commit `77f16947`, the second merge from
  `main`) found 3 new items — 1 `ANALYSIS`-severity, 2 `BUG`-severity — all verified against source
  before acting, and all three real.
  1. **"Whitespace validation fails" (real, fixed).** `git diff --check origin/main` flagged trailing
     whitespace on `docs/product-goal-directive.md:161` (inside this session's own §1/§2 reconciliation
     note from the round-2 fix) and `docs/product-technical-gap-baseline.md:2684` (inside an
     already-merged `main`-side paragraph that this PR's diff still carries against its older base).
     **Fix:** stripped trailing whitespace from both exact lines with a scoped `sed`, re-verified
     `git diff --check` clean on all three touched files.
  2. **"Owner authorization remains contradictory" (real, fixed).** `AGENTS.md` and ADR-0003's
     2026-08-31 correction both still say the *original 2026-08-30 implementation* (the commit that
     hardcoded `strix.yml` to `orchestrator/free`) was an unreviewed, non-owner-authorized agent action,
     and that the resulting availability risk is still open/unreviewed with reversion to
     `orchestrator/auto` explicitly "not foreclosed." Read next to §10 — which presents
     `orchestrator/free` pinning as owner-directed — that reads as a flat contradiction without further
     context. **Fix:** added a reconciliation note distinguishing two separate facts that don't conflict
     once kept apart: the 2026-08-30 *implementation* event (unauthorized, unchanged by this item) versus
     §10 itself, which *is* a separate, later, genuine owner directive (issued via `/loop` on
     2026-09-01) authorizing the CI-workflow *policy* going forward — but that policy authorization is
     not the same as, and does not retroactively supply, the specific documented risk-acceptance
     ADR-0003 says is still missing. Both records stay true simultaneously: the pin is owner-authorized
     as CI policy, and the specific availability risk it carries remains open and unreviewed.
  3. **"Workflow-only token claim is false" (real precision correction to this session's own prior
     verification note, not the user's verbatim directive text).** This session's own round-2 doctoring
     entry ("Devin Review round 2") verified §10's Addition item (2) — "workflow는 provider·model·
     group명·유료 fallback을 지정하지 않고 gateway token만 쓴다" — by pointing at `strix.yml`'s hardcoded
     `STRIX_MODEL` and its `case`-statement override rejection, and summarized this as "the workflow has
     no live path to specify a different provider, model, or group." That summary sentence overstated
     it: `strix.yml:732-749`'s `Prepare Strix model input file` step does write the literal string
     `orchestrator/free` into `STRIX_LLM_FILE` and pass that file to Strix alongside the gateway token —
     a group/model identifier genuinely is communicated, just always the one hardcoded constant, never a
     live choice. **Fix:** corrected the verification note's own wording to say the workflow has no live
     path to *choose* a different provider/model/group/paid-fallback, rather than implying no
     model/group identifier is ever communicated at all. Note this is a fix to **this session's own
     added commentary**, not to the user's verbatim `>` blockquote text (§10's own quoted lines were
     never touched).
- **Verification:** `git diff --check origin/main -- docs/product-goal-directive.md
  docs/product-technical-gap-baseline.md` → exit 0 (clean); `grep -n "�" docs/product-goal-directive.md`
  → no matches; `PYTHONPATH=. python3 -m pytest tests/test_product_technical_gap_baseline.py -q` → 5
  passed.
- **PR:** `ContextualWisdomLab/.github#1659`.

## 2026-09-02 Devin Review, round 4: escalated re-review of round 3's own §10 fix, one real gap tightened

- **Date:** 2026-09-02.
- **Subject:** Devin re-reviewed round 3's §10 owner-authorization reconciliation note (commit
  `537c3872`) and escalated it to 🔴 (highest severity in this session's experience with this
  reviewer): "Authorized routing can be reverted" — the note, as written, quoted ADR-0003's "reverting
  to `orchestrator/auto`... is not foreclosed" sentence and said that framing was "unchanged by this
  item," which — read in isolation from the sentence right after it — could be misread as current,
  standing license for an agent to revert the owner's own binding §10 CI pin on its own initiative.
- **Assessment:** the note's own very next sentence already said reversion would require "§10 would
  need updating to match, not the other way around," so the substantive guardrail was present — but the
  finding is right that the paragraph's internal ordering let the "not foreclosed" quote read as the
  operative instruction if a reader stopped there, exactly the kind of ambiguity that produced the
  original 2026-08-30 incident this whole note exists to prevent a repeat of. Real clarity gap, fixed.
- **Fix:** rewrote the paragraph to lead with an explicit, unambiguous prohibition — "No agent may treat
  ADR-0003's... sentence as standing authorization to revert the CI pin today" — and to explain *why*:
  that ADR-0003 sentence describes the risk-acceptance question's unreviewed status as of 2026-08-31,
  written *before* §10 existed; §10 is the later, explicit, binding instruction; the only legitimate
  path to `orchestrator/auto` is a **new owner decision updating §10 itself**, never an agent's own
  reading of "not foreclosed" in isolation. Closes with the same "both records true at once" framing as
  round 3, now preceded by the explicit guardrail rather than following the ambiguous quote unguarded.
- **Verification:** `git diff --check origin/main -- docs/product-goal-directive.md` → exit 0;
  `grep -n "�" docs/product-goal-directive.md` → no matches;
  `PYTHONPATH=. python3 -m pytest tests/test_product_technical_gap_baseline.py -q` → 5 passed.
- **PR:** `ContextualWisdomLab/.github#1659`.

## 2026-09-02 Devin Review, round 5: one real ID-collision bug fixed, one real clarity gap tightened, one analysis finding verified false and not acted on

- **Date:** 2026-09-02, after this PR's second merge from `main` (commit `c16d712c`, pulling in the
  `#1672` Noema single-request work and 10 other commits).
- **Subject:** a fifth Devin Review pass found 3 new items: 1 `BUG` (`based_on_repo_rules: true`),
  2 `ANALYSIS`. All three checked against live source before acting, per this session's standing
  verify-before-acting discipline.
- **Finding 1 (BUG, real, fixed) — "New gaps have colliding identifiers."** `docs/product-technical-gap-baseline.md`
  had accumulated seven narrative product-gap entries across this PR's own commits, labeled "Gap 1"
  through "Gap 7" — a distinct, informal numbering scheme that collides on sight with this same file's
  canonical `## 3. Gap register` table, which already uses `G-01` through `G-16` as the one ID space
  every PR is instructed to cite (`"이 문서의 Gap ID를 연결한다"`, line 2523/2534). Confirmed via
  `git diff origin/main...HEAD` that all seven "Gap N" labels were introduced by this branch's own
  commits (none exist on `main`), so this was this PR's own defect to fix, not a pre-existing one to
  merely flag. **Fix:** renamed all seven in place to continue the canonical sequence — `Gap 1`→`G-17`
  (E2E load-test gate), `Gap 2`→`G-18` (admin per-model LLM timeout), `Gap 3`→`G-19` (i18n ledger),
  `Gap 4`→`G-20` (ontology-pipeline split), `Gap 5`→`G-21` (master-context catalog gap), `Gap 6`→`G-22`
  (contextual-orchestrator Python-vs-Rust audit), `Gap 7`→`G-23` (§8 CI-architecture audit) — updated
  every cross-reference (the "Gap 3, above" and "Gap 4 and Gap 5 are the same..." sentences), and added
  one compact row per new ID to the `## 3. Gap register` table itself (pointing to the fuller narrative
  entries below for detail), so the register — the thing PRs are actually told to cite — is complete
  rather than seven items existing only in prose with no register row.
- **Finding 2 (ANALYSIS, verified false as stated, but a real underlying clarity gap fixed) —
  "Revision count is stale."** Anchored on the status line's "revised 2026-09-01, 2026-09-02 (twice,
  same day)." Checked this against every dated heading in this file: `2026-09-01 revision` (substantive,
  3 sections), `2026-09-02 revision` (substantive, 5 sections), `2026-09-02 third revision` (substantive,
  8 sections — labeled "third" because it is the third substantive revision *overall*, counting
  2026-08-30's original as the baseline), and `2026-09-02 fourth restatement` (verified, in its own
  entry above with a full section-by-section comparison, to be a **non-substantive duplicate** — no
  edit was made to `product-goal-directive.md` for it). Arithmetic: 1 (09-01) + 2 (09-02) = 3
  substantive revisions total, which is exactly what "revised 2026-09-01, 2026-09-02 (twice, same day)"
  already states — so the specific claim "the history documents a third substantive revision" not
  reflected in the status line is **false**; the third one (the "third revision" heading) *is* one of
  the two 09-02 occurrences the status line already counts. Not acted on as stated. However, the
  underlying confusion is real and worth preventing: a heading reading "third revision (second same-day
  chat message)" sitting next to a status line reading "twice, same day" invites exactly this
  misreading (is "third" a same-day count or an overall count?) for the next reviewer, human or bot.
  **Fix (clarity, not correction):** reworded the status line to spell out the count explicitly ("plus
  three substantive revisions since — 2026-09-01 (one), 2026-09-02 (two, same day; the second of these
  is labeled 'third revision' in the doctoring file because it is the third substantive revision
  overall, not a third same-day one)") and to state plainly that the fourth same-day restatement was
  compared and found non-substantive, so a future reader (or reviewer) never has to redo this exact
  arithmetic check.
- **Finding 3 (ANALYSIS, real, fixed) — "Load target lacks a timing boundary."** The new `G-17` entry's
  "every page's p95 end-to-end processing time must be ≤ 20ms" never stated what interval that spans.
  Confirmed the ambiguity is real and consequential: a server request-received-to-response-sent
  measurement, a browser navigation-start-to-load-event measurement, and an interaction-to-next-paint
  measurement are all plausible readings of "processing time" and would yield materially different
  numbers for the same page — and k6's own default HTTP-duration metric only covers the first of the
  three, silently excluding client-side render/hydration cost if that boundary were assumed without
  being stated. This ambiguity lives in this file's own explanatory prose (not the directive's verbatim
  quote elsewhere, which this file's governance clause forbids rewording), so it was this session's own
  gap to fix. **Fix:** added a sentence to `G-17` naming the three candidate boundaries, noting k6's
  default metric only covers the transport leg, and instructing that a future implementing k6 suite
  must pick and document one explicit boundary (pairing k6 with a browser-timing tool if client-side
  work is in scope) so "meets the gate" has one fixed meaning across every page and re-verification.
- **Verification:** `git diff --check origin/main -- docs/product-goal-directive.md
  docs/product-technical-gap-baseline.md` → exit 0; `grep -n "�" docs/product-goal-directive.md
  docs/product-technical-gap-baseline.md` → no matches; `grep -n "Gap [0-9]"
  docs/product-technical-gap-baseline.md` → no matches (confirms no collision-prone label survives);
  `PYTHONPATH=. python3 -m pytest tests/test_product_technical_gap_baseline.py -q` → 5 passed.
- **PR:** `ContextualWisdomLab/.github#1659`.

## 2026-09-02 Devin Review, round 6: one real cross-repo-reference-format bug fixed, one real untracked security gap recorded (not fixed by rewording the owner's verbatim text)

- **Date:** 2026-09-02.
- **Subject:** a sixth Devin Review pass found 2 new items: 1 `ANALYSIS` (repository-reference format),
  1 `SEC` (security). Both checked against live source and the org's own binding convention before
  acting.
- **Finding 1 (ANALYSIS, partially real) — "Repository references lack full ownership."** Anchored on
  `docs/product-technical-gap-baseline.md`'s new `.github#1659` reference. Checked
  `docs/CWL-MASTER-CONTEXT.md` §7's actual rule: "Cross-repo references must be `owner/repo#num`... **Same-repo may use `#num`**." `.github#1659` is a same-repo reference (this file lives in `.github`), so
  it already satisfies the rule as written — Devin's framing that *all* references need the owner
  prefix is not what the convention says. **However**, checking the same diff for genuine cross-repo
  references surfaced a real instance the finding's title correctly describes even if its example
  didn't: two newly-added bare `naruon#1486` references (this file lives in `.github`, so a reference to
  a `naruon` PR *is* cross-repo and needs the full form) — confirmed via
  `git diff origin/main...HEAD` that both are new to this branch (two other bare `naruon#...` mentions
  in the file predate this branch and are out of this pass's scope). **Fix:** qualified both new
  references to `ContextualWisdomLab/naruon#1486`. The `.github#1659` same-repo reference was left as-is
  since it already complies.
- **Finding 2 (SEC, real, recorded not rewritten) — "Product logins collect identity passwords."**
  Anchored on `docs/product-goal-directive.md`§4's verbatim owner blockquote (line 183): "Keyverse는
  인증 backend로 유지하되(Direct Grant/ROPC 또는 Keycloak REST API), 로그인·가입·복구는 제품 자체
  form으로 만든다." The underlying technical claim is correct and well-established: OAuth2 ROPC/"Direct
  Grant" by definition has the client application itself collect and forward the user's raw password,
  unlike a redirect-based Authorization Code flow where only the identity provider's own hosted page
  ever sees it — precisely the isolation property RFC 6819/the OAuth 2.0 Security BCP cite as the
  reason ROPC is discouraged. Confirmed via `grep -rln "ROPC\|Direct Grant\|passwordless" docs/adr/`
  and a grep of this file that this trade-off was genuinely untracked anywhere in this repo — a real
  gap, not a duplicate. **Not fixed by editing the quote:** this sentence is the owner's own explicit,
  deliberate architecture choice (naming both ROPC and the Keycloak REST API specifically, almost
  certainly *because* both allow the product-branded, non-redirected login UI the same sentence
  mandates, despite the well-known trade-off) — rewording it would substitute this session's judgment
  for an explicit owner decision, which this file's own governance clause and this PR's established
  practice throughout forbid. **Recorded instead:** added `G-24` to the gap register plus a full
  narrative entry in `docs/product-technical-gap-baseline.md`, naming the trade-off, confirming it was
  untracked, and directing a future Keyverse-integration ADR to make an explicit reviewed decision
  (accept with compensating controls — TLS, no credential logging/storage beyond the immediate
  exchange, product-side rate-limit/lockout — or revise the pattern) rather than leaving the trade-off
  implicit.
- **Verification (this round):** `git diff HEAD -- docs/product-goal-directive.md` → empty at the time
  of this round's own edit, confirming this round's change (adding G-24) touched only
  `docs/product-technical-gap-baseline.md` and did not modify `docs/product-goal-directive.md` — a claim
  about this round's edit scope, not a comprehensive proof that the §4 blockquote has stayed
  byte-for-byte identical to the owner's original text across this PR's entire commit history (which
  has, by design, added new sentences to it in earlier, individually-verified-against-the-owner's-text
  rounds); `git diff --check origin/main -- docs/product-technical-gap-baseline.md` → exit 0;
  `grep -n "�" docs/product-technical-gap-baseline.md` → no matches;
  `grep -rln "ROPC\|Direct Grant\|passwordless" docs/adr/` → no matches (confirms G-24 was genuinely new);
  `PYTHONPATH=. python3 -m pytest tests/test_product_technical_gap_baseline.py -q` → 5 passed.
- **PR:** `ContextualWisdomLab/.github#1659`.

## 2026-09-02 Devin Review, round 7: one real technical error in this session's own G-24 compensating-control suggestion fixed, one real verification-claim overreach corrected

- **Date:** 2026-09-02, after round 6's push (`fcad134f`).
- **Subject:** a seventh Devin Review pass found 2 new items: 1 `SEC`, 1 `ANALYSIS`. Both about this
  session's own prior-round work, not the owner's directive text.
- **Finding 1 (SEC, real, fixed) — "Embedded webview defeats OAuth isolation."** Round 6's `G-24` entry
  suggested "a PKCE-based Authorization Code flow inside an embedded/native webview" as a lower-risk
  alternative to ROPC. This conflates two orthogonal OAuth protections: PKCE protects the *authorization
  code exchange* from interception/replay by a different app on the same device; it says nothing about
  who can observe the *login page itself*. An embedded webview is rendered inside, and fully inspectable
  by, the hosting product's own process — cookies, DOM, injected JS, form field values are all reachable
  by the product regardless of PKCE — so it provides **no isolation improvement over ROPC at all**. This
  is precisely why RFC 8252 ("OAuth 2.0 for Native Apps") mandates the external user agent (system
  browser, or an OS-mediated in-app-browser-tab construct such as `SFSafariViewController`/
  `ASWebAuthenticationSession` on iOS or Chrome Custom Tabs on Android — a separate, product-inaccessible
  process/cookie jar) rather than an app-embedded webview. **Fix:** removed the embedded-webview
  suggestion from both the `G-24` register row and its narrative entry; added a correction paragraph to
  the narrative explaining the error (PKCE ≠ webview isolation) and stating the technically correct
  alternative, if one is wanted: Authorization Code + PKCE *via the external user agent*, never an
  embedded webview.
- **Finding 2 (ANALYSIS, real, fixed) — "Verification cannot prove unchanged text."** Round 6's
  verification line claimed `git diff docs/product-goal-directive.md` → empty "confirms the verbatim
  blockquote was not touched," phrased as an unqualified claim. A bare `git diff` only compares the
  working tree against the index/HEAD at the moment it's run — it proves that *round's own edit* made no
  further change to the file, not that the blockquote has been byte-for-byte stable across this PR's
  entire commit history (which it has not been, by design — earlier rounds added new sentences to it,
  each individually verified against the owner's supplied text at the time). **Fix:** reworded the round
  6 verification entry above to scope the claim correctly to "this round's own edit" rather than
  implying a whole-PR-history proof.
- **Verification:** `grep -n "PKCE\|embedded" docs/product-technical-gap-baseline.md` → confirms the
  embedded-webview suggestion no longer appears in either the register row or narrative (only the
  correction paragraph mentions "embedded" while explaining why it's wrong);
  `git diff --check origin/main -- docs/product-technical-gap-baseline.md docs/doctoring/product-goal-directive.md`
  → exit 0; `PYTHONPATH=. python3 -m pytest tests/test_product_technical_gap_baseline.py -q` → 5 passed.
- **PR:** `ContextualWisdomLab/.github#1659`.
