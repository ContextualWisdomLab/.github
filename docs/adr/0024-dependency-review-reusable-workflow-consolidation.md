# ADR-0024: Consolidate per-repo Dependency Review workflows into one reusable workflow

- **Status:** Accepted
- **Date:** 2026-09-02
- **Scope:** `.github/workflows/dependency-review.yml` (new, central, `workflow_call`);
  thin callers in `argos`, `mightyETL`, `newsdom-api`, `scopeweave`, `naruon`
  (`naruon` added same-day, see "Addendum: naruon" below)

## Context

Four repositories each carried an independently hand-written
`dependency-review.yml` running `actions/dependency-review-action` on pull
requests: `argos`, `mightyETL`, `newsdom-api`, `scopeweave`. This is exactly
the drift `docs/CWL-MASTER-CONTEXT.md` §7 and this repo's own
"individual-repository workflow duplication" standardization effort target —
per-repo copies of the same control drift independently and cost bootup time
on every PR run.

A field-by-field audit of all four files (2026-09-02) found:

| Field | argos | mightyETL | newsdom-api | scopeweave | naruon |
| --- | --- | --- | --- | --- | --- |
| `fail-on-severity` | `moderate` | `high` | unset (action default `low`) | `moderate` | `moderate` |
| `allow-ghsas` | none | none | `GHSA-69w3-r845-3855` | none | none |
| `comment-summary-in-pr` | unset | unset | unset | `on-failure` | `never` (explicit) |
| step-level `continue-on-error` | `true` | unset (blocking) | unset (blocking) | unset (blocking) | unset (blocking) |
| Dependency Graph availability handling | none (always runs, no fallback) | static `github.event.repository.private` branch to a separate no-op job | none | dynamic API preflight (`dependency-graph/compare` HTTP status): 200 → run the gate, 403/404 → warn and skip, any other status → hard-fail the job | none |
| `step-security/harden-runner` | absent | absent | absent | absent | present (egress audit) |
| trigger scope | `pull_request: branches: [main, developmental]` | `pull_request` (all branches) | `pull_request` (all branches) | `pull_request` + `workflow_dispatch` | `pull_request: branches: [develop, master, release/**]` + `workflow_dispatch` |
| concurrency group | none | `${{ github.workflow }}-${{ github.event.pull_request.number \|\| github.ref }}` | none | `dependency-review-${{ github.event.pull_request.number \|\| github.ref }}` | `dependency-review-${{ github.event.pull_request.number \|\| github.ref }}` |
| `actions/checkout` pin | unpinned `@v4` | n/a (action doesn't need checkout) | SHA `3d3c42e5...` | SHA `9c091bb2...` (v7.0.0) | SHA `3d3c42e5...` (v7.0.1) |
| `dependency-review-action` pin | unpinned `@v4` | SHA `a1d282b3...` (v5.0.0) | SHA `a1d282b3...` | SHA `a1d282b3...` | SHA `a1d282b3...` |
| `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24` | unset | unset | `true` | unset | unset |

Two findings changed the design from a naive copy-paste consolidation:

1. **Severity and the GHSA allowlist genuinely vary per repo** — these are
   real policy differences (newsdom-api carries a documented upstream false
   positive it allowlists; mightyETL runs a stricter `high`-only gate), not
   accidental drift. They must stay per-caller inputs, not get silently
   flattened to one value.
2. **mightyETL's public/private branch is the wrong generalization.**
   `github.event.repository.private == false` assumes GHAS availability
   tracks repository visibility, but a private repository can have GitHub
   Advanced Security enabled (making Dependency Graph available) while a
   public repository can still lack Dependency Graph in edge cases. scopeweave's
   dynamic preflight — call the dependency-graph compare API directly and
   check the HTTP status — checks the actual capability rather than inferring
   it, and already existed independently in one of the four originals. This
   ADR generalizes scopeweave's approach to all four callers rather than
   mightyETL's, and drops the separate no-op fallback job in favor of one job
   with a conditional step (the same job either runs the gate or emits the
   unavailability note, never both, with no risk of the fallback job being
   forgotten when Dependency Graph later becomes available). scopeweave's
   preflight also distinguishes a confirmed-unavailable response (403/404 —
   warn and skip) from any other unexpected HTTP status (500, an auth
   failure, a transient GitHub API problem — hard-fail the job instead of
   silently skipping the security gate); the reusable workflow preserves
   that exact distinction rather than the simpler "any non-200 means
   unavailable" behavior an initial draft of this workflow used, since
   collapsing a real failure into "unavailable" would silently drop
   coverage instead of surfacing the problem.
3. **`comment-summary-in-pr: on-failure` is a uniformly-beneficial UX
   improvement, not a policy choice.** Only scopeweave's original set it
   (posts the dependency-review findings as a PR comment when the gate
   fails). It changes nothing about pass/fail semantics, only where a
   failure's detail is surfaced, so it is hardcoded uniformly rather than
   made an input — the other three repositories gain it for free.
4. **`FORCE_JAVASCRIPT_ACTIONS_TO_NODE24` is a forward-compatibility setting,
   not a policy choice.** newsdom-api was the only original to set it,
   opting its job into GitHub's Node 24 actions runtime ahead of the default
   cutover for the JS actions it runs (`actions/checkout`,
   `actions/dependency-review-action` — both JS actions in every one of the
   four originals). There is no reason the other three repositories should
   not also get this ahead of Node 20's eventual end-of-life, so it is
   hardcoded uniformly in the reusable workflow's job `env`, not made an
   input.

## Decision

Add `.github/workflows/dependency-review.yml` to `ContextualWisdomLab/.github`
as a `workflow_call` reusable workflow with three inputs for the
genuinely-varying fields: `fail_on_severity` (string, default `"moderate"`),
`allow_ghsas` (string, default `""`), and `continue_on_error` (boolean,
default `false`, for argos's non-blocking original behavior). The dynamic
Dependency Graph availability check (scopeweave's design) is hardcoded and
uniform for every caller — it is a correctness fix, not a policy choice, so
it does not need to be an input.

Each of the four repositories keeps a thin caller workflow with its own
`on: pull_request` trigger (including argos's `branches:` restriction, which
cannot live inside a `workflow_call` target), a `concurrency` group (added to
argos and newsdom-api, which lacked one, bringing all four to the same
cancel-in-progress-on-repush posture used elsewhere in the org per the
concurrency-standardization pass this workflow-consolidation effort is part
of), and `with:` values reproducing that repository's original severity and
allowlist exactly. The old hand-written workflow bodies are deleted from each
repository in the same change, per this org's "repository-local copies are
drift sources, not repo-specific contracts" principle
(`README.md` policy summary; this repo's own `CLAUDE.md`).

## Consequences

- One place to fix a bug in the dependency-review logic (e.g. the
  availability-detection curl call) instead of four.
- Each repository keeps its own severity/allowlist policy explicitly and
  visibly in its own thin caller, not hidden in a shared default that could
  silently loosen or tighten a repo's actual gate.
- argos and newsdom-api gain the cancel-in-progress concurrency group they
  previously lacked, at no cost — a stale run for a superseded push no longer
  keeps running or occupying a runner slot.
- `mightyETL`'s previous two-job (public/private) shape becomes one job; the
  private-repo fallback note now fires from a live capability check instead
  of an assumption, so it no longer misclassifies a private+GHAS-enabled
  repository as unsupported, or a public+Dependency-Graph-disabled repository
  as supported.
- argos's `unpinned @v4` and `newsdom-api`'s slightly older checkout pin are
  both upgraded to the same current, verified pins the reusable workflow
  uses, closing that drift too.

See `docs/doctoring/dependency-review-reusable-workflow-consolidation.md` for
the full per-repo audit and the exact diffs each caller received, including
two post-merge corrections found by Devin's review on the caller PRs: (1)
every caller now pins `uses:` to this file's exact commit SHA rather than
the mutable `@main`, since a mutable central-workflow reference runs
unreviewed against every caller's PR checks; (2) converting a job to
`uses: <reusable workflow>` renames its published check-run to a combined
`<caller job> / <called job>` name, which broke `newsdom-api`'s branch
protection (it required the old standalone name) until that required-check
name was updated to match.

## Addendum: naruon (2026-09-02, later the same day)

A peer session's fresh org-wide workflow-duplication survey (63 repos, 255
workflow files) found a fifth repository, `naruon`, independently carrying
its own `dependency-review.yml` — missed by the original survey this ADR's
consolidation was based on, which never covered `naruon`. Auditing it found
two real, non-cosmetic differences from the four originals above:

1. **A `step-security/harden-runner` step (egress audit), present in none
   of the original four.** Not a per-repo policy — it is a uniformly
   beneficial security-hardening practice already standard elsewhere in
   this org's own workflows (e.g. `pr-review-autofix.yml`), so it is added
   to the reusable workflow itself, as its first step, applying to every
   caller including the four already migrated (no caller-side change
   needed for this one).
2. **`comment-summary-in-pr: never`, an explicit opt-out**, conflicting
   with the earlier decision (see item 3 above) to hardcode
   `comment-summary-in-pr: on-failure` uniformly for every caller. That
   earlier decision was made when only scopeweave's original set the
   field at all, so "hardcode it uniformly" cost no caller its own choice.
   naruon proves that assumption wrong: hardcoding it now would silently
   overturn an explicit, deliberate choice naruon's original workflow
   made. Corrected by making `comment_summary_in_pr` a proper
   `workflow_call` input (default `"on-failure"`, preserving current
   behavior for the four already-migrated callers with no changes needed
   on their side; `naruon`'s caller explicitly sets `"never"`).

`naruon`'s other fields (`fail-on-severity: moderate`, no `allow-ghsas`,
multi-branch trigger `develop`/`master`/`release/**` plus
`workflow_dispatch`, its own `concurrency` group, job-level `permissions:`
redundant with the workflow-level block, and an informational "Log
dependency review policy" step) either match an existing input, are
caller-side triggers/concurrency untouched by this ADR's design, or (the
informational logging step, and the redundant job-level `permissions:`)
are dropped as they add no policy value the central workflow or the
underlying action doesn't already provide.
