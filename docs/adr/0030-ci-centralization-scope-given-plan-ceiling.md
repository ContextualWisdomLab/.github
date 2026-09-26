# 0030. CI centralization: what it can and cannot fix, given the plan-level concurrency ceiling

## Status

Proposed (informational/scoping ADR — no workflow behavior changes yet)

## Context

`docs/ci-baseline-20260916.md` measured 24h of Actions runs across all 79 org repos (9,353 runs,
400 (repo, workflow, trigger) groups) to quantify PR queue stalls, starting from the observed
symptom of `fast-mlsirm` PRs sitting with 20+ checks `QUEUED` and 0 completed for extended periods.

That baseline reproduces, live and two weeks later, the exact signature already recorded in
[`docs/doctoring/actions-plan-concurrency-ceiling-20260903.md`](../doctoring/actions-plan-concurrency-ceiling-20260903.md):
single-digit `in_progress` runs against triple/quadruple-digit `queued` runs, org-wide
(`fast-mlsirm`: 8 vs 220; `.github`: 6 vs 220 at measurement time). That record's root-cause finding —
a plan-level concurrent-job ceiling (user-reported 58-60/60 at the time), not workflow-file
duplication — is not something a workflow change in this repository can lift. It also explicitly
warns that a large workflow-consolidation project undertaken on the theory that it fixes the queue
"would be solving the wrong layer of the problem, at real cost."

This ADR exists so the next PR against this effort starts from that constraint instead of
re-discovering it, and scopes what centralization *is* still good for.

## What GitHub's mechanisms actually do (for reference)

- **Reusable workflows (`workflow_call`)** ([GitHub docs](https://docs.github.com/en/actions/using-workflows/reusing-workflows)):
  let a thin per-repo caller invoke a workflow defined once in `.github`. Reduces file drift and the
  number of independent `.yml` files to keep security-equivalent across repos. Does **not** change
  how many jobs the org can run concurrently — each `workflow_call` job still consumes one slot
  against the same org-wide ceiling as any other job.
- **Concurrency groups with `cancel-in-progress`** ([GitHub docs](https://docs.github.com/en/actions/using-jobs/using-concurrency)):
  cancel a stale run when a newer one starts in the same group. This *does* directly reduce
  concurrent-job pressure, by retiring superseded work instead of letting it sit `queued` (or worse,
  `in_progress`) behind newer pushes. This is the one lever here that actually shrinks the number of
  jobs competing for the ceiling, not just the number of files.
- **Organization required-workflow rulesets** ([GitHub docs](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets#require-workflows-to-pass-before-merging)):
  run one canonical workflow file's job graph in every target repo's context; already how this repo
  centralizes `opencode-review`, `strix`, `admit-current-head`, etc. Centralizes *maintenance*, not
  *capacity*.
- **Usage limits** ([GitHub docs](https://docs.github.com/en/actions/administering-github-actions/usage-limits-billing-and-administration#usage-limits)):
  the concurrent-job ceiling is a plan/billing property (GitHub Free/Team/Enterprise tiers set
  different concurrent-job maximums), not something exposed or changeable via the Actions or
  rulesets APIs. Confirmed via this session's own `gh api` exploration: no REST or GraphQL field
  surfaces the org's current ceiling; it's Settings → Billing → Plans and usage only.

## Decision

1. **Do not scope further work here as "fix the queue by centralizing more workflows."** The baseline
   shows that lever is largely already pulled (org-required workflows already cover
   opencode-review/strix/noema/sast/codeql/secrets; concurrency groups already exist on every
   event-triggered required workflow that isn't a reusable `workflow_call` target or an
   `issue_comment`/`schedule` trigger — see baseline doc for the file-by-file check).
2. **The ceiling itself is an org-owner billing decision** (raise plan tier, buy additional included
   concurrency, or provision runners with a separate capacity pool), per the 2026-09-03 doctoring
   record. This ADR does not propose a workflow change to address it, because none exists.
3. **The one remaining code-level lever that reduces total *concurrent job count per PR head*, and
   therefore genuinely helps under a fixed ceiling, is folding required checks that are
   `needs:`-serial or logically redundant into fewer jobs/runners** — the pattern already used for
   `sast-semgrep.yml` (2026-09-13 fold, see baseline doc and
   `docs/product-technical-gap-baseline.md`) and for the `opencode-review.yml` chain-depth cut
   (`#1910`). Any future PR in this space should look for the same fold opportunity rather than
   proposing new centralization for its own sake.
4. **`bandscope`'s 89% cancellation rate across all 7 of its required workflows** (91 runs each,
   ~80 cancelled, in the 24h baseline) is the one concrete duplication/thrash signal this baseline
   surfaced and is not yet explained — worth a scoped follow-up investigation (what's re-triggering
   pushes that often on that repo) before proposing a fix, since the cause is unconfirmed.

## Consequences

- No PR follows directly from this ADR: the smallest safe next step this session could find
  (add missing `concurrency:` blocks) was already done org-wide, and consolidating further reusable
  workflows would add maintenance surface without moving the KPI this task defined (p95 queue time,
  jobs per PR head) — that KPI is dominated by the plan ceiling, not file count.
- The KPI itself needs a caveat added wherever it's used: run-level `created_at` → `run_started_at`
  queue time is close to 0 for nearly every workflow in this org (see baseline doc) because a run's
  status flips to `in_progress` as soon as one job starts, even while other jobs in the same run sit
  `queued`. Any future measurement of this KPI should use job- or check-suite-level `started_at`,
  not run-level, or it will systematically under-report the stall.
- Escalating the plan-ceiling question to the org owner (or confirming it's already been acted on
  since 2026-09-03) is the highest-leverage next action, and is outside what a repository-scoped PR
  can do.
