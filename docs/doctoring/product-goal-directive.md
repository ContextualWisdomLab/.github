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
  reference-library bullet list with an explicit table of 23 named
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

1. **Repo-existence check.** Every one of the 30 repositories named across
   §5 and §9 (the §5 ontology-ownership discussion names four of these —
   `ConceptWeave`, `semantic-data-portal`, `context-graph-contracts`,
   `enterprise-architecture-core` — as a named subset of, not additional to,
   the 23 §9 core repos; plus the seven §9 domain-consumer repos) was
   checked against a live listing of every `ContextualWisdomLab` repository
   the operating account can reach. All 30 matched exactly, including case
   (e.g. `ConceptWeave`, `EgressWeave`,
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

## 2026-09-02 revision (third, same-day refinement)

- **Subject:** the owner issued a third, further-refined version of the
  directive the same day as the second revision above, delivered directly in
  an agent session (again not via a PR comment). Per this file's own conflict
  policy, `docs/product-goal-directive.md` was updated in place again — on
  the same branch/PR as the second revision (`docs/product-goal-directive-2026-09-02-revision`,
  ContextualWisdomLab/.github#1692), not a new PR, since that PR was still
  open/draft and unmerged when this third revision arrived. The prior
  agent-session identity that authored the second revision's PR body could
  not be directly confirmed as the same session continuing (concurrent
  sessions under the same account are normal per §2's "don't assume
  concurrent commits are a race" instruction), so this revision's notes are
  additive to, not a rewrite of, the second revision's verification record
  above — both are kept so the reconciliation trail stays intact regardless
  of which session's account of events is read first.

### What changed in the directive text (second revision → third revision)

- §1: added an explicit constraint on what "0 open PRs" may mean — reaching
  it via merge or via a successor PR's full absorption of a predecessor's
  valid delta only, never via a bare close. This is a forward reference to
  §2's new repair-vs-close policy below.
- §2: gained a substantial, entirely new PR-lifecycle policy not present in
  the second revision at all — a `single-writer`/DDD violation, wrong
  base/merge conflict, ADR-number collision, premature `Accepted` status, an
  unprotected dependency, or a missing test/fixture/contract is a **repair
  finding**, not grounds for closing a PR. Required response: downgrade to
  Draft/Proposed and non-force restack/retarget onto the correct owner
  stack (never force-push over someone else's branch); resolve a
  `single-writer` conflict by integrating both deltas, never discarding
  either; when an agent can't fix a PR directly, a successor must fully
  absorb its valid delta and continue the predecessor's intent; a PR
  blocked on an unlanded prerequisite stays open while the prerequisite is
  completed; a mistakenly closed PR is recovered via reopen or successor,
  not left closed. Closing a PR at all is permitted only for an explicit
  user request, no valid delta remaining, a malicious change, or full
  successor absorption — and even then, "closed" is a label, not
  confirmation the underlying work landed anywhere.
- §4: dropped the second revision's named-framework shortlist
  ("React·Vite·shadcn/ui·jQuery 4"); the stack-choice criteria are now
  stated framework-agnostically (security, maintainability, standards,
  accessibility, measured performance), while still naming `shadcn/ui`
  explicitly as the owned component source.
- §5: moved the second revision's detailed per-repo ontology-owner
  breakdown (which repo does discover/propose/align/validate/publish, etc.)
  out of §5 and into §9, where the full core-repo table now lives; §5 itself
  now just states the responsibilities are split across separate owners and
  points to §9.
- §8: spelled out, in the quoted text itself, exactly how the
  `orchestrator/free` pin must be implemented at the GitHub Actions layer —
  workflows select only the pool id and a gateway token, never a concrete
  provider/model/group name or a paid-fallback flag; all free-candidate
  discovery/routing/fallback happens inside contextual-orchestrator itself;
  a workflow fails closed (not to a paid model) when no free capability is
  available. This is strictly more specific than the second revision's bare
  "`orchestrator/free` 고정," not a change in intent.
- §9: added an explicit definition of what "core foundation" means (not a
  common install for every product; a selective control-plane/service/
  library one repo canonically owns because a responsibility repeats across
  products, with role/maturity verified from protected-branch evidence, and
  an open PR proposing core status is `Proposed`, not authoritative yet);
  reorganized the same 21-repo list into five named categories (조직·계약 /
  의미·데이터 / AI·운영 / Identity·보안·runtime / 재사용 기능) instead of the
  second revision's flat bullet list; and added concrete interim-boundary
  mechanisms for the §2 build-the-core policy — while an owner is still
  building a needed capability, a consumer holds the boundary with a port,
  an ACL, a feature flag, or a test double, and must not read the owner's
  source, database, or a temporary branch directly.

### Verification performed this revision

1. **Repo list unchanged, re-confirmed.** The third revision's §9 names the
   same 21 core repos as the second revision (reorganized into categories,
   not expanded or reduced), plus the same second-revision consumer set is
   implied by §9's new opening definition even though the third revision's
   quoted text doesn't restate the seven-repo consumer list verbatim. No new
   repo-existence check was needed beyond the second revision's — recorded
   inline in the directive (§9 "Verification" note) rather than re-running
   the same live-listing check for an unchanged set.
2. **§2 repair-vs-close policy — no conflict found against
   `docs/CWL-MASTER-CONTEXT.md` or `docs/agent-github-project-protocol.md`.**
   This is new operational policy (how to handle a defective PR) rather than
   a restatement of an existing binding convention, so there was nothing to
   reconcile it against; it does not contradict anything already binding.
3. **§8's newly-explicit workflow-implementation language — re-verified
   against the same four workflow files as the second revision**
   (`opencode-review-dispatch.yml`, `noema-review.yml`, `strix.yml`,
   `pr-review-autofix.yml`): all four already set only the pool id plus a
   gateway token, never a provider/model/group name or paid-fallback flag,
   and `strix.yml` fails closed on any other requested value — the third
   revision's more detailed wording matches confirmed reality exactly, same
   conclusion as the second revision's check, now more specifically stated.

### Audit trail (2026-09-02, third revision)

- `docs/product-goal-directive.md` — updated again in place; each section
  with third-revision changes carries its own dated note distinguishing
  second-revision text from third-revision text, and the "Revision history"
  section at the end of the file now has three dated entries.
- ContextualWisdomLab/.github#1692 (branch
  `docs/product-goal-directive-2026-09-02-revision`) — the same open PR
  carrying both the second and third revision's commits; not superseded by
  a new PR, per this directive's own "edit this file in place... do not
  fork a second copy elsewhere" policy applied to the PR-branch level too.

## 2026-09-02 Devin Review findings on PR #1692 — three confirmed, fixed

Devin Review's automated pass on #1692 raised six findings; three were confirmed real and fixed in
place (not by editing the verbatim quoted directive text), one required cross-repo verification beyond
this directive's own file, and two were informational/no-action. Following the same pattern as the
2026-08-30 Devin Review findings on the original PR #1429 (see above): confirm before fixing, fix in the
notes rather than the quoted blockquotes, and record the reasoning here.

1. **Confirmed — §5's "pause and confirm" rename language contradicted
   `docs/CWL-MASTER-CONTEXT.md` §7's binding "Do NOT ask the user to decide — make the call and proceed"
   (full autonomy) convention.** The reconciliation note added by the third revision (on breaking a
   published contract) said such a rename was "exactly the kind of consequential, hard-to-reverse action
   this org's own engineering conventions ask an agent to pause and confirm before taking" — that framing
   is simply wrong; §7 forbids asking the user to decide, full stop. Fixed by replacing "pause and
   confirm" with an autonomous, contract-safe process: preserve the existing published boundary (alias/
   deprecation shim/versioned API), prepare a versioned migration and compatibility plan, and record the
   rename as an ADR — proceeding without waiting on a human, with explicit approval required only where
   some *other* already-existing policy demands it for a specific irreversible action (this repo's own
   "never force-push over someone else's branch," for example), not as a new exception this note invents.
2. **Confirmed — repository-count arithmetic did not reconcile.** The doctoring text for the second
   revision (above) said §9 listed "21 named core-owner repos" and that "29" total names were verified
   across "the four ontology repos, all 21 §9 core repos, and the seven §9 domain-consumer repos" — but
   §9's actual list (verified by recounting it directly) has 23 entries, not 21, and the four ontology
   repos named in §5 (`ConceptWeave`, `semantic-data-portal`, `context-graph-contracts`,
   `enterprise-architecture-core`) are a **named subset of**, not additional to, those 23 — so treating
   them as a fifth, separate group of "4" was double-counting on top of an already-wrong base count. The
   correct total is 23 §9 core repos + 7 §9 domain-consumer repos = 30 unique names, not 29. Fixed both
   this doctoring file's second-revision section (above) and `docs/product-goal-directive.md`'s own §9
   "Verification" note to say 23 and 30, and to state the four-ontology-repos-are-a-subset relationship
   explicitly instead of implying a fifth additive group.
3. **Confirmed — sandbox ownership tension was left "open, not yet resolved" when it was directly
   resolvable.** The prior revision's §9 note flagged, but deliberately did not resolve, the tension
   between `docs/CWL-MASTER-CONTEXT.md` (`noema` owns "the lightweight quarantine sandbox") and this
   directive's §9 (`quarantine-sandbox-runtime` as its own dedicated repo) — correctly declining to guess,
   but Devin's finding was right that this PR could resolve it with the reading it had asked for the last
   time, rather than deferring again. Resolved this revision by cloning both repos read-only and reading
   `noema/README.md`, `quarantine-sandbox-runtime/README.md`, and `noema/docs/noema-agent-sandbox-plan.md`
   directly: `quarantine-sandbox-runtime`'s README ("Source-agnostic, credential-free artifact analysis
   runtime for the ContextualWisdomLab security ecosystem") is a near-verbatim match for
   `CWL-MASTER-CONTEXT.md` §6's own AI-SOC sandbox spec; `noema`'s current README is an unrelated product
   (GitHub OIDC/App-token credential exchange and review evidence, explicitly disclaiming model/provider
   ownership) with no artifact-analysis responsibility; and `noema`'s own sandbox-planning doc states the
   review agent "runs in a separate quarantined execution plane" that "must not run untrusted repository
   code in the Noema Worker process" — i.e. noema's own architecture decision already separates sandbox
   execution out of its own process. Fixed by updating `docs/CWL-MASTER-CONTEXT.md` at all four locations
   that said "noema quarantine sandbox" (§3's noema bullet, §6's header, the P1 roadmap bullet, and the
   ecosystem UML diagram's node label plus the `WARD -->|"quarantine detonation"|` edge target) to name
   `quarantine-sandbox-runtime` instead, and updating this directive's §9 note from "open, not yet
   resolved" to "resolved," while explicitly leaving open (as a coverage gap, not a contradiction) that
   §3 still doesn't mention most of §9's other newer repos at all.
4. **Informational, no action — empty-PR cleanup remains permitted.** Devin correctly read §2's closing
   conditions as still permitting closure of a non-draft, zero-changed-file PR; this is consistent with
   "no valid delta remains" and needed no change.
5. **Informational, no action — §9's quoted blockquote doesn't restate the seven-repo consumer
   classification verbatim.** True, but by design: the blockquote is the owner's verbatim wording (never
   paraphrased, per this file's own established pattern above) and the classification is preserved in the
   "Verification" note immediately below it, which is exactly what that note is for. No fix applied; the
   quoted text is not editable for this reason without violating the file's own verbatim-preservation
   rule.
6. **Informational, no action — pool pin matches deployed workflows.** Devin's own check confirmed §8's
   text already matches the four live workflow files. No action needed.
