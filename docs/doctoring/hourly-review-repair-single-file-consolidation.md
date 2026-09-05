# Hourly review-repair single-file consolidation

## Decision

The 18 near-identical per-repository hourly review-repair caller files
(`accounting-information-platform-hourly-review-repair.yml`,
`afipc-hourly-review-repair.yml`, `bandscope-hourly-review-repair.yml`,
`clearfolio-hourly-review-repair.yml`,
`contextual-orchestrator-hourly-review-repair.yml`,
`disksage-hourly-review-repair.yml`, `fast-mlsirm-hourly-review-repair.yml`,
`github-hourly-review-repair.yml`,
`governance-risk-compliance-hourly-review-repair.yml`,
`inkspan-hourly-review-repair.yml`, `lineageweave-hourly-review-repair.yml`,
`metering-billing-platform-hourly-review-repair.yml`,
`nonnest2-hourly-review-repair.yml`, `orgmetra-hourly-review-repair.yml`,
`originweave-hourly-review-repair.yml`,
`psychometrics-commons-hourly-review-repair.yml`,
`quarantine-sandbox-hourly-review-repair.yml`, and
`semantic-data-portal-hourly-review-repair.yml`) are replaced by one file,
`.github/workflows/hourly-review-repair.yml`, at the request of the
repository owner (2026-09-02, citing hosted run
`ContextualWisdomLab/.github/actions/runs/33524178483/job/99910668839` of the
"Governance Risk Compliance Hourly Review Repair" workflow): "이런 Workflow는
단일 파일로 통합하라" (consolidate workflows like this into a single file).
See also [ADR-0021](../adr/0021-hourly-review-repair-single-file-consolidation.md).

Each deleted file differed from every other one only in `name:`, one
`cron:` minute (and its staggering-rationale comment), the
`concurrency.group` name (and its one-line cancellation-rationale comment),
and the `target_repository` / `base_branch` / `retry_hours` values passed to
`pr-review-fix-scheduler.yml`. `max_prs` ("50") and `max_dispatches` ("1")
were uniform across all 18. That reusable engine already followed this
repository's own stated convention (AGENTS.md / CLAUDE.md: "Product hourly
callers stay thin. Do not hard-code ... into pr-review-fix-scheduler.yml"),
so it is unchanged; only the trigger/dispatch layer above it is
consolidated.

## Mechanism

`.github/workflows/hourly-review-repair.yml` uses GitHub Actions' own native
syntax controls, as requested, rather than a new abstraction:

1. A single `on.schedule` list carries all 17 distinct cron minutes the 18
   files used (one minute, `49 * * * *`, was shared by two files -- see
   "The minute-49 collision" below).
2. A `resolve-target` job reads `github.event.schedule` -- the exact cron
   expression GitHub sets on the triggering event (GitHub, n.d.-b) -- in a
   `run:` step, and looks it up in a `case`/`esac` table that sets a JSON
   `targets` array via `GITHUB_OUTPUT`. Every deleted file's staggering and
   concurrency-cancellation rationale comments survive as comments on the
   corresponding `on.schedule` entry and `case` branch.
3. A `dispatch-review-repair` job (`needs: resolve-target`) fans out over
   that JSON array with `strategy.matrix.include`, then calls
   `pr-review-fix-scheduler.yml` once per resolved target with
   `target_repository` / `base_branch` / `retry_hours` from `matrix.*` and
   the two static uniform values (`max_prs: "50"`, `max_dispatches: "1"`).

### Per-repository concurrency stays isolated

All 18 original files used SEPARATE, independent `concurrency.group` values
(never one shared group) with `cancel-in-progress: false`, so a later
heartbeat never cancels one repository's in-flight RCA. The consolidated
job's `concurrency:` is `group: ${{ matrix.concurrency_group }}`, reusing
each repository's exact former group name (e.g.
`afipc-hourly-review-repair`). A job-level `concurrency:` expression may
reference `${{ matrix.* }}` because the matrix is resolved before the job
starts (GitHub, n.d.-a), so this reproduces the 18 independent leases inside
one job definition instead of one group shared across every schedule --
verified directly with `actionlint` and with the extracted lookup script
executed for every one of the 18 original repositories (see Verification).

### The minute-49 collision

Auditing the 18 originals for this consolidation found that
`fast-mlsirm-hourly-review-repair.yml` and
`metering-billing-platform-hourly-review-repair.yml` had each
independently chosen `cron: "49 * * * *"` -- an unnoticed collision, not a
deliberate shared heartbeat (their staggering comments both read "Minute 49
avoids minute-zero pressure and the existing product callers" with no
mention of each other). Under the original 18-file design this was
harmless: each file is its own workflow, so GitHub triggered two
independent workflow runs at `:49`, one per file, each dispatching its own
repository once.

A consolidated single file cannot rely on two textually-identical
`on.schedule` entries to reproduce that: GitHub Actions' behavior for
duplicate identical cron strings within one workflow's schedule list is not
documented, so this consolidation does not depend on it. Instead there is
exactly **one** `"49 * * * *"` entry in `on.schedule`, and the
`resolve-target` lookup for that one schedule returns a two-element JSON
array (fast-mlsirm, then metering-billing-platform); `dispatch-review-repair`'s
matrix fans out over both. Each of the two repositories still gets exactly
one dispatch attempt at minute 49 of every hour -- the same net cadence as
before -- through a mechanism whose correctness does not depend on
unspecified GitHub scheduling behavior.

## Other non-uniform fields found while auditing

- `retry_hours` was **not** uniform: `clearfolio`, `github`, and
  `metering-billing-platform` used `"1"`; the other 15 used `"2"`. Preserved
  exactly per repository in the lookup table.
- `base_branch` was **not** uniform: `develop` (6), `main` (9), `master`
  (2), and `LineageWeave`'s literal `"*"` (1). Preserved exactly.
- `resolve_unreviewed_conflicts: true` appeared explicitly only in
  `github-hourly-review-repair.yml`; the other 17 omitted it. The reusable
  workflow's own input already defaults to `true`
  (`pr-review-fix-scheduler.yml`), so the consolidated file sets it
  explicitly and uniformly for all 18 targets -- behaviorally identical to
  the prior mixed omitted/explicit state, and simpler than conditionally
  omitting a `with:` key per matrix element (which reusable-workflow
  `with:` blocks do not support).
- Job-level `permissions:` (`contents: read`, `id-token: write`) was present
  in 17 of the 18 files. `clearfolio-hourly-review-repair.yml` was the sole
  exception: it had no job-level `permissions:` override, so its job
  inherited only the workflow-level `contents: read` and never actually
  granted the reusable scheduler `id-token: write` for Clearfolio's calls --
  a latent, silent gap (the scheduler's OIDC token-exchange step could not
  mint a token for that one caller; its established
  `PR_REVIEW_MERGE_TOKEN` / `OPENCODE_APPROVE_TOKEN` secrets kept the
  mutation-credential check passing regardless, so this was not
  externally visible). The consolidated file grants
  `contents: read` / `id-token: write` uniformly to every matrix target,
  matching the other 17 and closing that gap. This is a deliberate,
  narrow widening of one caller's own job permissions -- not of
  `pr-review-fix-scheduler.yml`, whose own `permissions:` block is
  unchanged -- and does not observably change dispatch behavior under the
  secrets already provisioned for Clearfolio.
- `max_prs` (`"50"`) and `max_dispatches` (`"1"`) were uniform across all 18
  files; the consolidated file keeps them as static `with:` values rather
  than carrying them through the per-target lookup table, since there is
  nothing to look up.

## Verification

`tests/test_hourly_review_repair_callers.py` extracts the `resolve-target`
job's `run:` script (the same extraction pattern already used in
`tests/test_pr_review_fix_hourly_contract.py`) and executes it as a real
subprocess for each of the 17 schedules, asserting the exact JSON target(s)
against every field the 18 deleted files passed to
`pr-review-fix-scheduler.yml`; an 18th case (the minute-49 pair) is asserted
within the `"49 * * * *"` schedule. It also asserts: the 18 former files no
longer exist; the dynamic `concurrency.group` expression and non-cancelling
posture; the matrix/`needs` wiring; the narrow job permissions; explicit
secrets with no `secrets: inherit`; and that no consolidated target
repository is hard-coded into `pr-review-fix-scheduler.yml`. `actionlint`
passes on the consolidated file. `tests/test_pr_review_fix_hourly_contract.py`,
`tests/test_hourly_scheduler_runtime_budget.py`,
`tests/test_github_hourly_conflict_repair.py`, and
`tests/test_pr_review_autofix_nvidia_nim_contract.py` -- which previously
used Clearfolio, DiskSage, or the central `.github` self-caller as a
representative example caller -- were updated to read the consolidated file
instead of a deleted one, with per-repository flat-string assertions
(`target_repository: ...`, `base_branch: ...`, `retry_hours: ...`) replaced
by the equivalent JSON-literal check against that repository's row in the
lookup table.

## Non-goals

The 14 per-repository doctoring records this consolidation's caller files
previously had (e.g. `docs/doctoring/originweave-hourly-review-caller.md`,
`docs/doctoring/nonnest2-hourly-review-caller.md`) are historical decision
records with their own repository-specific security and activation-boundary
narrative; they are kept as-is rather than merged into this document, since
merging would blur which repository a given rationale applies to without
reducing any real duplication (their prose, unlike the deleted YAML, was
never byte-for-byte identical across repositories). Only the one doc that
named its own now-deleted filename
(`docs/doctoring/clearfolio-hourly-review-caller.md`) was corrected to point
at `hourly-review-repair.yml`.

`docs/product-technical-gap-baseline.md` is a live per-PR gap-tracking
ledger, not a description of current architecture; this internal-only
consolidation does not add a new tracked product gap, so no row was added
there.

## 2026-09-03 follow-up: `max_prs` raised from 50 to 200

The 18 originals were uniform at `max_prs: "50"` only because none of them
had yet picked up the fix `ContextualWisdomLab/.github#1397` proposed for
BandScope specifically (root cause: BandScope's own queue had already
reached 136 open PRs, so an oldest-first scan capped at 50 never reached
current non-draft work). That PR never merged before this consolidation
deleted its target file (`bandscope-hourly-review-repair.yml`) out from
under it, leaving `#1397` obsolete and the underlying 50-PR cap live and
unfixed for all 20 targets in the consolidated file.

Confirmed independently live for at least one target: `ContextualWisdomLab/.github`
itself (the `21 * * * *` row) had 117 open PRs as of 2026-09-03, so its own
oldest-first self-scan was already silently capped well short of its queue.
`max_prs` in `.github/workflows/hourly-review-repair.yml` is raised to
`"200"` for all 20 targets uniformly (still a single static `with:` value,
not a per-target one -- there remains no evidence any one target needs a
*different* bound from any other, only that 50 was too low for all of
them). `tests/test_hourly_review_repair_callers.py` and the two example
blocks in `docs/automation/hourly-review-repair.md` were updated to match.

The 200-PR value is a discovery ceiling, not a per-run deep-inspection budget.
The shared scheduler normalizes the hourly run number over the number of actual
50-PR windows, so repositories with fewer than 200 open PRs do not rotate into
empty slots. It hydrates review, check, mergeability, and comment evidence only
for the selected window. Once `max_dispatches: "1"` is consumed, the loop stops
without inspecting later PRs. This preserves access to PRs beyond the former
oldest-first 50-item ceiling without multiplying each hourly run's expensive
inspection work fourfold.

## References (APA 7th edition)

GitHub, Inc. (n.d.-a). *Using concurrency*. GitHub Docs. Retrieved
2026-09-02, from
https://docs.github.com/en/actions/using-jobs/using-concurrency

GitHub, Inc. (n.d.-b). *Events that trigger workflows: schedule*. GitHub
Docs. Retrieved 2026-09-02, from
https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule
