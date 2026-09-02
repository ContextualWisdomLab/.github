# Scheduler stale-`headRefOid` cancellation doctoring

## Incident

`ContextualWisdomLab/naruon` PR #1528's Strix run
(`https://github.com/ContextualWisdomLab/naruon/actions/runs/33581213829`,
job `strix`, `head_sha cf472cf77fb93325858f485a22e967449d7c387a`) was cancelled
at 2026-09-02T01:56:44Z while it was the PR's sole, still-current head -- no
later push ever superseded `cf472cf7...`, confirmed both immediately after the
cancellation and again during this investigation. The run's own
`cancel-superseded-pr-runs` job (defined in `.github/workflows/strix.yml`)
reported `skipped` in the same run, so the naruon-local cleanup job did not
issue the cancellation; sibling `Required OpenCode Review` and `Required Noema
Review` runs for the identical head were left `queued`, untouched. PR #1528 was
created at `2026-09-02T01:54:42Z`, four seconds before the Strix run.

## Root cause

`scripts/ci/pr_review_merge_scheduler.py`'s `stale_pr_run_ids()` and
`active_review_run_refs()` -- called unconditionally near the top of every
`inspect_pr()` pass, both from the per-PR-event `scan-pr-queue` job and the
org-wide `org-queue-sweep` job (`.github/workflows/pr-review-merge-scheduler.yml`)
-- computed the PR's "current head" as:

```python
head = str(pr.get("headRefOid") or "").lower()
```

A falsy `headRefOid` (missing, `None`, or empty -- e.g. a transient upstream
data gap on a PR fetched moments after it opens) silently coerced to `""`.
Every other head-comparison call site in this file validates `headRefOid` via
`validate_git_sha()`, which raises loudly on anything that is not a real SHA;
these two did not. An empty expected head can never equal a real run
`head_sha`, so `stale_pr_run_ids()` classified **every** active run associated
with the PR -- Strix included, regardless of its true, unchanged head -- as
stale, and its caller (`cancel_stale_pr_runs()` / `cancel_stale_opencode_runs()`)
force-cancelled each one via a direct `POST .../actions/runs/{id}/force-cancel`
call with **no further check**. `force_cancel_workflow_runs()` only logs on
*failure*, so a successful misfire leaves no positive trace in the run log --
consistent with why no explicit "cancelled run 33581213829" line could be
found even in the live, actively-cancelling `org-queue-sweep` run
(`ContextualWisdomLab/.github` run `33561946691`) inspected during this
investigation.

This is the exact bug class `docs/doctoring/queue-hygiene-live-ref-race.md`
already fixed for the *sibling* cancellation path in the same workflow --
the bash "Queue hygiene" block that revalidates every candidate through
`scripts/ci/revalidate_queue_cancellation.sh` immediately before cancelling.
That fix never touched `stale_pr_run_ids()` / `active_review_run_refs()`,
which run earlier in the same `inspect_pr()` pass and have no revalidation
step at all: a documented failure mode was repaired in one of two parallel
cancellation mechanisms and left live in the other.

`scripts/ci/current_head_run_coalescer.py` (`.github/workflows/current-head-run-coalescer.yml`)
-- the script named in the original incident report as a candidate -- is not
implicated: that workflow triggers only on `pull_request_target` events against
`ContextualWisdomLab/.github` itself and is not part of the org's required-workflow
rollout (confirmed against the naruon commit's full check-run list, which has
no coalescer job). It coalesces duplicate *queued* runs for one already-current
head inside `.github`'s own PRs, a materially different purpose and blast
radius from the org-wide, cross-repository cancellation path above.

## Scope

Org-wide, not naruon-specific. `stale_pr_run_ids()` and
`active_review_run_refs()` are shared library functions invoked for every
repository the scheduler touches, both from the per-PR `scan-pr-queue` job
(triggered by each target repository's own PR events) and from the hourly
`org-queue-sweep` job (`.github/workflows/pr-review-merge-scheduler.yml`,
`if: github.event.schedule == '0 * * * *'`), which iterates every
non-archived, non-disabled repository in the organization. Any repository
whose PR list ever yields a falsy `headRefOid` for an open PR -- most
plausible on a PR inspected within moments of creation -- is exposed for
Strix, OpenCode, and Noema evidence alike.

## Repair

`stale_pr_run_ids()` and `active_review_run_refs()` now check
`pr.get("headRefOid")` for truthiness before using it, and fail safe (return
`[]` / `([], [])` respectively) with an `::warning::` log line instead of
silently treating a missing head as "matches nothing, so everything is
stale". This mirrors the fail-closed discipline
`revalidate_queue_cancellation.sh` already applies to its own cancellation
path: an unresolvable expected head is a reason to cancel *nothing* for that
PR, not a reason to cancel *everything* associated with it.

## Evidence

`tests/test_pr_review_merge_scheduler.py::test_stale_pr_run_ids_preserves_current_head_run_when_head_ref_oid_missing`,
`::test_cancel_stale_pr_runs_issues_no_cancel_call_when_head_ref_oid_missing`,
and `::test_active_review_run_refs_preserves_current_head_run_when_head_ref_oid_missing`
reproduce the incident directly: a Strix run whose `head_sha` matches the
PR's real, unchanged head (`cf472cf77fb93325858f485a22e967449d7c387a`, PR
number `1528`, repository `ContextualWisdomLab/naruon`), paired with a PR
snapshot carrying `headRefOid: None`. All three tests fail against the
pre-fix code (`stale_pr_run_ids` returns the current-head run id as "stale";
`cancel_stale_pr_runs` issues a live `force-cancel` call against it;
`active_review_run_refs` classifies it as stale rather than current) and pass
after the guard is added. `coverage run -m pytest tests` (2603 passed, 1
skipped) and `coverage report` (100% on `scripts/ci`) plus `interrogate`
(100% docstring coverage) both hold after the change.

### Positive case: a genuinely superseded head is still cancelled correctly

`ContextualWisdomLab/naruon` run `25650417985` ("Strix Security Scan" run
`#86`, PR #140, `head_sha 5371bf3ee97d596ea27cf9d43ea90f0c82ee7b2e`) was
cancelled with the annotation "Canceling since a higher priority waiting
request for strix-Strix Security Scan-140 exists" -- GitHub's native
concurrency mechanism retiring an old-head scan in favor of a newer push to
the same PR, under naruon's PR-scoped concurrency group from before the
current repo-wide, `cancel-in-progress: false` design documented in
`.github/workflows/strix.yml`. This confirms genuine supersession cancellation
has worked in this codebase's history. For the current architecture, the
already-passing `test_workflow_run_filters_skip_mismatched_workflow_and_current_head_other_pr`
and `test_stale_opencode_run_ids_filters_current_head_and_missing_ids` cases
are the deterministic proof that a run whose `head_sha` genuinely differs from
a *valid* `headRefOid` is still correctly classified as stale and cancelled by
the (now-guarded) matching logic -- only a falsy expected head is refused.

Hosted exact-head CI, security, coverage, and review evidence remain
authoritative before merge; this doctoring note does not substitute for those
gates.
