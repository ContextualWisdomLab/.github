# ADR-0021: Consolidate the 18 hourly review-repair callers into one file

- **Status:** Accepted
- **Date:** 2026-09-02
- **Scope:** ContextualWisdomLab/.github `.github/workflows/` hourly review-repair trigger/dispatch layer

## Context

18 near-identical files (`<repo>-hourly-review-repair.yml`) each existed
solely to give one product repository its own hourly `schedule` trigger and
call the shared, product-neutral `pr-review-fix-scheduler.yml` with that
repository's `target_repository` / `base_branch` / `retry_hours`. Every file
differed from every other one only in `name:`, one `cron:` minute (and a
staggering-rationale comment), the `concurrency.group` name (and a
cancellation-rationale comment), and those three `with:` values;
`max_prs`/`max_dispatches` were uniform. Adding, auditing, or re-staggering
a caller required editing (or copy-pasting) one of 18 files.

The repository owner requested consolidating this pattern into a single
file, citing hosted run
`ContextualWisdomLab/.github/actions/runs/33524178483/job/99910668839` (a
"Governance Risk Compliance Hourly Review Repair" run) as an example of the
duplication, and specifically identifying that GitHub Actions' own native
syntax already supports this without a new abstraction layer.
`docs/doctoring/hourly-review-repair-single-file-consolidation.md` records
the full before/after mapping, verification, and every non-uniform field
found while auditing.

## Decision

1. One file, `.github/workflows/hourly-review-repair.yml`, replaces all 18.
   Its `on.schedule` list carries all 17 distinct cron minutes the 18 files
   used, each keeping its original file's staggering-rationale comment.
2. A `resolve-target` job reads `github.event.schedule` in a `run:` step and
   looks it up in a `case`/`esac` table -- a small, readable lookup table,
   not a new configuration format -- producing a JSON array of
   `{name, target_repository, base_branch, retry_hours, concurrency_group}`
   via `GITHUB_OUTPUT`. Every deleted file's concurrency-cancellation
   rationale comment survives as a comment on its `case` branch.
3. A `dispatch-review-repair` job (`needs: resolve-target`) fans out over
   that array with `strategy.matrix.include` and calls
   `pr-review-fix-scheduler.yml` once per resolved target, forwarding the
   two secrets exactly as the 18 originals did.
4. `concurrency.group` is `${{ matrix.concurrency_group }}` -- each
   repository's own former group name, reused verbatim -- so the 18 (17
   distinct-minute) schedules keep the same independent, non-cancelling
   isolation the 18 separate files gave them. A job-level `concurrency:`
   expression may reference `matrix.*` because the matrix is resolved
   before the job starts.
5. `fast-mlsirm` and `metering-billing-platform` had each independently
   chosen `cron: "49 * * * *"` in their original files -- an unnoticed
   collision, not a deliberate shared heartbeat. Rather than rely on
   GitHub's undocumented behavior for two textually-identical `on.schedule`
   entries in one file, the consolidated file has exactly one `"49 * * * *"`
   entry whose lookup resolves to a two-element array; the matrix dispatches
   both. Each repository still gets exactly one dispatch attempt at minute
   49 of every hour.
6. `resolve_unreviewed_conflicts: true` is passed explicitly and uniformly
   to every target. The reusable workflow's own input already defaults to
   `true`, so this is behaviorally identical to the prior state (17 files
   omitted it, one set it explicitly) and avoids needing to conditionally
   omit a `with:` key per matrix element, which reusable-workflow calls do
   not support.
7. Job-level `permissions:` (`contents: read`, `id-token: write`) is granted
   uniformly to every target. `clearfolio-hourly-review-repair.yml` was the
   sole one of the 18 originals that omitted this override, so it alone
   never actually granted the reusable scheduler `id-token: write` -- a
   latent gap closed by this uniform grant. `pr-review-fix-scheduler.yml`'s
   own `permissions:` block is unchanged; this widens only one caller's own
   job permissions to match its 17 siblings.
8. `pr-review-fix-scheduler.yml` is not modified. It remains product-neutral
   per this repository's existing convention (AGENTS.md / CLAUDE.md:
   "Product hourly callers stay thin. Do not hard-code ... into
   pr-review-fix-scheduler.yml"); only the trigger/dispatch layer above it
   is consolidated.
9. `.github/workflows/hourly-nvidia-nim-review-repair.yml`'s path-filter
   lists (a separate, pre-existing focused quality-gate workflow) are
   updated to track the one consolidated file and its one consolidated test
   file instead of the 14 individual entries they previously tracked.
10. 13 dedicated per-repository test files
    (`tests/test_<repo>_hourly_review_caller.py`), each pinning only that
    one repository's now-deleted caller file, are replaced by one file,
    `tests/test_hourly_review_repair_callers.py`, which asserts the full
    18-repository mapping by extracting and executing the `resolve-target`
    lookup script for every schedule. Test files with additional,
    non-caller-shape logic (`tests/test_github_hourly_conflict_repair.py`,
    `tests/test_hourly_scheduler_runtime_budget.py`,
    `tests/test_pr_review_fix_hourly_contract.py`,
    `tests/test_pr_review_autofix_nvidia_nim_contract.py`) are kept and
    updated in place rather than deleted.
11. The 14 per-repository doctoring records for the individual callers are
    kept as historical decision records rather than merged, since their
    prose (unlike the deleted YAML) was never byte-for-byte duplicated
    across repositories; only the one doc that named its own deleted
    filename (`docs/doctoring/clearfolio-hourly-review-caller.md`) is
    corrected to point at the consolidated file.

## Consequences

- Adding, removing, or re-staggering a product's hourly heartbeat is a
  one-file, one-`case`-branch edit instead of a new copy-pasted file.
- The full minute-to-repository mapping, and every staggering/cancellation
  rationale, is visible in one place rather than requiring 18 separate file
  reads to audit for a collision -- which is how the pre-existing minute-49
  collision between fast-mlsirm and metering-billing-platform surfaced
  during this consolidation's audit.
- Concurrency isolation depends on `matrix.*` being available to job-level
  `concurrency:` expressions, a documented but less commonly exercised
  GitHub Actions capability; `tests/test_hourly_review_repair_callers.py`
  and `actionlint` both verify the consolidated file directly rather than
  assuming this.
- The consolidated file is longer (comments included) than any single one
  of the 18 originals, trading per-repository file separation for one file
  whose structure (schedule list, then lookup table, then matrix dispatch)
  is uniform and mechanically auditable.
- Clearfolio's job-level OIDC permission gap is closed as a side effect of
  uniform matrix permissions; this is a narrow, intentional, and
  behaviorally inert widening (Clearfolio's forwarded PAT secrets already
  kept its mutation-credential check passing), not an unreviewed permission
  escalation.

## Rejected alternatives

- **Duplicate `cron: "49 * * * *"` twice in `on.schedule` and let each
  physical trigger resolve to its one repository.** Rejected because
  GitHub's behavior for two textually-identical schedule entries in one
  workflow (one physical run, or two) is not documented; relying on it
  would make dispatch correctness depend on unspecified platform behavior
  instead of one entry with a two-element lookup result.
- **Silently re-stagger `metering-billing-platform` off minute 49 during
  this consolidation.** Rejected as out of scope for a pure consolidation:
  changing effective dispatch timing is a separate decision from replacing
  18 files with one, and is called out explicitly instead, for the owner or
  a follow-up change to decide.
- **One shared `concurrency.group` for the whole consolidated workflow.**
  Rejected because the 18 originals were deliberately independent (a
  Governance Risk Compliance heartbeat must not queue behind, or cancel, an
  unrelated Clearfolio run); a dynamic per-target group was required to
  preserve that.
- **Merge the 14 per-repository doctoring records into one document.**
  Rejected because their content is repository-specific decision history,
  not duplicated boilerplate; merging would blur which repository a given
  security or activation rationale applies to.
- **Delete the 13 dedicated per-repository test files outright without a
  replacement.** Rejected: their assertions (exact cron, target repository,
  base branch, retry floor, permissions, secrets) are real correctness
  properties for production scheduling infrastructure and are preserved,
  consolidated into one parametrized module instead of dropped.
