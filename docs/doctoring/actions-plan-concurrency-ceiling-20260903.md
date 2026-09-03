# Doctoring record: the org's GitHub Actions concurrency ceiling is a plan-level quota, not a workflow defect (2026-09-03)

- **Date:** 2026-09-03
- **Subject:** two peer sessions independently observed the org's GitHub Actions run queue growing rather
  than shrinking this week and, in that tick, proposed auditing/consolidating/centralizing workflow files
  across the org as the fix. Before either session sank time into that plan, this root cause needed a
  durable record: the actual bottleneck this session identified is a **plan-level concurrent-job quota**,
  not workflow duplication, and consolidating workflow files cannot lift it.
- **Decision record:** none in `docs/adr/` — this is a diagnostic/root-cause finding for the org owner's
  awareness and eventual plan-tier decision, not an architecture decision this repository can make.
- **PR:** see the PR that carries this commit.

## Primary evidence

The user directly reported, and shared a screenshot of, the organization's GitHub Actions usage view
earlier in this session showing **58-60 of a 60 concurrent-job plan limit in use**. That is the primary
source for the specific ceiling figure in this record. The raw screenshot itself is not reproducible from
this doc (it was shared inline in conversation, not committed to the repository), so the number here is
reported as the user stated it, not independently re-derived pixel-for-pixel — flagged explicitly so a
reader can tell primary-source-observed-directly-by-the-user apart from what this session could verify
itself via the API (below). GitHub does not expose an org's concurrent-job plan ceiling through the
standard REST API available to this session (it is a billing/plan-settings value, visible only in the
org's own Settings → Actions/Billing UI) — confirming the exact number and its precise scope (whether it
counts standard-runner jobs only, whether larger/self-hosted runners have a separate pool, which plan tier
the org is on) requires the org owner to check that page directly; this record does not claim to have
re-verified those specifics independently.

## Corroborating evidence (live, reproducible, gathered for this record)

A live sample taken 2026-09-03 across three of the org's most CI-active repositories, using:

```bash
gh api "repos/ContextualWisdomLab/<repo>/actions/runs?status=in_progress&per_page=1" --jq '.total_count'
gh api "repos/ContextualWisdomLab/<repo>/actions/runs?status=queued&per_page=1"       --jq '.total_count'
```

| Repository | `in_progress` | `queued` |
|---|---|---|
| `.github` | 5 | 1,877 |
| `contextual-orchestrator` | 0 | 727 |
| `naruon` | 5 | 416 |
| **Total (3-repo sample)** | **10** | **3,020** |

This is a deliberately small sample, not a full 63-repo census — an attempted full sweep across every
non-archived, non-fork repository (the same corpus as the 2026-09-02 workflow-duplication audit) hung
indefinitely on this run and was aborted; a post-hoc `gh api rate_limit` check immediately after showed
5,000/5,000 REST calls remaining, so the hang was not caused by hitting the org's shared REST rate limit
(consistent with this session's standing practice of preferring REST over GraphQL to avoid that limit) —
its actual cause is undetermined and not investigated further here, since the 3-repo sample already
establishes the pattern this record needs.

The pattern itself is the useful signal: single-digit `in_progress` counts (5, 0, 5) against
quadruple-digit `queued` counts (1,877; 727; 416) in the same moment, across independently-owned
repositories, each triggering its own workflows on its own schedule. That shape — many jobs queued,
very few ever concurrently running — is exactly what a hard, roughly-constant, **org-wide** (not
per-repository) concurrent-job ceiling produces, and is hard to explain by per-repository causes alone
(each repository's own workflow volume, trigger frequency, and CI design differ substantially). It is
consistent with, though does not by itself prove, the specific 58-60/60 figure from the primary evidence
above.

## Relationship to other queue-related findings already in this repository

This is not the first queue-depth observation recorded here, and this finding does not supersede or
contradict the earlier ones — they describe different, plausibly-compounding causes:

- `docs/product-technical-gap-baseline.md`'s 2026-08-31 entry (chained required-workflow poller removal)
  cites "53 concurrent Actions runs and a growing runner queue" as the trigger for removing roughly eleven
  runner-hours of polling per PR — a real, already-fixed contributor to total load, but framed as a
  mechanism-level fix (reduce runner-hours consumed per PR), not a claim about the plan's own ceiling.
- The later `ubuntu-latest` starved-floating-image finding (same file, referencing 822 queued Actions runs
  observed at merge time) diagnosed a *scheduling* problem — GitHub-hosted runners requesting the floating
  `ubuntu-latest` label sitting `queued` with no runner assignment for hours even when capacity should have
  been available, fixed by pinning off the floating label. That is a distinct failure mode from a hard
  concurrency quota: a starved image can leave slots idle *despite* available capacity, whereas a plan
  ceiling caps how many jobs can ever run concurrently even with perfect scheduling. Both can be true at
  once and both can slow the same queue; neither finding invalidates the other.
- A separate, still-unmerged-as-of-this-writing finding (`project_strix_concurrency_starvation_unfixed` in
  this session's own working notes) identifies that `strix.yml`'s concurrency group is scoped per-repository
  rather than per-PR, which starves cross-PR Strix evidence specifically — again a distinct, compounding
  mechanism, not the same thing as the org-wide plan ceiling this record documents.

## Implication for workflow-consolidation proposals

Consolidating or centralizing workflow files — the idea both peer sessions were independently converging
on this tick as *the* fix for the growing queue — is real hygiene and can reduce the *total number of
runs triggered* (fewer redundant CI paths competing for the same slots), which helps the queue drain
somewhat faster once jobs are submitted. It does **not** change how many jobs GitHub will run concurrently
for this organization at once: that number is set by the plan tier, not by how many `.yml` files exist or
how many of them are centralized versus per-repository. A large cross-repo consolidation-and-deletion
effort undertaken on the theory that it would resolve the backlog would be solving the wrong layer of the
problem, at real cost (each deletion needs branch-protection `required_status_checks` re-verified per
repo, and any repo-specific `with:` tuning preserved or intentionally dropped).

## Recommendation

This is a plan/billing decision, not a code change either agent session can make: raising the concurrent-job
ceiling (a higher GitHub plan tier, purchasing additional included concurrency, or provisioning
self-hosted/larger runners with their own separate capacity pool) is the org owner's call to make with the
actual billing page in front of them, not something to infer further from repository-side evidence.
Workflow consolidation remains worth pursuing for its own, independent hygiene reasons (see
`docs/doctoring/ci-workflow-duplication-audit-20260902.md` for what is and is not already duplicated
org-wide) — but should not be scoped or prioritized as *the* fix for the current backlog growth.

## Audit trail

- User-reported screenshot of the organization's Actions usage view, shared earlier in this session
  (primary source for the 58-60/60 figure; not independently re-verifiable from this record alone).
- Live `gh api` sample gathered 2026-09-03 for this record (table above); `gh api rate_limit` confirmed
  5,000/5,000 REST calls remaining immediately after the aborted full-org sweep, ruling out rate-limiting
  as the sweep's failure cause.
- `docs/product-technical-gap-baseline.md` — the 2026-08-31 chained-poller-removal entry and the
  `ubuntu-latest` starved-image entry, both cross-referenced above.
- `docs/doctoring/ci-workflow-duplication-audit-20260902.md` — the org-wide workflow-duplication sweep this
  record's "Implication" section points back to.
