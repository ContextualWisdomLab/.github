# Strix metadata admission consolidation

Status: **Proposed and locally verified**, based on central `.github` commit
`5ea1cc47ec040fa4f6417136f059be637666c2a2`. This is not hosted-run evidence.

## Change and metric

The required Strix workflow previously allocated two read-only metadata jobs:
`changed-scope` and `admit-current-head`. A valid code-changing pull request then
allocated three jobs before completion: those two metadata jobs plus `strix`.
This change moves the byte-identical admission shell ahead of the byte-identical
path classifier in `changed-scope`, publishes `code`, `deps`, `admitted`,
`target_repository`, and `pr_number` from that one job, and makes `strix` depend
only on `changed-scope` while requiring both `code == 'true'` and
`admitted == 'true'`.

The verified source-structure metric is therefore metadata jobs **2 -> 1**.
For `opened`, `reopened`, and `ready_for_review` code-changing PR runs, where
cleanup does not run, total jobs fall **3 -> 2**. A `synchronize` run includes
cleanup and falls **4 -> 3**; an exact dispatch includes the status publisher
and also falls **4 -> 3**. These counts do not claim a hosted queue-time
improvement. A
current exact PR is admitted before its file list is classified; a stale PR
ends successfully with `admitted=false` and never runs the classifier. Direct
push and schedule events make no PR API call and retain fail-open `code=true`.
Exact dispatch validates the live PR but has no native PR changed-file fields,
so the classifier makes no files API call and retains `code=true`. Malformed or
unreadable admission fails the job; empty, unreadable, or count-mismatched file
lists retain the existing fail-open full-scan result.

GitHub documents that a failed or skipped dependency normally propagates to
dependent jobs, which is why admission and classification remain in the same
successful metadata job and the scan reads both outputs. GitHub also requires
step `timeout-minutes` to be a positive number. The metadata job is bounded at
10 minutes and each of its two steps at 5 minutes. See [workflow syntax for
`jobs.<job_id>.needs`](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#jobsjob_idneeds)
and [step `timeout-minutes`](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#jobsjob_idstepstimeout-minutes).

## Permission and latency boundary

Both former jobs had only `contents: read` and `pull-requests: read`; the merged
job keeps exactly that job permission set. The stronger admission credential is
still scoped to the admission step's environment and the classifier receives
only `github.token`. The `actions: write` cleanup job and the scan job's
`id-token: write`/`statuses: write` permissions remain separate. Moazen,
Ahmadian, and Balliu's *Granite: Granular Runtime Enforcement for GitHub Actions
Permissions* explains the general risk of steps sharing job permissions; it
supports keeping unlike privileged work in separate jobs, but it does **not**
establish this change's queue metric. The redistributed v1 PDF is preserved
unchanged at [`docs/papers/granite-granular-runtime-enforcement-github-actions-permissions-v1.pdf`](../papers/granite-granular-runtime-enforcement-github-actions-permissions-v1.pdf),
SHA-256 `5d1dd7b26176de6d5347885867156759928641c8e7415a09869cbfb00cbeb07d`,
under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Citation:
Moazen, M., Ahmadian, A. M., & Balliu, M. (2025). *Granite: Granular Runtime
Enforcement for GitHub Actions Permissions* (v1). arXiv.
https://doi.org/10.48550/arXiv.2512.11602.

The tradeoff is serial latency: admission must finish before classification,
where the old metadata jobs could run in parallel. That delay is bounded by the
5-minute admission step and prevents stale events from spending a second runner.
No model, scan, cleanup, or concurrency behavior is changed.

## Evidence boundary and follow-up

Local regression shells and actionlint verify source wiring and syntax only;
they do not prove hosted output propagation, required-check publication, or
queue latency. Live reads found no separate admission context among the 12
required contexts on `.github` `main` or the 17 required contexts on Naruon
`develop`; organization ruleset
`18156473` could not be read without `admin:org`, so no organization-wide claim
is made. Project linkage is also unverified in this turn because the project was
unavailable and the Mac UI was locked.

The pre-existing workflow-header statement that Strix does not cancel in
progress conflicts with the current `cancel-in-progress: true` expression, but
that text belongs to the independent #1938 concurrency hunk and is intentionally
not mixed into this repair. Track it as a follow-up documentation correction.
