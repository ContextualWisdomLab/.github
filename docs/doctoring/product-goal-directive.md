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

## Revision (2026-09-02): directive text replaced in full

- **Date:** 2026-09-02
- **Subject:** The owner supplied a revised nine-section directive (pasted
  directly into an interactive session, not as a PR) that is substantially
  longer and more specific than the 2026-08-30 text it replaces. Per this
  file's own stated policy ("edit this file in place... do not fork a second
  copy elsewhere"), `docs/product-goal-directive.md`'s nine quoted sections
  were replaced in full, verbatim, with the new text; only the two
  reconciliation notes (§5 naming, §8 CI pool routing) and the surrounding
  scaffolding (title, "why this file exists," `/goal` pointer) were kept and
  updated, not the directive text itself.
- **PR:** ContextualWisdomLab/.github#1698 (product-goal-directive branch;
  see the PR for the exact diff).

### What changed in substance (not exhaustive — read the new §1-9 directly)

- **§1** adds an explicit anti-pattern: a PR reaching zero open state must
  come from a merge, or from a verified successor fully carrying forward its
  valid delta — never from a bare Close.
- **§2** is substantially expanded: Close is redefined as a repair-not-close
  action for most failure modes (single-writer/DDD violations, wrong
  base/conflicts, ADR number collisions, premature Accepted status,
  unprotected dependencies, missing test/fixture/contract) — demote to
  Draft/Proposed and non-force restack/retarget instead of closing. Close
  itself is now restricted to four cases: explicit user instruction, no valid
  delta, a malicious change, or full successor carry-forward. Also newly
  names https://github.com/epoko77-ai/im-not-ai for Korean phrasing/document
  translation review (meaning/facts/figures/proper nouns must be preserved).
- **§3** adds an explicit decision-record bar: reconstructable by a first-time
  reader (problem, constraints, alternatives, why chosen/rejected, evidence,
  risk, effect, follow-up), evidenced against exact-head/logs/issues/PRs/ADRs.
- **§4** is new in large part: shadcn/ui is named as the product-owned
  component source with Storybook as the verification environment; Keyverse
  is scoped specifically to Direct Grant/ROPC or the Keycloak REST API as an
  auth backend, with login/signup/recovery built as product-owned forms; and
  a full i18n subsection is new — 8 supported languages, a DB-backed
  versioned translation ledger (not files or a JS bundle), key-only
  lookup/cache on server/native, and a dedicated repo for translation
  workflow tooling if none exists yet.
- **§5** adds an ontology/semantic-layer ownership split (creation/publish vs.
  catalog/consumption vs. interoperability contracts vs. EA decisions each
  have a distinct owner; product domain truth/UL never moves) and loosens
  identifier casing from "snake_case" to "snake_case, camelCase, or
  PascalCase, snake_case preferred" for non-DB identifiers — see the
  in-file reconciliation note for what still applies to DB objects
  specifically.
- **§6** softens the earlier "all core math/perf code must be Rust, full
  stop" framing: Python is now explicitly deprioritized rather than banned,
  and a documented exception path exists (ADR-recorded scope/justification/
  removal condition) for the case where no practical Rust alternative exists
  for a Python-only ML runtime dependency, with the hot path still kept in
  Rust.
- **§7** adds a concrete performance target (p95 ≤ 20ms on every page, via
  async processing + k6 E2E) and a frontend-performance subsection (bundle
  size, heap, DOM, hydration, main thread, GC as replacement triggers for
  dependencies/rendering approach/frontend stack).
- **§8** adds explicit, mechanical CI-routing rules that were previously only
  implied: GitHub Actions model-backed workflows must pin to
  `orchestrator/free` and must not name a provider/model/group or a paid
  fallback — only a gateway token; missing capability fails closed rather
  than routing around the free pool. Also adds an explicit default-null model
  timeout policy (no app/agent/gateway-wide cap; upstream provider owns
  timing out a stalled call) and admin-web requirements for per-model
  enable/disable/restore with audit and API access.
- **§9** replaces the old flat repo list with a structured "core foundation"
  ownership taxonomy (org/contracts; meaning/data; AI/ops;
  identity/security/runtime; reusable capabilities), each entry naming its
  canonical-owner repo and scope, plus an explicit anti-bypass rule: a
  consumer must not copy/route around an immature or API-less owner repo —
  the owner ships RED→GREEN→immutable-release first, the consumer adopts
  after, and uses ports/ACLs/feature flags/test doubles as the boundary in
  the meantime.

### Reconciliation notes re-checked against the new text

1. **§5 wardnet example.** The new text no longer names "wardnet" (or any
   other product) as an "old name" example, so the specific conflict the
   2026-08-30 note flagged (wardnet is the *current* canonical name, not a
   legacy one) no longer has a live trigger in the quoted text. Kept a
   shortened note covering the still-relevant point: the DB-object grandfather
   clause in `docs/CWL-MASTER-CONTEXT.md` §7.
2. **§8 CI pool routing.** The new text now states directly that GitHub
   Actions model-backed workflows pin to `orchestrator/free` — which, as of
   2026-09-02, matches the owner-confirmed live state for **both** OpenCode
   Review and Strix (see `docs/adr/0003-contextual-orchestrator-vendored-free-zdr.md`'s
   2026-08-30/2026-09-02 amendments). The 2026-08-30 note's original point
   (this section describes orchestrator product capability, not CI routing
   policy) is kept as historical context, with a status update on top stating
   the risk it was tracking is now resolved and owner-reviewed.

## Audit trail (revision)

- `docs/product-goal-directive.md` — the revised directive and both
  reconciliation notes.
- `docs/adr/0003-contextual-orchestrator-vendored-free-zdr.md` — the
  2026-08-30/2026-09-02 amendments confirming the `orchestrator/free` pin for
  both OpenCode Review and Strix.
- `docs/CWL-MASTER-CONTEXT.md` §7 — the DB-naming grandfather clause the §5
  note still cites.
- ContextualWisdomLab/.github#1698 — the PR carrying this revision.
