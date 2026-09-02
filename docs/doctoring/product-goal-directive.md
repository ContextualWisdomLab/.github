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

## 2026-09-02 revision

- **Subject:** the owner reissued the full nine-section directive with
  substantially expanded text in every section (delivered directly in an
  agent session, not via a PR comment). Per this file's own conflict policy
  ("edit this file in place... do not fork a second copy elsewhere"),
  `docs/product-goal-directive.md` was rewritten in place to hold the new
  text verbatim, superseding the 2026-08-30 wording of all nine sections.

### What changed in the directive text

- §2 gained an explicit "build the immature core, don't bypass it" policy:
  a consumer repo must not duplicate, work around, or exclude functionality
  that belongs to an immature core/owner repo — it must develop the missing
  piece at the owner (RED test → contract → feature → docs → release) and
  only then consume the new versioned release. Exclusion is only valid when
  the boundary itself is wrong or there is no real shared demand, and must
  be recorded as an ADR.
- §2 also added a new Korean-copyediting tool reference,
  `https://github.com/epoko77-ai/im-not-ai`, for preserving meaning/facts/
  figures/proper nouns while polishing Korean prose. This repo is under a
  different GitHub account (`epoko77-ai`), not `ContextualWisdomLab` — noted
  inline in the directive so a future agent doesn't mistake it for an org
  core repo or try to add it via the org's repo-scope tooling as if it were
  one.
- §4 (renamed from "UX/UI and customer-facing expression" to "UX/UI, i18n,
  and customer-facing expression") added: UI-as-composed-reusable-objects,
  `shadcn/ui` as a component source (not a Storybook substitute), an
  explicit unpinned frontend stack (React/Vite/shadcn/ui/jQuery 4 chosen on
  merit, not mandated), Keyverse's role narrowed to an auth backend only
  (Direct Grant/ROPC or the Keycloak REST API) with product-owned
  login/signup/recovery forms, and a detailed i18n policy: 8 supported
  languages (ko/en/ja/zh/vi/es/de/fr), CJK/width/line-break/font-fallback/
  locale-format testing per language in Storybook and E2E, and — the
  highest-signal addition — translation strings must live as a DB-backed
  **versioned resource**, not a file or JS bundle; server/native code
  fetches only the screen keys it needs and caches them; the browser never
  loads a full catalog or heavy i18n JavaScript, and an SPA is not assumed.
  If no shared translation-management product exists yet, a new repo should
  provide per-product translation CRUD, review/approval, deploy, rollback
  API, and an admin UI.
- §5 (renamed to "Architecture, ontology, naming, and database conventions")
  added an ontology-ownership split across four named repos —
  **ConceptWeave** (observe→discover→propose→align→validate→review→publish
  and semantic release), **semantic-data-portal** (catalog/governance/
  consumption), **context-graph-contracts** (interoperability contracts),
  **enterprise-architecture-core** (Context Map and cross-org decisions) —
  with domain truth and Ubiquitous Language staying with each product
  owner, and every concept/relation/dimension/measure/mapping published as
  an immutable release carrying evidence/provenance/validity/confidence/
  status/deprecation/locale-label metadata; consumers may only use released
  API/contracts through an ACL, never copy files, run cross-service SQL, or
  publish without authorization. UI-translation and ontology-label ledgers
  are explicitly kept separate (the two i18n-shaped systems in §4 and §5
  are not the same system). §5's identifier-naming rule also broadened from
  "DB object names" to essentially every code identifier (variables,
  constants, parameters, fields, functions, methods, classes, types,
  modules, packages, APIs, DB objects, files, directories) — see
  Reconciliation below.
- §8 folded the pool pin directly into the quoted text ("`orchestrator/free`
  고정"), removing the prior section's ambiguity outright rather than
  needing an out-of-band note to resolve it.
- §9 (renamed from "Reference libraries and tool invocations" to "Core
  foundation and development/consumption boundaries") replaced the general
  reference-library bullet list with an explicit table of 21 named
  core-owner repos grouped by responsibility (workflow/review/security/
  release; enterprise architecture/context contracts; ontology generation
  vs. catalog/governance; model orchestration/OIDC/evidence; identity;
  outbound/browser/edge/sandbox isolation; batch/embedding; psychometrics
  measurement kernels; retrieval/threading; editor/diagram tooling; MHTML
  ETL; SAST/gateway), plus an explicit classification of seven repos
  (`naruon`, `LineageWeave`, `psychometrics-commons`, `disksage`,
  `PolicyWeave`, `CalendarWeave`, `supply-chain-control-plane`) as domain
  product/composition **consumers**, not core, with the instruction that
  genuinely shared functionality found duplicated across consumers should
  be extracted to a core owner and developed through integrated CI.

### Verification performed this revision

1. **Repo-existence check.** Every one of the 29 repositories named across
   §5 and §9 (the four ontology repos, all 21 §9 core repos, and the seven
   §9 domain-consumer repos) was checked against a live listing of every
   `ContextualWisdomLab` repository the operating account can reach. All 29
   matched exactly, including case (e.g. `ConceptWeave`, `EgressWeave`,
   `OriginWeave`, `DiagramWeave`, `PolicyWeave`, `CalendarWeave` — all
   PascalCase, confirmed correct as given, not "corrected" to another
   case). None needed a spelling or case fix. This check is recorded
   verbatim in the directive file itself (§9 "Verification" note) so a
   future agent doesn't have to re-derive it from this doctoring record.
2. **Conflict check against `docs/CWL-MASTER-CONTEXT.md`.** Two real
   tensions were found and handled per this file's stated conflict policy
   ("resolve the conflict and update whichever document is wrong — do not
   silently pick one"):
   - **§5 naming scope vs. §7's DB-object grandfather clause (resolved).**
     `docs/CWL-MASTER-CONTEXT.md` §7 is narrow and binding: *"DB object
     names = 2+ word snake_case (don't rename existing Camel/Pascal)."*
     The revised §5 is broader (every code identifier, not just DB
     objects) and says a violating name "gets replaced" — read alone and
     literally, combined with this org's full-autonomy convention, an
     agent could take that as a mandate to sweep every repo and
     force-rename every existing identifier that doesn't fit, which would
     be a large, high-risk, potentially breaking action with no ADR and no
     migration plan, and would directly contradict §7's explicit
     grandfather clause for the DB-object case it already covers. Added a
     reconciliation note directly under §5 in the directive (not inside
     the quoted text) stating: the broader rule applies going forward, on
     code an agent is already touching or creating, not as license to
     force-rename existing identifiers ecosystem-wide; §7's DB-object
     grandfather clause remains binding and unambiguous; a genuinely
     warranted repo-wide rename needs its own ADR and migration plan, not
     a blanket action under this directive.
   - **§9 quarantine-sandbox ownership vs. `docs/CWL-MASTER-CONTEXT.md` §3
     (flagged, not resolved).** §3 currently states `noema` owns "the
     lightweight quarantine sandbox." The revised §9 lists
     `quarantine-sandbox-runtime` as its own dedicated repo, grouped with
     `EgressWeave`/`OriginWeave`/`pingora-gateway` under "outbound·browser·
     edge·격리 core." Whether sandbox ownership moved to the new dedicated
     repo, is now shared between the two repos, or `quarantine-sandbox-runtime`
     covers a different scope than "the lightweight quarantine sandbox" in
     §3, was **not** verified against either repo's actual README/
     ARCHITECTURE content — doing so honestly requires reading both repos,
     which this pass did not do, rather than guessing. Recorded as an open
     item directly in the directive file (§9 "Open reconciliation item")
     instead of silently picking an answer. A future pass should read both
     repos and either update §3, update §9, or record an ADR if the split
     is a genuinely new architectural decision.
   - `docs/CWL-MASTER-CONTEXT.md` §3 was **not** otherwise updated this
     pass to add the ~13 §9 core repos it doesn't yet mention
     (`ConceptWeave`, `enterprise-architecture-core`,
     `context-graph-contracts`, `EgressWeave`, `OriginWeave`,
     `pingora-gateway`, `quarantine-sandbox-runtime`, `EmbedRelay`,
     `DiagramWeave`, `mhtml-etl-gateway`, `PolicyWeave`, `CalendarWeave`,
     `supply-chain-control-plane`, `psychometrics-commons`,
     `LineageWeave`) — that is a larger, separate reconciliation (each
     repo's actual role description in §3 should be written from that
     repo's own README/ARCHITECTURE, not paraphrased from this directive's
     one-line-per-repo summary) and is intentionally left as future work
     rather than rushed.
3. **§8 pool-pin state, re-verified against the actual workflow files**
   (not just ADR-0003's prose): `opencode-review-dispatch.yml`,
   `noema-review.yml`, `strix.yml`, and `pr-review-autofix.yml` in
   `ContextualWisdomLab/.github` all hardcode
   `contextual-orchestrator/orchestrator/free` (or `orchestrator/free` for
   the Noema sidecar), each with fail-closed validation rejecting any other
   value. §8's new explicit "`orchestrator/free` 고정" wording matches this
   confirmed reality exactly — no further action needed for this section.

### Audit trail (2026-09-02 revision)

- `docs/product-goal-directive.md` — the rewritten directive (all nine
  sections) and its inline 2026-09-02 reconciliation/verification notes
  under §2, §5, §8, and §9.
- `docs/CWL-MASTER-CONTEXT.md` §3, §7 — the documents this revision's
  reconciliation checks were run against; §3 still needs the larger,
  separate follow-up noted above.
- `.github/workflows/opencode-review-dispatch.yml`,
  `.github/workflows/noema-review.yml`, `.github/workflows/strix.yml`,
  `.github/workflows/pr-review-autofix.yml` — the live workflow files
  checked for the §8 pool-pin verification.
- `docs/adr/0003-contextual-orchestrator-vendored-free-zdr.md` — the
  authoritative ADR for *why* the pool pin is `orchestrator/free`; this
  revision's §8 note points here rather than restating the reasoning.
