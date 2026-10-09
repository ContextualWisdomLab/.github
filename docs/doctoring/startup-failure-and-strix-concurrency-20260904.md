# Startup failure recovery and Strix concurrency repair

## Evidence

The organization-wide REST census on 2026-09-04 covered all 74 visible
ContextualWisdomLab repositories. It found no new `startup_failure` created
after central main `07db37e5e42c63ba40ac66f22ef74e4f8836ce9a`, confirming that the
required-workflow CodeQL prohibition is no longer firing. The census still
found six non-CodeQL startup failures on unchanged heads of two open pull
requests. Their REST job lists are empty. A live
`POST /actions/runs/32985871408/rerun` probe also returned
`403 This workflow run cannot be retried`, so neither job nor run retry can
recover them.

The same audit found that `strix.yml` admitted provider jobs directly into a
job group that included `github.event_name`, which put
`pull_request_target` and `repository_dispatch` evidence for the same
repository and pull request in different queues. It also used
`cancel-in-progress: false`, preserving duplicate scanner work.

## Decision

The scheduler now considers only the newest run for each workflow on the exact
current head. When any latest PR run has `startup_failure`, it reuses the
existing guarded same-tree restamp operation to create one new head and one
fresh `synchronize` event. A newer queued or completed run suppresses
recovery, and a head whose latest commit is already the recovery restamp is not
restamped again. The former direct-CodeQL required workflow was excluded while
its platform prohibition remained. The dispatch-and-poll architecture has
since removed all `github/codeql-action` use from the required entrypoint, so
CodeQL now uses the same guarded recovery path as every other pre-job failure.
The PR head is re-read immediately before mutation, and the operation remains
restricted to same-repository branches plus a credential that GitHub permits to
start workflows.

The original Strix design assumed that live-head admission ran before
workflow-level concurrency. That ordering assumption was false: GitHub applies
workflow-level concurrency before any job can query the live PR, so a delayed
old `synchronize`, `closed`, or `converted_to_draft` event could cancel a
newer current-head/lifecycle run before the admission job executed.

The corrected contract separates three identities:

- Workflow-level admission uses target repository, PR number, exact head SHA,
  and event action. A delayed stale event therefore occupies a separate group
  and cannot cancel the newer head before live admission. Push runs still
  coalesce per protected branch; schedule and PR-less dispatch retain unique
  run IDs.
- The actual `strix` provider job uses a distinct stable group keyed only by
  target repository and PR number, with `cancel-in-progress: false`. Native
  PR and `repository_dispatch` events therefore serialize actual provider work
  in the same queue without making a newer run blindly cancel current evidence.
- The `cancel-superseded-pr-runs` cleanup job uses its own repository/PR/head/
  action group, `actions: write`, and live PR revalidation before run selection
  and immediately before each cancellation. It is the authority for retiring
  obsolete heads; workflow-level cancellation is not treated as proof of
  staleness.

GitHub Actions does not support `queue: max`; the repair intentionally does
not add that unsupported key. The structural regression in
`tests/test_required_workflow_queue_contract.py` now pins workflow head/action
identity, the separate PR-stable provider group, and head/action-scoped cleanup.
The repair is Proposed until focused tests, actionlint, the full suite, fresh
exact-head hosted Checks, qualifying independent approval, ordinary protected
merge, and a post-merge live canary are observed.

**Amendment (2026-09-05).** "nor one another" no longer holds for `push`
events on the same branch. Measured at 14:27Z in `.github`: nine `push`/`main`
Strix runs were outstanding at once — five holding runner slots under the
shared 60-job ceiling (jobs started 12:31-14:25Z, one already past two hours)
and four more waiting in the queue behind them, which occupy no slot until a
runner is assigned — against a 10-30 minute normal scan. The run-id fallback
in the workflow-level group made every main push its own group, so no newer
main head ever retired an older scan. The workflow-level group now scopes
`push` events as `push-<ref_name>`: a newer head of the same protected branch
supersedes the older scan exactly as a newer PR head does. What a retired scan
gives up is its own report, not the gate's inputs: a push scan covers the whole
tree (`STRIX_TARGET_PATH` is `./` outside PR scope) and publishes no `strix`
commit status, so the newest head's scan is a complete scan *of the current
tree*. It is not a record of every earlier commit: code that entered and left
`main` between two heads, and findings a retired run never uploaded, are absent
from the newest report, and report collection preserves only runs that reach
it. A per-commit evidence-retention guarantee would need a separate,
verifiable preservation contract; this change does not provide one. `schedule`
and PR-less `repository_dispatch` runs still receive a unique run id. The
`pr_number=${GITHUB_RUN_ID}` admission output is unchanged.

Tradeoff, stated so a later reader of the security dashboard is not
surprised: with `main` moving roughly every 30 minutes against a 10-30 minute
scan, "main is scanned after every merge" becomes "the latest `main` is
scanned once merging pauses for at least one scan duration". During a merge
burst each new head cancels the previous scan; the burst's final head is
scanned, and the weekly full-tree `schedule` scan (unique run id, never
cancelled) is the floor under a sustained burst.

## Verification

- `python -m pytest -q tests/test_pr_review_merge_scheduler.py -k 'startup_failures or startup_failure'`
- `bash scripts/ci/test_strix_quick_gate.sh`
- `actionlint -color never .github/workflows/strix.yml`

The review sidecar and its direct contract tests are intentionally outside this
change.
