# Org-queue-sweep review-dispatch rotation

## Problem

`org-queue-sweep` in `pr-review-merge-scheduler.yml` walks every organization
repository once per 15-minute tick and consumes bounded, organization-wide
review-dispatch budgets across that entire walk. Default-base work uses
`ORG_SWEEP_REVIEW_DISPATCH_LIMIT` (default `1`); stacked work uses the separate
`ORG_SWEEP_STACKED_REVIEW_DISPATCH_LIMIT` (default `1`) because stacked PRs do
not receive injected required workflows. The walk order came from a single `gh api
/orgs/{org}/repos` call with no explicit sort, so it was effectively fixed
across ticks. A repository early in that fixed order always consumed the
single available ordinary dispatch, so every later repository's ready, all-green,
zero-open-thread pull requests never reached the OpenCode review dispatch
through the sweep fallback path — indefinitely, not just for one tick.

`ContextualWisdomLab/.github#1219` recorded this with direct evidence from a
RankWeave sweep run: PRs #36, #40, and #41 all reported `review dispatch limit
reached` in the same run where the ordinary org-wide budget was already `1/1`
before RankWeave's own turn. The same ordinary budget could also leave stacked
PRs at `OpenCode review absent` even though they are the only path to their
required review.

## Decision

Rotate the sweep's repository walk order by a rotation index before applying
the unchanged organization-wide budgets. `rotation_offset = rotation_index %
repository_count`; the walk starts at that offset and wraps. This spreads each
bounded dispatch budget across repositories over successive sweep executions;
the stacked budget is tracked independently so normal default-base work cannot
starve stacked review dispatches.

`ORG_SWEEP_ROTATION_INDEX`'s primary source is a persistent
`ORG_SWEEP_ROTATION_COUNTER` repository variable on `ContextualWisdomLab/.github`
itself, incremented by exactly one at the start of every actual
`org-queue-sweep` execution (`gh api .../actions/variables/ORG_SWEEP_ROTATION_COUNTER
-X PATCH`, falling back to `-X POST` to create it on the first run). It falls
back to a wall-clock tick (`$(date -u +%s) / 900`) only if the counter
read/write itself is unavailable (permissions, transient API failure) — a
fairness mechanism must never fail the sweep's much more important
review-dispatch/merge work. `ORG_SWEEP_ROTATION_INDEX` is left unset in the
job's `env:` block in production so the sweep step computes it; tests inject
it directly, or stub `gh` on `PATH`, for determinism.

This design went through two prior, each independently review-flagged
iterations, both instructive about why neither alone is sufficient:

1. **`github.run_number`** (original `#1220`). Rejected because `run_number`
   increments on every trigger of this workflow — push, `pull_request_target`,
   `pull_request_review`, `workflow_run` — not only the `*/15` sweep schedule,
   so it cannot give the "bounded by `repository_count` executions" guarantee
   a rotation is meant to provide (Devin review finding on `#1220`; that
   version merged before the correction landed, since the review comment was
   informational rather than a blocking request-changes).
2. **Wall-clock tick alone** (`#1223`, first revision). Rejected as the sole
   source because `org-queue-sweep` is single-flight/non-cancelling with up to
   a 60-minute `timeout-minutes`: a delayed or backlogged real execution can
   let more than one 900-second window elapse before the next real run, and if
   that elapsed-tick gap happens to be an exact multiple of `repository_count`
   the modulo offset repeats — reintroducing the exact starvation `#1220`
   fixed for a different reason (CodeRabbit review finding on `#1223`).

A persistent per-execution counter is immune to both: it is untouched by
non-sweep triggers of this workflow (unlike `run_number`) and advances by
exactly one every time the sweep body actually runs, regardless of how much
wall-clock time a slow prior run consumed (unlike a wall-clock tick alone).

The budget-sizing question in #1219 (is `1` a deliberate LLM-provider
cost/rate ceiling, or an unconsidered default?) is explicitly **not**
resolved here. Raising the shared number without that context risks the
exact provider budget/rate-limit incident already documented in
`PR_GOVERNANCE_AUDIT.md` (2026-07-13 KST GitHub Models org budget cap
starvation). Rotation fixes starvation-by-fixed-order without touching that
open cost question. The stacked queue has the same explicit cost/rate control
through `vars.ORG_SWEEP_STACKED_REVIEW_DISPATCH_LIMIT`; whoever has
organization Billing/Budgets visibility can tune either limit independently.

## Consequences

- Every repository with ready work eventually reaches the front of the walk
  order and receives its queue's bounded dispatch, bounded by
  `repository_count` actual sweep executions in the worst case, instead of
  never.
- Each queue remains bounded per tick. The default configuration permits one
  ordinary and one stacked review dispatch, so provider call volume increases
  from one to two only when both queues are eligible.
- `rotation_offset` is logged (`Sweeping N repositories starting at rotation
  offset O (rotation tick T).`) so a specific execution's walk order is
  reconstructable from the run log alone.
- `ORG_SWEEP_ROTATION_INDEX` follows the same fail-closed numeric-validation
  pattern as the sibling `ORG_SWEEP_*_LIMIT` variables (reject non-digit
  input before it reaches arithmetic context, where an unguarded `set -e`
  would not trap the error), applied after the persistent-counter/wall-clock
  default fills it in when the environment does not already provide one.
- A degraded run (counter unavailable) still rotates by wall-clock time
  rather than reverting to the original fixed order; it only loses the
  strict per-execution guarantee for that one run, logged as a
  `::warning::`.
- A stacked PR whose OpenCode evidence is absent or stale is logged as `wait`
  when the shared review-dispatch budget is exhausted, preserving the real
  blocker instead of misreporting it as a no-action `skip`.
- Targeted scheduler dispatch validates the PR's live base branch but passes
  the target repository's default branch to the scheduler. Passing the PR base
  itself would make a stacked PR appear default-base and bypass its central
  OpenCode dispatch path.

## Shared-installation rate-limit boundary

The scheduler and several sibling workflows use installation access tokens
from one GitHub App installation. GitHub applies one primary request bucket to
that installation: at least 5,000 requests per hour, scaling by organization
users and repositories to at most 12,500 requests per hour outside GitHub
Enterprise Cloud. In a 30-run scheduler sample, 5 runs failed with the same
primary-limit diagnostic across more than 15 hours; 4 failed on the first of
66 repositories within 5 to 18 seconds. That aggregate timing evidence is
consistent with shared-bucket contention rather than one target repository
consuming the budget.

REST and GraphQL reads therefore make at most four attempts. Primary-limit
failures use the reset epoch reported by `GET /rate_limit`, capped at 60
seconds for each retry interval; other transient failures retain the shorter
exponential backoff. GitHub documents that the rate-limit endpoint does not
consume the primary REST budget, although it can consume secondary capacity,
and recommends waiting until the reported reset rather than continuing to
send requests after a primary limit is exhausted.

If bounded retries still end with `API rate limit exceeded`, the workflow
records the current repository as deferred and stops the organization loop.
The bucket is shared, so visiting the remaining repositories cannot produce
new authoritative state before reset; it would only repeat up to three
one-minute waits per repository and add queue-hygiene requests that GitHub
explicitly advises against. The capacity condition remains non-fatal and the
rotating next execution retries unfinished work. Secondary-limit diagnostics
remain outside this narrow classifier because GitHub gives them a different
retry contract and may provide `Retry-After` instead of a primary reset epoch.

## Verification

- `tests/test_required_workflow_queue_contract.py::test_org_queue_sweep_rotation_offset_is_deterministic_and_reorders_targets`
  executes the extracted rotation snippet directly through `bash -euo
  pipefail` for several rotation indices and asserts the resulting order is a
  full permutation of the input, not a subset.
- `test_org_queue_sweep_rotation_offset_is_safe_with_no_targets` covers the
  zero-repository edge case.
- `test_org_queue_sweep_rotation_index_uses_persistent_counter_when_available`
  stubs `gh` on `PATH` to simulate a successful read-increment-write and
  confirms the counter advances by exactly one.
- `test_org_queue_sweep_rotation_index_creates_counter_on_first_run` confirms
  the POST-create fallback when the PATCH target does not exist yet.
- `test_org_queue_sweep_rotation_index_falls_back_to_wall_clock` confirms the
  wall-clock degraded path and its `::warning::` when the counter is entirely
  unavailable.
- `test_org_queue_sweep_rotation_index_override_is_preserved` and
  `test_org_queue_sweep_rotation_index_rejects_malformed_override` cover the
  test-injection and fail-closed-validation paths.
- `test_org_queue_sweep_documents_rotation_leverage_and_validates_input`
  locks the `#1219` cross-reference, confirms `github.run_number` is not
  reintroduced as the source, confirms the shared budget constant itself
  is untouched, and confirms the ordinary budget remains independently
  configurable from the stacked budget.
- `test_org_queue_sweep_treats_rate_limited_repositories_as_non_fatal`
  confirms the primary-limit diagnostic is deferred without becoming a generic
  hard failure and that the repository loop stops immediately after recording
  the exhausted shared bucket.
- `actionlint` (with `shellcheck` on `PATH`) reports no findings against the
  modified workflow.

## References

`ContextualWisdomLab/.github#1219` — original starvation report with sweep
run evidence.
`ContextualWisdomLab/.github#1220` — original rotation fix; `run_number` vs.
per-execution-guarantee review discussion.
`ContextualWisdomLab/.github#1223` — wall-clock correction, then the
persistent-counter correction this document and the current workflow source
reflect.

GitHub, Inc. (n.d.-a). *Best practices for creating a GitHub App*. GitHub
Docs. Retrieved August 24, 2026, from
https://docs.github.com/en/apps/creating-github-apps/about-creating-github-apps/best-practices-for-creating-a-github-app

GitHub, Inc. (n.d.-b). *Rate limits for GitHub Apps*. GitHub Docs. Retrieved
August 24, 2026, from
https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/rate-limits-for-github-apps

GitHub, Inc. (n.d.-c). *Rate limits for the REST API*. GitHub Docs. Retrieved
August 24, 2026, from
https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api
