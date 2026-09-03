# Loop-brief items 4, 15-18, 39: verified already resolved, no further change needed

## Context

The 2026-09-03 standing-loop brief asked to confirm whether several specific
workflow-consolidation and telemetry items were complete, since the queue felt
like it was growing rather than shrinking. This records what was checked and
why each item needed no further code change as of this branch's base commit
(`4f95abc`).

## Items 4 / 39 — opaque 900-second Noema "Repair" timeout, no telemetry on why

Reproduced from the linked evidence:
`ContextualWisdomLab/html4tree` run `33560972491`, job `100033086428`
("Required Noema Review ...#595"), step 13 "Prepare Noema model verdict"
failed with `NoemaRepairDeadlineExceeded: Noema repair exceeded 900-second
absolute wall-clock deadline` on 2026-09-02T02:28 UTC — no further specifics,
matching the complaint exactly. The item-39 example
(`contextual-orchestrator` run `33580381913`, PR #1008) is the same class of
failure, same day.

Already fixed on this branch's base, same day: PR (`a28fc2f`,
"fix(noema): remove caller repair deadline and duplicate model call") found
the 900-second bound had "no owner-specified or measured basis" and, deeper,
that Noema was duplicating a repair/failover responsibility
`contextual-orchestrator` already owns — turning one gateway failure into two
expensive calls. The fix: Noema now sends exactly one structured-output
request to the gateway, with no caller-side deadline, retry, or temperature;
every gateway call now emits a passive Actions annotation carrying attempt
count, elapsed duration, active phase, and a sanitized serving-model
identifier (see `docs/doctoring/noema-repair-attempt-telemetry.md`, PR
`86ef3e7` for the doc's own later clarification pass). A permanent contract
test (`tests/test_noema_repair_has_no_fixed_wall_clock_deadline.py`) forbids
`NOEMA_REPAIR_DEADLINE_SECONDS`, `NoemaRepairDeadlineExceeded`,
`signal.setitimer`, and a caller-authored retry/temperature from ever
reappearing; ran it plus `tests/test_noema_repair_attempt_telemetry.py`
locally (25 passed) to confirm it holds on this branch.

The item-39 PR (`contextual-orchestrator#1008`, head `f35ee58d`) is still
`mergeable_state: blocked`, but its Noema check now shows a fresh attempt
queued at `2026-09-02T19:32:21Z` — after the fix merged — sitting `queued`
with no conclusion yet. That is the already-documented org-wide Actions
job-queue ceiling (#1754), not a recurrence of the repair-deadline bug; no
separate action taken here.

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
production incidents that shaped them (#1219, #1223).

"Rate limit" covers at least two distinct resources here, and this item's
"rate limit issues" symptom should not be collapsed into one cause:

- The org's Actions **plan-level 60-concurrent-*job*** ceiling (#1754,
  docs-only, merged) — a billing-tier constraint on how many jobs (of any
  kind, any repo) can run at once. This is the one that best matches the
  general "queue piles up instead of shrinking" symptom this loop-brief
  opened with, and no workflow-file change can fix it.
- A separate, already-documented **LLM-provider rate limit** — a
  `litellm.RateLimitError` storm against the shared NVIDIA NIM key from too
  many *concurrent Strix/review callers* (`.github` PR #1297, 2026-08-23/24;
  see `.github` PR #1661 /
  `docs/doctoring/strix-cross-pr-concurrency-starvation-20260902.md`, not yet
  merged to `main`). That is why `strix.yml`'s scan job deliberately
  serializes per repository instead of per PR — a different mechanism, a
  different resource, and not something `org-queue-sweep` itself triggers
  directly (it can *dispatch* reviews, but it does not call an LLM provider
  on its own).

`org-queue-sweep`'s own GitHub REST calls are subject to a third resource
(GitHub's per-token API rate limit), which is why it already paginates
conservatively and fails closed past `ORG_SWEEP_MAX_UNAVAILABLE` rather than
retrying harder. No action taken; removing or rewriting this job would
re-litigate an already-evidenced design, and none of the three resources
above are fixable by a workflow-file edit alone.

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

Searched every `.py` and `.sh` file under `scripts/ci/` and `.github/`
(workflows, and the one composite action at
`.github/actions/orchestrator-free-sidecar/action.yml`), then re-checked the
whole repository tree (this repo has no `.yaml`-suffixed files, and
`opencode.jsonc` and the pinned `requirements-*.txt` files carry nothing
token-shaped either), for any assumption about installation-token length or
prefix shape: no fixed-length checks (`len(token) == N`, `token[:N]`), no
prefix/length regexes matching the old `ghs_` format, and no truncating
display logic keyed to a specific length. The only token-shaped regexes
present (`noema_review_gate.py:240,245`, `pr_review_merge_scheduler.py:254`)
are secret-redaction patterns (`token\s+<anything-non-whitespace>` -> `***`)
that mask a token of any length or format when logging — they do not depend
on the token being any particular size. No action taken; this repository has
nothing that would break under the announced longer, stateless
installation-token format.
