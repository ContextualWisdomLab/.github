# Loop-brief items 15-18: verified already resolved, no further change needed

## Context

The 2026-09-03 standing-loop brief asked to confirm whether several specific
workflow-consolidation and telemetry items were complete, since the queue felt
like it was growing rather than shrinking. This records what was checked and
why each item needed no further code change as of this branch's base commit
(`4f95abc`).

## Item 15 — remove `org-queue-sweep` if plain GitHub Actions syntax can do it

`org-queue-sweep` (`.github/workflows/pr-review-merge-scheduler.yml:591`) walks
every organization repository looking for PRs that became mergeable after
their last triggering event fired (event-driven scheduler runs do not retry on
their own). GitHub Actions has no native primitive for "enumerate every org
repository's PR queue and act on each" — this requires the GitHub API calls
the job already makes; it is not something a `schedule:`/`concurrency:` block
alone could replace.

What plain Actions syntax *can* control, it already does: the schedule trigger
is deduplicated by workflow's own top-level `concurrency:` group
(`schedule-${{ github.event.schedule }}`), and the job carries a `timeout-minutes: 60`
ceiling plus several already-hard-won budget knobs
(`ORG_SWEEP_MAX_PRS`, `ORG_SWEEP_REVIEW_DISPATCH_LIMIT`,
`ORG_SWEEP_MAX_UNAVAILABLE`, rotation logic) whose comments cite the specific
production incidents that shaped them (`.github#1219`, `.github#1223`). The
rate-limit symptom this item worried about traces to the org's Actions
plan-level 60-concurrent-job ceiling
([[project-actions-plan-concurrency-ceiling]], `.github#1754`, docs-only,
merged) — a billing-tier constraint no workflow-file change can fix.
No action taken; removing or rewriting this job would re-litigate an
already-evidenced design.

## Item 16 — consolidate the per-repo hourly-review-repair caller shown in the linked run

The linked run (`ContextualWisdomLab/.github` run `33524178483`, job
`99910668839`, workflow `governance-risk-compliance-hourly-review-repair.yml`)
failed at "Validate scheduler target and dispatch authority" because
`governance-risk-compliance` was hardcoded into the scheduler in a way the
validator rejected. Both problems are already fixed on this branch's base:

- The per-repo caller file itself no longer exists — consolidated into the
  shared `hourly-review-repair.yml` matrix by PR #1673
  (`29b931e`, "refactor(actions): consolidate hourly review-repair callers").
- The hardcode that made that specific run fail was replaced with an
  org-variable admission path by PR #1743 (`8c08583`, already at the tip of
  `main` this branch is based on; doctoring: this commit's own message and
  `4f95abc`).

No action taken; the cited failure predates both fixes.

## Item 17 — maximize GitHub Actions file consolidation org-wide

Already swept: `docs/doctoring/ci-workflow-duplication-audit-20260902.md`
(PR #1731, `9330d41`) re-checked all 63 non-archived/non-fork org repositories
(255 workflow files) for duplication beyond the hourly-review-repair,
R-CMD-check, and dependency-review consolidations already completed. Verdict:
18 of 19 filename-collision groups are genuinely different policies (different
language/toolchain, security posture, thresholds, trust model, or job
topology — evidenced per group), and the one true near-duplicate
(`hourly-pr-maintenance.yml` in DiagramWeave/ThreadWeave) is already two
~20-30 line thin callers of a shared reusable workflow, differing only by a
deliberate cron stagger — wrapping that further would be an unrequested
abstraction over two already-small files. No action taken; re-running this
audit from scratch would duplicate #1731 rather than extend it.

## Item 18 — GitHub App installation token format change (`ghs_...`, ~520 chars, stateless)

Searched `scripts/ci/*.py` and `.github/workflows/*.yml` for any assumption
about installation-token length or prefix shape: no fixed-length checks
(`len(token) == N`), no prefix/length regexes matching the old `ghs_` format,
and no truncating display logic keyed to a specific length. The only
token-shaped regexes present (`noema_review_gate.py:240,245`,
`pr_review_merge_scheduler.py:254`) are secret-redaction patterns
(`token\s+<anything-non-whitespace>` -> `***`) that mask a token of any length
or format when logging — they do not depend on the token being any particular
size. No action taken; this repository has nothing that would break under the
announced longer, stateless installation-token format.
