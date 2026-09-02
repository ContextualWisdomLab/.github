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
