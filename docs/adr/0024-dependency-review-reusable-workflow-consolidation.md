# ADR-0024: Consolidate per-repo Dependency Review workflows into one reusable workflow

- **Status:** Accepted
- **Date:** 2026-09-02
- **Scope:** `.github/workflows/dependency-review.yml` (new, central, `workflow_call`);
  thin callers in `argos`, `mightyETL`, `newsdom-api`, `scopeweave`

## Context

Four repositories each carried an independently hand-written
`dependency-review.yml` running `actions/dependency-review-action` on pull
requests: `argos`, `mightyETL`, `newsdom-api`, `scopeweave`. This is exactly
the drift `docs/CWL-MASTER-CONTEXT.md` §7 and this repo's own
"individual-repository workflow duplication" standardization effort target —
per-repo copies of the same control drift independently and cost bootup time
on every PR run.

A field-by-field audit of all four files (2026-09-02) found:

| Field | argos | mightyETL | newsdom-api | scopeweave |
| --- | --- | --- | --- | --- |
| `fail-on-severity` | `moderate` | `high` | unset (action default `low`) | `moderate` |
| `allow-ghsas` | none | none | `GHSA-69w3-r845-3855` | none |
| `comment-summary-in-pr` | unset | unset | unset | `on-failure` |
| step-level `continue-on-error` | `true` | unset (blocking) | unset (blocking) | unset (blocking) |
| Dependency Graph availability handling | none (always runs, no fallback) | static `github.event.repository.private` branch to a separate no-op job | none | dynamic API preflight (`dependency-graph/compare` HTTP status): 200 → run the gate, 403/404 → warn and skip, any other status → hard-fail the job |
| trigger scope | `pull_request: branches: [main, developmental]` | `pull_request` (all branches) | `pull_request` (all branches) | `pull_request` + `workflow_dispatch` |
| concurrency group | none | `${{ github.workflow }}-${{ github.event.pull_request.number \|\| github.ref }}` | none | `dependency-review-${{ github.event.pull_request.number \|\| github.ref }}` |
| `actions/checkout` pin | unpinned `@v4` | n/a (action doesn't need checkout) | SHA `3d3c42e5...` | SHA `9c091bb2...` (v7.0.0) |
| `dependency-review-action` pin | unpinned `@v4` | SHA `a1d282b3...` (v5.0.0) | SHA `a1d282b3...` | SHA `a1d282b3...` |
| `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24` | unset | unset | `true` | unset |

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
the full per-repo audit and the exact diffs each caller received.
