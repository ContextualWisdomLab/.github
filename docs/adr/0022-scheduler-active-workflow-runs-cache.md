# ADR-0022: Cache `active_workflow_runs` per scheduler invocation; stay Python

- **Status:** Accepted
- **Date:** 2026-09-02
- **Scope:** ContextualWisdomLab/.github `scripts/ci/pr_review_merge_scheduler.py`
  (the `scan-pr-queue` job's PR-queue sweep)

## Context

`pr_review_merge_scheduler.py` is 5,428 lines and is invoked by `scan-pr-queue`
with `--max-prs "$MAX_PRS"` (workflow_call default `"100"`;
`.github/workflows/pr-review-merge-scheduler.yml`). Its call path is
`main()` → `fetch_open_prs()` (paginated GraphQL, one repository only --
`fetch_open_prs(repo, max_prs)` takes a single `repo` string, never a set) →
`enrich_rest_mergeable_states()` (already a bounded `ThreadPoolExecutor`) →
a sequential `for pr in prs: inspect_pr(pr)`. That final loop is correctly
sequential by design, not a naive-parallelize target: `inspect_pr` consumes
stateful, order-dependent mutation-budget counters
(`review_dispatch_limit`/`branch_update_limit`, default `1`) that must be
spent in PR order across the whole sweep.

`concurrent.futures.ThreadPoolExecutor` already exists at four sites --
`fetch_open_prs_rest` (REST PR-list enrichment), `enrich_rest_mergeable_states`
(per-PR mergeable-state/compare-freshness enrichment),
`resolve_outdated_review_threads` (outdated-thread resolution), and
`force_cancel_workflow_runs` (batched run cancellation) -- so the "naive
sequential loop of independent reads" pattern this investigation went looking
for is already fixed everywhere it occurs for bulk reads.

The real remaining inefficiency is different in kind: `inspect_pr()` calls
`cancel_stale_pr_runs(repo, pr, dry_run=dry_run)` **unconditionally** for
every non-draft PR, before any eligibility or budget gate. Non-dry-run, that
calls `active_workflow_runs(repo, ("queued", "in_progress"))` -- two
sequential, repository-wide, paginated `gh api repos/{repo}/actions/runs
--paginate --slurp` calls, unfiltered by PR and filtered client-side
afterward. Because the scheduler only ever targets the one repository passed
on its command line, this exact fetch is reissued from scratch for every PR
in the loop, and several other call sites (`active_review_run_refs`,
`dispatch_strix_evidence`'s busy check) ask the identical unfiltered question
again within the same invocation. There was no caching anywhere in the file
(`functools`/`lru_cache` was not even imported). Worst case at the default
`MAX_PRS=100` with mostly non-draft PRs: well over a hundred redundant
sequential `gh api` round-trips per scheduler invocation, each potentially
multi-page, for data that does not change unless the scheduler's own actions
change it.

No prior ADR discusses this file's language choice (a repository-wide grep
across `docs/adr/*.md` and `docs/*.md` for the scheduler, scheduler
performance, GIL, or Python/Rust turned up nothing). `scripts/ci/` is 50
files / 27,115 lines, 100% Python, with zero `.rs` files or `Cargo.toml`
anywhere in the repository -- Python-for-CI-glue is this repository's
existing, uniform convention.
`docs/product-technical-gap-baseline.md` §2.2 (Compute plane) scopes
mandatory Rust to math-science/psychometrics computation and CPU-bound hot
paths, and explicitly permits Python/JS for "orchestration/API adapter"
roles -- exactly what this scheduler is: `gh` CLI / GraphQL+REST glue with no
CPU-bound core. `docs/product-goal-directive.md` §6 separately carries a
narrower, already-authorized escape hatch for the concern this investigation
was chartered to check: if a Python web server hits GIL problems, support
multithreading or move to Python 3.14 -- not "rewrite in Rust." The measured
bottleneck here is redundant sequential I/O wait, not CPU/GIL-bound
computation; CPython threads already release the GIL during subprocess and
network I/O, so a Rust rewrite would not remove these round-trips -- only
avoiding the redundant reads does.

## Decision

1. **Cache, not a thread pool, for this hot path.** `active_workflow_runs`
   now memoizes its result in a module-level dict keyed on the full call
   shape `(repo, tuple(statuses), event, created, head_sha)`. This is a
   caching fix in the same spirit as "stop repeating a blocking call that
   could be done once" -- and is strictly better than thread-pooling the
   redundant calls would have been, since caching also cuts GitHub API
   rate-limit consumption instead of only wall clock.
2. **Cache lifetime is exactly one scheduler invocation.**
   `reset_active_workflow_runs_cache()` clears the dict; `main()` calls it
   once at the top of every run, so no state survives across separate
   invocations sharing a process (relevant to tests, and to any future
   long-lived caller).
3. **Explicit invalidation on every mutation, not a blind full-invocation
   cache.** A blind cache is unsafe here: `dispatch_strix_evidence`'s
   `busy_refs` check reads `active_workflow_runs` again immediately after
   `force_cancel_workflow_run_refs` cancels stale runs for the same
   repository, and a later PR's own `cancel_stale_pr_runs` can run after an
   earlier PR's dispatch created a new run in the same repository within the
   same invocation. Serving a pre-mutation snapshot to either of those reads
   would let a just-cancelled run still look "busy," or let a same-invocation
   dispatch go undetected by the repository-wide single-concurrency dispatch
   guard. `reset_active_workflow_runs_cache()` is therefore called
   immediately after the four places that change GitHub Actions run state:
   `force_cancel_workflow_runs` (after a cancel), `rerun_actions_job` (after
   a rerun), and `dispatch_opencode_review` / `dispatch_strix_evidence`
   (after their dispatch `POST`) -- the complete set found by grepping for
   every `force-cancel`, `/rerun`, and `/dispatches` call in the file.
4. **The four existing `ThreadPoolExecutor` sites and the sequential per-PR
   mutation-budget loop are untouched.** They already convert independent,
   read-only bulk lookups to bounded concurrency where that was safe; nothing
   with ordering dependencies (merges, branch updates, review dispatches) was
   touched, per this organization's standing rule against parallelizing
   anything with side effects or ordering dependencies without strong
   evidence.
5. **No Rust rewrite.** Per the gap-baseline and goal-directive citations in
   Context above: this script's role and evidence do not meet the bar either
   document sets for mandatory or motivated Rust.

## Consequences

- In the common case -- most PRs carry no stale old-head runs, so
  `force_cancel_workflow_runs` is never called with a non-empty `run_ids` and
  never invalidates -- the redundant unfiltered `(repo, ("queued",
  "in_progress"))` fetches collapse from up to two per PR to two total for
  the whole sweep, matching the investigation's own estimate.
- In the pathological case -- every single PR has a stale run to cancel, so
  every iteration invalidates -- the cache provides no savings, but also no
  regression: behavior degrades gracefully back to exactly today's
  call-per-PR pattern, never worse.
- `tests/test_pr_review_merge_scheduler.py`: two existing call-index
  assertions (`test_actions_call_gh_with_expected_arguments`,
  `test_actions_control_uses_workflow_token_when_mutation_token_is_app`)
  shifted because a busy-check read that used to issue two fresh `gh api`
  calls is now a cache hit, and were updated (with an inline comment
  explaining the shift) rather than the underlying call counts contorted to
  preserve the old indices. Four new tests were added:
  `test_active_workflow_runs_caches_repeated_identical_calls` (identical
  results, one underlying fetch for many repeated calls),
  `test_active_workflow_runs_cache_is_faster_than_repeated_fetches` (a
  `time.sleep`-delayed fake `gh` proves a genuine wall-clock improvement, not
  just fewer assertions), `test_active_workflow_runs_cache_keys_on_full_call_shape`
  (distinct repo/statuses/event/created/head_sha combinations never share an
  entry), and
  `test_force_cancel_workflow_runs_invalidates_active_workflow_runs_cache`
  (a cancellation is never masked by a stale pre-cancellation snapshot). A
  new autouse fixture clears the cache between every test so the new
  module-global state cannot leak across the file's ~250 other tests.
- `coverage run -m pytest tests && coverage report` remains 100% on
  `scripts/ci` (`pr_review_merge_scheduler.py`: 2,208 statements / 940
  branches, zero missed); `interrogate` remains 100%.

## Rejected alternatives

- **A blind, never-invalidated full-invocation cache.** Rejected as unsafe:
  it would let `dispatch_strix_evidence`'s busy check believe a run this same
  invocation just cancelled is still occupying the repository's dispatch
  capacity, or let one PR's dispatch go invisible to a later PR's read in the
  same repository within the same run -- silently breaking the
  "repository busy" single-concurrency dispatch guard the code depends on.
- **`functools.lru_cache` decorating `active_workflow_runs` directly.**
  Rejected: `lru_cache` hashes its raw arguments before the function body
  runs, so a caller passing `statuses` as a list (the parameter's declared
  type is `Sequence[str]`, not specifically `tuple`) would raise
  `TypeError: unhashable type` where today's implementation tolerates any
  iterable. The manual cache normalizes to `tuple(statuses)` for the key
  while still iterating the caller's original argument for the actual `gh`
  calls.
- **Converting the unconditional `cancel_stale_pr_runs` call, or the per-PR
  loop generally, into a `ThreadPoolExecutor` read-parallelization.**
  Rejected: the loop is correctly sequential (the mutation-budget counters
  must be consumed in PR order), and the actual inefficiency is a *duplicate*
  read of identical data across iterations, not independent reads that could
  usefully run concurrently. Caching is strictly better for this specific
  shape of waste.
- **Rewrite this scheduler, or just its GitHub-API layer, in Rust.**
  Rejected under `docs/product-technical-gap-baseline.md` §2.2's scoping
  (mandatory Rust is reserved for CPU-bound math-science/psychometrics
  compute; Python/JS is explicitly permitted for orchestration/API-adapter
  roles) and `docs/product-goal-directive.md` §6's narrower, already-adopted
  GIL escape hatch (multithreading or Python 3.14, not a rewrite). The
  measured bottleneck is network I/O wait, which CPython already handles by
  releasing the GIL during subprocess/socket calls; a Rust rewrite would not
  remove the round-trips themselves, only the caching fix does. If a future
  profile shows a genuinely CPU-bound hot path inside this file (none is
  evidenced today), the removal/migration condition for revisiting this
  decision is: a profiler-attributed CPU-bound function, not I/O-bound `gh`
  invocation latency, consuming a measurable share of scheduler wall clock.
