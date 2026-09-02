# ADR-0022: Trust-bounded scope for agent PR follow-up, web/paper search, and issue authoring

- **Status:** Accepted
- **Date:** 2026-09-02
- **Decision owners:** ContextualWisdomLab platform maintainers
- **Scope:** ContextualWisdomLab/.github control plane. Informs, but does not bind without its
  own review, ContextualWisdomLab/contextual-orchestrator (PR #1009) and ContextualWisdomLab/noema
  (ADR-0012 / PR #536).
- **Figma File ID:** N/A. This repository has no customer UI.

## Context

The owner asked that Noema and/or the OpenCode Agent also handle PR follow-up work more broadly,
process review feedback, search the web, find papers, handle issues, and author issues on the
owner's behalf — to the same evidence-based, ADR-traceable, root-cause standard as
`docs/product-goal-directive.md`. A hard constraint was given and independently re-verified before
any design work started: the required, `pull_request_target`-triggered review gates
(`opencode-review.yml:11`, `noema-review.yml:11`) must keep `"edit": "deny"` — set globally and on
every agent in `opencode.jsonc:13,32,51,71` — because that job runs the base branch's trusted
scripts against an arbitrary, unauthenticated PR author's diff *as data*, before any human or
independent-agent review has happened. Nothing in this ADR touches that file or that trigger.

A fresh investigation (fresh clones, `.github@fb847d6a`, `contextual-orchestrator@88390816`,
`noema@6b2b3e90`, re-verified independently a second time before this design) found:

1. **PR follow-up autofix already exists and is already broader than "merge conflicts only."**
   `scripts/ci/pr_review_fix_scheduler.py:58` defines `REPAIR_MODES = frozenset({"review", "rca",
   "conflict"})`. `needs_autofix` (`pr_review_fix_scheduler.py:237-250`) dispatches bounded repair
   when the current-head OpenCode review is `CHANGES_REQUESTED` and the body is not a blocker
   marker; `needs_rca_repair` (`:253-266`) dispatches on failed-check evidence; `needs_conflict_resolution`
   (`:304-326`) is the merge-conflict path. All three route through `.github/workflows/pr-review-autofix.yml`,
   which triggers on `repository_dispatch` — explicitly *not* `pull_request_target` (comment at line 8) —
   checks out the trusted base-branch source (`github.sha`, lines 42-49), and scopes edit access to a
   sealed, review-thread-derived path allowlist verified by `pr_review_conflict_scope.py` after the run
   (line 460). No widening of dispatch scope is needed today; re-litigating "conflict-only" against this
   code would be building on a stale read.
2. **Web search exists as code but is unmerged, uncalled, and denied everywhere by design.**
   `contextual_orchestrator/web_search.py` is not on `contextual-orchestrator`'s `main`
   (`git merge-base --is-ancestor` is false); it lives on open PR #1009
   (`feat/web-search-mcp-a2a-foundation`), whose own commit message states there is "no concrete
   Strix/Noema caller yet." It has zero callers anywhere. Every `opencode.jsonc` in this
   organization — the required gate's (`opencode.jsonc:20-21,39-40,58-59,78-79`) and the autofix
   worker's generated one (`pr-review-autofix.yml:310-311,338-339`) — sets `"webfetch": "deny"` and
   `"websearch": "deny"`, and `"mcp": {}` besides. This is deliberate: the required gate runs against
   untrusted fork content, so outbound network access is an SSRF/exfiltration vector regardless of
   `edit`.
3. **Academic paper search has no code anywhere in the organization.** No arXiv/Semantic
   Scholar/OpenAlex/Zotero client exists in any script. `docs/product-goal-directive.md:36`
   (§3) already names Local Zotero as the intended source, conditionally ("Local Zotero API가
   되면…"), and `docs/doctoring/product-technical-gap-baseline.md:70-71` records a real session that
   found it unreachable and fell back to manual APA citation. This is aspirational infrastructure,
   not a live gap this ADR can close by itself.
4. **Issue authoring is missing in the three repos this ask names, but the pattern is solved
   elsewhere in the organization.** No `gh issue create` exists anywhere in `.github`,
   `contextual-orchestrator`, or `noema` — every `issues/{n}/comments` call found
   (`pr_review_fix_scheduler.py:159,351`, `agent_mention_sweep.py:271`, and others) is the
   PR-comments endpoint, not standalone-issue creation. But `four-pillars`'
   `hourly-product-loop.yml` already runs a scheduled, deterministic, idempotent issue
   sync (`gh issue create`/`comment`/`close` against one fixed-title issue) with plain
   `github.token`, and `mhtml-etl-gateway`'s `opencode.jsonc` already allows an OpenCode agent
   `"gh issue create *"`/`"edit *"`/`"comment *"`/`"close *"` on trusted, scheduled triggers, still
   with `webfetch`/`websearch` denied. This is a port, not an invention.
5. **`noema-core` (PR #536, opened hours before this design work, `mergeState: BLOCKED`) is not a
   viable host for any of this today.** Its entire surface is `build_openai_model()` and
   `build_agent()` — two functions wiring `pydantic_ai.Agent(...)`, plus a persona string. Its own
   module docstring says it "deliberately owns none of a consumer's domain logic: no verdict
   schema, no tool/deps machinery, no credential resolution or validation policy, no tenant
   isolation." No tools, no edit access, no sandboxing, no bash. ADR-0012 in that PR explicitly
   rejected a shared *service* (its Option B) because two of its three envisioned endpoints have no
   real callers yet, and scoped v1 to construction-wiring only. naruon's actual do-anything agent
   (`backend/services/noema_agent.py`, main, six `@agent.tool` closures at lines 504-537) is real but
   scoped to email/knowledge-graph/task tooling only, per `CWL-MASTER-CONTEXT.md:16`'s platform
   boundary, and does not consume `noema-core` yet.
6. **The organization's own "immature core gets completed at its owner, not worked around" rule is
   drafted but not binding yet.** The exact sentence — an immature dependency is fixed at its
   canonical owner via RED → GREEN → versioned release, never duplicated or worked around in a
   consumer, with an ADR as the only escape hatch — is not in `main`'s `docs/product-goal-directive.md`
   §2 today; it is live only on open PR `ContextualWisdomLab/.github#1682` (`mergeStateStatus:
   BLOCKED`). This ADR follows its intent anyway (it matches the owner's already-stated direction and
   this repository's existing `CLAUDE.md` "immature core" guidance), but does not treat #1682 as
   merged, binding text.
7. **No existing standing authorization names unattended issue creation.** `docs/product-goal-directive.md`
   contains zero occurrences of "이슈"/"issue" anywhere in its 96 lines. Its §2 ("동시 작업·PR
   운영·근본 수정") is written entirely in terms of PRs — Stacking, merge-readiness, Force-Push
   avoidance, Check failures. The standing autonomous-loop authorization this organization already
   operates under is real and broad for *PR* work; it does not, on its own text, extend to opening
   new public-visible Issues unattended. This is a genuine gap, not an assumption in either
   direction, and it directly shapes the issue-authoring design below.

## Trust-boundary decision

The required gates and the autofix worker sit on opposite sides of the same boundary, and every
decision in this ADR keeps them there:

- **`opencode-review.yml` / `noema-review.yml`** (`pull_request_target`, `edit: deny`, `mcp: {}`,
  `webfetch`/`websearch: deny`): judge *first-look, unauthenticated-author* content. Nothing has
  been reviewed yet; the diff is data, never a command; no write, no outbound network call, no merge
  decision can originate here. **Unchanged by this ADR, and nothing proposed here ever runs inside
  it.**
- **`pr-review-autofix.yml`** (`repository_dispatch` from the trusted scheduler only, base-branch
  source, OIDC/App-token credentials distinct from the required job's own token): acts only on a PR
  that has *already* received a formal review verdict — `needs_autofix`/`needs_rca_repair` gate on
  `has_current_head_changes_requested`, `needs_conflict_resolution` gates on
  `has_current_head_approval` unless the scheduled caller explicitly allows unreviewed conflict
  repair (and even then, produces a new head that must be fully re-reviewed). Its edit access is a
  sealed allowlist derived from the actual review threads, verified post-run. Its output is never
  merge evidence on its own: a fresh push resets prior approvals and Checks per the merge
  scheduler's exact-head requirement, so a wrong repair cannot merge unreviewed.

This is why the autofix worker may be trusted with *more* than the required gate ever gets, and why
this ADR's roadmap (web search, paper search) only ever proposes extending *that* worker, never the
required gate: its blast radius is already bounded by (a) a narrow, verified edit-path allowlist,
(b) mandatory fresh re-review of everything it touches, and (c) it only ever runs on content a formal
review has already looked at once. Adding a capability there is extending an already-bounded trust
region, not opening a new one — provided each addition gets its own equivalent bound (§ Deferred
items below states what that bound must be for web/paper search specifically, since neither is
merged yet).

Issue authoring's draft-first design (below) applies the same boundary at a different layer: because
no existing standing text authorizes *unattended* issue creation, the correct boundary today is
between *composing* evidence-gated content (safe, reversible, no GitHub-visible effect) and *making
it visible* (irreversible-ish, needs an explicit human or explicitly-authorized trigger) — the same
shape as this repository's own `infra/cloudflare/reconcile.sh` convention: dry-run by default,
writes only on an explicit `mode = apply`.

## Chosen architecture

1. **Review-finding autofix (existing, re-verified, not extended in this PR).** `review`/`rca`/
   `conflict` modes already cover ordinary review findings, failed-check RCA, and merge conflicts,
   with the correct trust model. No code change ships here; re-verifying this against a fresh read
   (not the original investigation's cached understanding) is itself part of this ADR's evidence.
2. **Web search (deferred, not implemented in this PR).** `contextual_orchestrator/web_search.py`
   must first merge on its own review in `contextual-orchestrator` (PR #1009) as an independent
   decision — this ADR does not pre-approve that PR. Once merged, it may be wired *only* into the
   `pr-review-autofix.yml` worker's generated `opencode.jsonc` (never the required gate's), scoped to
   a narrow verification task (e.g. "does this citation/library-version/API claim in the review
   thread hold up"), with an outbound-URL/domain scope check equivalent in spirit to
   `pr_review_conflict_scope.py`'s path allowlist — that scope check does not exist yet and is
   required before this un-denying is safe, not optional polish.
3. **Academic paper search (deferred, not implemented in this PR).** No code exists anywhere in the
   organization. The right shape, when built, is a minimal client against a permissive, free,
   ZDR-compatible API (OpenAlex or arXiv, evaluated the way `contextual-orchestrator` already
   evaluates provider ZDR posture) offered as a tool to the same trusted autofix worker, with Local
   Zotero preferred when reachable per `docs/product-goal-directive.md` §3 and OA/DOI citation as the
   documented fallback exactly as practiced today.
4. **Issue authoring — the first increment shipped in this PR.** A pure, evidence-gated draft
   composer, `scripts/ci/issue_draft_composer.py`: validates that a proposed issue has a non-empty
   summary, at least one citation-backed finding, and a traceable source, renders it to Markdown, and
   *only* calls `gh api -X POST repos/{repo}/issues` when a caller explicitly passes `--create`. No
   workflow in this PR triggers `--create` on a schedule or on any automated event — the tool exists,
   is tested, and is invokable, but nothing currently invokes it unattended. This sidesteps the
   authorization gap found in Context item 7 rather than assuming it away in either direction: a
   human (or an agent working interactively, as this session is) can use `--create` today; wiring it
   into a scheduled/dispatched trigger is deferred until `docs/product-goal-directive.md` names
   issue-creation authorization explicitly (mirroring how PR #1682 is the tracked, not-yet-merged
   place that kind of directive-text change belongs).
5. **Host for all of the above: `.github`/`contextual-orchestrator` today, not `noema-core`.**
   Per Context item 5, `noema-core` cannot host tool-calling, edit, or sandboxed work yet — it is
   three-days-old construction-wiring DRY-ing with no tool machinery at all. Building any of this
   *inside* `noema-core` now, or working around its immaturity by duplicating logic in a product
   repo, would be exactly the pattern PR #1682's pending directive text (and this repository's
   existing `CLAUDE.md` "immature core" guidance) says not to do. The composer shipped here is
   deliberately structured to make a future move cheap rather than to pre-empt the decision: its
   validation and Markdown-rendering functions (`load_draft`, `render_markdown_body`) are pure,
   side-effect-free, and stdlib-only, so they can become a `noema-core`/naruon `@agent.tool` closure
   later with no restructuring — only the CLI/`gh`-invocation wrapper (`create_issue`, `main`) is
   `.github`-specific and would stay behind.

## Connection to backlog item 5 and ADR-0012

`CWL-MASTER-CONTEXT.md:36` already names the target shape: "noema — agent runtime … a GitHub Review
Agent in CI + a do-anything agent inside naruon." Backlog item 5 (Noema as a reusable DDD agent for
naruon, not just a CI reviewer) and `noema`'s own ADR-0012 (unify on a shared `noema-core` package)
are the same convergence this ADR defers into, not a separate track: once `noema-core` grows tool/
edit/sandbox machinery (ADR-0012's own stated next step, not yet scoped there), the review-finding
autofix worker's OpenCode CLI invocation, naruon's six-tool agent, and this ADR's issue-draft/
web-search/paper-search capabilities become the same kind of `@agent.tool` surface on the same
runtime instead of three independently-maintained integrations. This ADR does not implement that
convergence — `noema-core` is not ready, and forcing it in now would itself violate the reuse-boundary
rule this ADR otherwise follows — but the composer's pure-function design keeps that later move
a lift, not a rewrite.

## Deferred items (roadmap)

Recorded in full, with owning repository, in `docs/product-technical-gap-baseline.md`'s
2026-09-02 entry so a later cycle does not need to re-investigate from scratch:

1. Merge `contextual-orchestrator#1009` (web search) on its own review; only then wire it into
   `pr-review-autofix.yml`'s generated config with a new outbound-scope check. Owner:
   `contextual-orchestrator`, then `.github`.
2. Build a minimal, ZDR-evaluated academic paper search client and offer it to the same worker;
   prefer Local Zotero when reachable per the standing directive. Owner: `contextual-orchestrator`
   or `noema-core` once tool-capable, then `.github`.
3. Wire `issue_draft_composer.py --create` into a trusted, scoped trigger (e.g. a
   `repository_dispatch` sibling to the autofix worker, gated the same way) once
   `docs/product-goal-directive.md` explicitly authorizes unattended issue creation. Owner:
   `.github`, blocked on a directive-text decision, not on code.
4. Once `noema-core` grows tool/edit/sandbox machinery (its own future ADR, not this one), migrate
   `load_draft`/`render_markdown_body` there as an `@agent.tool`, alongside naruon's existing six
   tools and any web/paper-search tools from items 1-2, per ADR-0012's shared-runtime direction.
   Owner: `noema`.
5. Re-adopt this ADR's reasoning once `.github#1682` merges the explicit "immature core" directive
   text, to confirm nothing here drifted from the final wording. Owner: `.github`.

## Alternatives rejected

- **Widen the required gate's `opencode.jsonc` (`edit`, `webfetch`, `websearch`) directly.**
  Rejected outright — this is the constraint the owner gave and independently re-verified as still
  true; it judges unauthenticated-author content and must stay fail-closed.
- **Build issue-authoring as a new invention instead of porting the `four-pillars`/
  `mhtml-etl-gateway` pattern.** Rejected: those two repositories already carry a working, scheduled,
  trusted, idempotent version of exactly this; porting is lower-risk than a fresh design and matches
  this organization's stated preference for reusing solved patterns over inventing new ones.
- **Ship `issue_draft_composer.py` wired to auto-create on a schedule now, treating the standing
  PR-loop authorization as implicitly covering issues too.** Rejected per Context item 7: the
  directive text is PR-specific by its own words, and assuming coverage either way was explicitly
  out of scope for this design. Flagging the gap and shipping the safe (draft-only) half is the
  responsible middle path.
- **Force the new capabilities into `noema-core` now to avoid a second migration later.** Rejected:
  `noema-core` has no tool/edit/sandbox surface to build against yet (Context item 5); building
  against a package that owns none of the needed machinery would mean effectively vendoring that
  machinery into `.github` anyway, which is the exact "consumer works around an immature core"
  pattern the org's own pending rule (and existing `CLAUDE.md` guidance) rejects.
- **Treat PR #1682's pending directive text as already binding.** Rejected: it is open and
  `BLOCKED`. This ADR follows its intent because it matches the owner's already-stated direction, but
  documents the distinction rather than treating an unmerged PR as governance.

## Validation

`scripts/ci/issue_draft_composer.py` ships with unit tests covering: evidence validation (missing/
empty summary, title, source, findings, malformed labels, oversized title, malformed repo), Markdown
rendering (summary/evidence/source/attribution sections all present, citations attached to their
findings), the CLI's draft-only default (no `gh` invocation, evidence-gate errors surfaced as a
non-zero exit with a clear message), and the `--create` path (exact `gh api` argv, including
repeated `labels[]` fields) via a monkeypatched `run()` — the same seam
`pr_review_fix_scheduler.py`'s own tests use for `gh` calls. `coverage run -m pytest tests` and
`interrogate` must both stay at 100% on `scripts/ci`, matching every other module in this
repository; no exception is requested for this file.
