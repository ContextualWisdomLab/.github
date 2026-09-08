# org-queue-sweep and the 2026-09-02 GraphQL secondary rate limit

## Incident

During a multi-hour, many-concurrent-agent-session working day on 2026-09-02,
an interactive session repeatedly hit `API rate limit exceeded for user ID
8172694` on GitHub's GraphQL API, badly enough that resolving PR review
threads (`resolveReviewThread`, a GraphQL-only mutation — GitHub's REST API
has no endpoint for thread resolution) was blocked for hours. The repo owner
asked whether `org-queue-sweep` — a scheduled, organization-wide job in
`.github/workflows/pr-review-merge-scheduler.yml` — could be replaced by
native GitHub Actions syntax (removing the custom implementation), or, if
not, needed a rate-limit improvement plan.

## What org-queue-sweep actually does

`org-queue-sweep` (`.github/workflows/pr-review-merge-scheduler.yml:568-1265`,
the file's last job) runs only on the hourly `schedule: cron: "0 * * * *"` trigger (line 85) or a
manual `repository_dispatch` with `client_payload.org_sweep == true` (line
584-586) — **not** the `*/30 * * * *` cron at line 76, which drives the
separate same-repository `scan-pr-queue` job and explicitly excludes the
hourly tick (line 132-134). This distinction matters: the job header comment
block at lines 77-84 sits next to the `*/30` cron but documents the *hourly*
sweep below it — a documentation-adjacency trap for anyone skimming the file.

Per run, it (`.github/workflows/pr-review-merge-scheduler.yml:935-1064`):

1. Lists every non-archived, non-disabled org repo except `.github` itself
   (one paginated REST call, `GET /orgs/{org}/repos`).
2. Rotates the walk order by a persistent counter (`ORG_SWEEP_ROTATION_INDEX`,
   see `docs/doctoring/org-queue-sweep-rotation.md` — unrelated fairness fix,
   unchanged here).
3. For each repo: one cheap REST call (`GET /repos/{repo}/pulls?per_page=1`)
   to check for any open PR; **skips the repo entirely if none** (line
   988-992 — lever (d) from the task brief was already implemented before
   this investigation).
4. For a repo with open PRs, invokes the same trusted
   `scripts/ci/pr_review_merge_scheduler.py` used by the per-repo,
   event-triggered scheduler, with organization-wide bounded budgets (1
   ordinary + 1 stacked review dispatch, 1 branch update, by default) shared
   across the *entire* sweep, not per repo.

Inside that script, `fetch_open_prs`
(`scripts/ci/pr_review_merge_scheduler.py:1174-1207`) issues one paginated
GraphQL query per ≤25 open PRs (`OPEN_PRS_QUERY`, already fetching
`mergeable`/`mergeStateStatus` and reviews/checks in the same round trip —
this is *not* an N+1 REST loop), then calls
`enrich_rest_mergeable_states` to refresh mergeability via REST
(`fetch_rest_mergeable_state` + `fetch_compare_branch_freshness`, 2 REST
calls per PR). That REST refresh exists because GraphQL's
`mergeable`/`mergeStateStatus` fields are computed asynchronously by GitHub
and can be stale immediately after a push (commit `5c6f0694`, "ci: refresh
PR mergeability before queue decisions") — it is deliberate, tested
correctness, not naive duplication. `resolve_review_thread`
(`scripts/ci/pr_review_merge_scheduler.py:1717-1719`) — the exact GraphQL
mutation the incident report names — is called only per genuinely-outdated
unresolved thread (`resolve_outdated_review_threads`), typically zero to a
handful across an entire sweep.

**Confirmed by reading the code, not assumed:** yes, this is exactly the
polling reconciliation the header comment (lines 568-580) describes — a
fallback for PRs that become mergeable *after* their last triggering event
(a late approval race, a required check that lands after the scheduler's own
pass, a base-branch policy blocker clearing) with no later GitHub Actions
event to re-wake the per-repo scheduler.

## Quantified API cost

Per hourly run, for an org with `R` non-`.github` repos and `A` of them with
open PRs, before this change:

- REST: `1 + R + Σ(2 × open_PRs_in_repo)` for the org list, per-repo
  open-PR gate, and per-PR mergeability refresh, plus a small constant for
  the org-wide bounded dispatch/update/merge actions (≤3 REST calls total
  across the whole sweep, since those budgets are 1/1/1 by default).
- GraphQL: `A` list queries (one per active repo, almost always fitting in
  one page) + the count of genuinely outdated unresolved threads across the
  whole sweep (usually 0, occasionally a handful).

This repository's own `docs/doctoring/*-hourly-review-caller.md` inventory
names 14 sibling product repos (afipc, bandscope, clearfolio,
contextual-orchestrator, disksage, fast-mlsirm,
governance-risk-compliance, inkspan, lineageweave, nonnest2, orgmetra,
originweave, quarantine-sandbox, semantic-data-portal), so `R ≈ 14`. A live
`gh api /orgs/ContextualWisdomLab/repos` call to confirm the exact count and
`A` directly was attempted during this investigation and itself hit the same
secondary rate limit on its very first request (see below), so `R`/`A` here
are read from repo evidence rather than a fresh live count — noted as an
approximation rather than silently treated as exact.

Even generously assuming every one of the 14 repos is active with, say, 3
open PRs apiece, one hourly run is on the order of ~15 REST (gate) + ~85 REST
(mergeability refresh, pre-fix) + ~15 REST (misc) ≈ 100-120 REST calls, and
~14 GraphQL list calls + a handful of thread-resolution mutations ≈ 15-25
GraphQL calls — all issued **sequentially across repos** (the sweep is a
plain bash `for` loop over `sweep_targets`; concurrency is bounded to
`REST_MERGEABLE_STATE_WORKERS = 10` only *within* one repo's mergeability
refresh, not across repos). At 24 runs/day that is roughly 2,400-2,900
REST calls/day and 360-600 GraphQL calls/day organization-wide from this one
job — a small fraction of GitHub's 5,000-request/hour *primary* quota, and a
per-repo concurrency level GitHub's own abuse-detection documentation
describes as acceptable (up to ~100 concurrent requests before secondary
limiting applies).

## Is org-queue-sweep the actual cause of this session's rate-limit pain?

**Evidence says no, not primarily.** During this investigation, a single,
completely unrelated REST call
(`GET https://api.github.com/orgs/ContextualWisdomLab/repos`, issued from a
freshly cloned, isolated working copy, using this session's own `gh auth
token`) immediately returned:

```
"API rate limit exceeded for user ID 8172694. ..."
```

— the identical error and user ID from the incident report, reproduced on
the *first* live API call this investigation made. A follow-up call to
`GET /rate_limit` (made once, deliberately, to avoid compounding the exact
problem under investigation) showed:

```
core:    {"limit": 5000, "used": 0, "remaining": 5000}
graphql: {"limit": 5000, "used": 0, "remaining": 5000}
```

Full, **unused** primary quota alongside an active 403 is the signature of
GitHub's *secondary* (abuse-detection / concurrency) rate limiter, not
exhaustion of the 5,000-request hourly budget. GitHub's documented secondary
limits key off concurrent request volume and burst rate for one identity
across *all* simultaneous callers, not a single workflow's cumulative daily
call count. Corroborating this directly: while this investigation was
running, `ps aux` on the same host showed several other concurrent `pytest`/
`coverage` and general agent processes rooted in sibling scratchpad clones
under the same session tree — direct, observed evidence of the "many
parallel autonomous Claude sessions" the task brief hypothesized, all
presumably sharing overlapping GitHub API credentials/identity around the
same time window.

Given `org-queue-sweep`'s own footprint is sequential (not concurrent across
repos), bounded (≤10-way concurrency within one repo, well under GitHub's
own stated ceiling), and modest in absolute volume (well under 1% of the
primary hourly quota even under generous assumptions), it is not a plausible
sole cause of a secondary/concurrency-triggered limit. The much more likely
driver is aggregate concurrent GraphQL usage — including `resolveReviewThread`
calls — from many simultaneous interactive and autonomous sessions sharing
the org's identity pool, landing in the same short window this one hourly
job happened to also be running in.

## Can native GitHub Actions primitives replace it? (the "제거" branch)

**No — not fully, and this repository's own already-verified operational
constraints establish why, not just general GitHub Actions documentation:**

- `docs/org-required-workflow-rollout.md:25` records, from this
  organization's own live verification, that the required-workflow ruleset
  pattern (`CWL Central required workflows`, ruleset `18156473` — the exact
  mechanism Strix/OpenCode/Noema/this scheduler already use to fan a
  workflow out to every repo without per-repo file copies) supports only
  `pull_request`, `pull_request_target`, `push`, and `workflow_run` triggers.
  **`schedule`, `check_suite`, and `check_run` are not in that supported
  set.** There is therefore no way to get GitHub to fan a cron tick, or a
  generic check-suite-completed event, out to every organization repository
  through the required-workflow mechanism this org already relies on.
- Separately, and independently of this org's ruleset support list, GitHub
  Actions' `schedule` trigger is documented to run only in the repository
  that owns the workflow file — it has no cross-repository or
  organization-wide fan-out semantics at all. A schedule trigger placed in
  each sibling repo would need its own workflow file copy in every repo
  (exactly the drift-source pattern `docs/org-required-workflow-rollout.md:32`
  says the central-required-workflow architecture exists to avoid), and
  would still need to make the same GitHub API calls to check state — same
  total call volume, just decentralized, and likely still sharing the same
  `PR_REVIEW_MERGE_TOKEN`/`OPENCODE_APPROVE_TOKEN` credential and therefore
  the same secondary-rate-limit exposure.
- `workflow_run` (already wired at
  `.github/workflows/pr-review-merge-scheduler.yml:10-12`) only re-wakes the
  scheduler on **"Required OpenCode Review"** and **"Strix Security Scan"**
  completion. A PR blocked on a *different* required check (CodeQL, Scorecard,
  osv-scanner, secret-scan, dependency-review — all listed as required
  workflows/gates in `CLAUDE.md`) that lands last has no event-driven
  re-wake today. This is a real, partially-closeable gap (see Future work
  below) but closing it only shrinks the sweep's necessity, it doesn't
  eliminate it, because of the ruleset trigger-type restriction above.
- General webhook/event-delivery reliability: GitHub does not guarantee
  Actions-trigger delivery is lossless or immediate; periodic reconciliation
  against authoritative API state is the standard mitigation for that kind
  of at-least-once/best-effort delivery gap, not a design smell specific to
  this repository.

Given these three independent reasons — the ruleset's documented supported
trigger types, `schedule`'s single-repository semantics, and general
delivery-reliability practice — elimination is not safe or possible with
GitHub Actions' native primitives as they exist today. This finding is
reported per the task's explicit fallback: not fully certain elimination is
safe → propose the improvement-plan path instead, said explicitly.

## What was implemented (the improvement-plan branch)

One concrete, low-risk, evidence-backed optimization, sized to match how
small `org-queue-sweep`'s own contribution actually is (per the analysis
above, this does not fix the *incident* — the incident's cause is
concurrent multi-session load outside this workflow's control — but it is a
genuine, safe reduction in this job's own call volume, worth doing on the
"every bit helps a saturated shared resource" principle the task invited):

`enrich_rest_mergeable_states`
(`scripts/ci/pr_review_merge_scheduler.py:1265-1298`) now skips the 2 REST
calls per PR (`fetch_rest_mergeable_state` + `fetch_compare_branch_freshness`)
for **draft** PRs. `inspect_pr`
(`scripts/ci/pr_review_merge_scheduler.py:3501-3535`) returns for a draft PR
— dispatching at most a draft-only review — before it ever reads
`restMergeableState`, `compareStatus`, or `compareBehindBy` anywhere in its
decision tree (confirmed by tracing every reader of those three keys:
`effective_merge_state`, `compare_behind_by`, `branch_outdated_by_base`, and
their three call sites, all located strictly after the draft early-return).
Refreshing mergeability for a draft PR was therefore two REST calls per
draft, per sweep tick, spent on evidence no decision path ever consults —
pure dead-call elimination with no change to which non-draft PR gets
reviewed, branch-updated, or merged.

This only affects the primary GraphQL-fetch path
(`fetch_open_prs` → `enrich_rest_mergeable_states`). The REST-fallback path
(`fetch_open_prs_rest` → `rest_pr_node`, used only when GraphQL itself is
unavailable) already assembles `restMergeableState` as part of one
already-REST-native per-PR fetch and never calls
`enrich_rest_mergeable_states`, so it is untouched.

### Before/after

- Before: 2 REST calls × every open PR (draft or not) fetched via GraphQL,
  every hourly sweep tick.
- After: 2 REST calls × every **non-draft** open PR only. Savings scale with
  however many draft PRs exist org-wide at sweep time (0 in the common case
  where nothing is mid-draft — this is a real-world-variable, not a fixed
  daily number to quote as guaranteed savings).

## What is NOT being eliminated, and why

- `org-queue-sweep` itself: not removable — see the native-primitives
  section above.
- The hourly cadence: already reduced from every 15 minutes to every 60
  minutes by `#1630` / commit `edbc623f` earlier on 2026-09-02 (see
  `docs/doctoring/actions-queue-saturation-hourly-sweep.md`), a 4× reduction
  in call volume already landed before this investigation started. Further
  reduction is a real lever but was not touched here: it trades staleness
  tolerance the repository owner has not asked to widen, and the same-day
  doctoring entry already frames the hourly value as a deliberately bounded
  choice.
- Skip-repos-with-no-open-PRs (lever (d)): already implemented
  (`.github/workflows/pr-review-merge-scheduler.yml:988-992`), predating
  this investigation.
- Batching the PR list itself (lever (b), N+1 avoidance): already
  implemented — `OPEN_PRS_QUERY` fetches up to 25 PRs' full field set
  (including merge state) in one GraphQL round trip, not one call per PR.
- The 2-REST-call-per-non-draft-PR mergeability refresh: **not** removed or
  narrowed further. It is deliberate, tested correctness (commit
  `5c6f0694`) protecting against exactly the kind of GraphQL-staleness bug
  that would cause an incorrect merge/no-merge decision. This is exactly the
  kind of correctness-critical, previously-incident-driven code this task's
  constraints say not to weaken without being certain, and the evidence in
  this investigation does not support that certainty.
- `resolve_review_thread`'s GraphQL-only mutation: cannot be moved to REST.
  GitHub's REST API has no endpoint for resolving a review thread; only the
  GraphQL `resolveReviewThread` mutation exists. This is the specific
  operation the incident report named, and it is architecturally forced to
  be GraphQL — lever (c) from the task brief does not apply to it.

## Verification

- `PYTHONPATH=. python3 -m coverage run -m pytest tests` — 2602 passed, 1
  skipped, at repo HEAD `669505bdf267d92989298857c740a59807bbd735` plus this
  change.
- `python3 -m coverage report --show-missing` —
  `scripts/ci/pr_review_merge_scheduler.py` 100% line, 100% branch;
  `TOTAL` 100%/100%.
- `python3 -m interrogate` — `RESULT: PASSED (minimum: 100.0%, actual: 100.0%)`.
- New tests: `test_enrich_rest_mergeable_states_skips_draft_prs_entirely` and
  `test_enrich_rest_mergeable_states_enriches_only_non_draft_prs_in_mixed_batch`
  in `tests/test_pr_review_merge_scheduler.py`, alongside the three
  pre-existing tests for the same function (all still passing unmodified,
  since none of them set `isDraft` on their fixtures and are therefore
  unaffected by the new filter).
- No workflow YAML was changed; no contract test listed by
  `grep -rl "org-queue-sweep\|pr-review-merge-scheduler" tests/` needed
  updating, since the change is internal to
  `scripts/ci/pr_review_merge_scheduler.py`'s REST-enrichment step, not the
  workflow's structure, triggers, or job graph.

## References

`docs/doctoring/org-queue-sweep-rotation.md` — prior fairness fix (rotation
offset), unrelated to and unaffected by this change.
`docs/doctoring/actions-queue-saturation-hourly-sweep.md` — same-day
(2026-09-02) cadence reduction from 15 to 60 minutes, `#1630`.
`docs/org-required-workflow-rollout.md:25` — this org's own verified
required-workflow-ruleset supported-trigger-type list, the primary evidence
against native-primitive elimination.
Commit `5c6f0694` — "ci: refresh PR mergeability before queue decisions",
the correctness fix this investigation deliberately left untouched.
