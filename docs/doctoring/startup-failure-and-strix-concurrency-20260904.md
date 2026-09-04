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
restamped again. The retired required
`CodeQL PR` workflow is excluded explicitly; its platform prohibition was
fixed by the existing dispatch-and-poll architecture and must not be retried.
The PR head is re-read immediately before mutation, and the operation remains
restricted to same-repository branches plus a credential that GitHub permits to
start workflows.

Strix now validates event metadata against the live pull request before the
provider job can enter one `strix-security-scan-<repository>-<pull-request>`
group shared by native PR and repository-dispatch evidence, with
`cancel-in-progress: true`. A delayed stale event is skipped before concurrency
and therefore cannot cancel newer evidence. Push and schedule runs receive a
unique run-id admission output, so they neither cancel PR evidence nor one
another. Workflow-level concurrency was deliberately not used because GitHub
applies it before any live-head admission job can run and does not guarantee
concurrency ordering.

## Verification

- `python -m pytest -q tests/test_pr_review_merge_scheduler.py -k 'startup_failures or startup_failure'`
- `bash scripts/ci/test_strix_quick_gate.sh`
- `actionlint -color never .github/workflows/strix.yml`

The review sidecar and its direct contract tests are intentionally outside this
change.
