# 0025 — Restore central CodeQL as a required workflow via repository_dispatch

**Status:** Proposed, amended 2026-09-09 (one dispatch per pull request; post-matrix run-level wake; exact PR head/base binding) · **Date:** 2026-09-03 · **Owner intent recorded:** loop-brief item 41

## Problem

`.github/workflows/codeql-pr.yml`'s `analyze-head`/`analyze-merge` jobs called
`github/codeql-action/init` and `github/codeql-action/analyze` directly. As of
this ADR, that file is **not** in the org required-workflow ruleset
(`18156473`) — it was removed as an emergency fix (see
`docs/doctoring/codeql-pr-required-workflow-always-fails.md`) after every
ruleset-injected run of it, across every sampled repository, ended in
`startup_failure` with zero jobs created. The reason, confirmed via the
GitHub web UI (the REST API exposes nothing) and independently corroborated
against GitHub's own community documentation
(github.com/orgs/community/discussions/69595, github.com/google/github-team#5):
**`github/codeql-action/init`/`analyze` are categorically disallowed inside
any workflow admitted through a ruleset's `workflows` rule type** ("required
workflows"). This is a platform restriction, not a configuration mistake —
no SHA pin or version bump changes it.

Constraint confirmed during this investigation, load-bearing for the design
below: GitHub's admission check for required workflows appears to scan the
**entire workflow file** for disallowed actions before starting any job — the
observed `startup_failure` produced zero check runs, not just a failure of
the two jobs that actually call `codeql-action`. Any fix that keeps a
`codeql-action` reference anywhere in the required-workflow file, even in a
job that would never execute for a given event, will be refused at
admission. The fix must remove every `codeql-action` reference from the
required-workflow file itself, not merely gate it with an `if:`.

Second constraint, also load-bearing: per GitHub's own documentation
("Required status checks do not take workflow, matrix, or event trigger
types into account... you must manually enter the exact check name
expected" — and, from the community discussion above, the ruleset's
`workflows` rule type tracks the **specified file's own execution**, not an
externally-posted check-run that merely happens to share a name) — the
required check for `codeql-pr.yml` can only be satisfied by a job that is
still literally defined *inside* `codeql-pr.yml`. A separate, unrelated
workflow cannot satisfy this required check by posting a same-named
check-run from outside; the job producing the required check-run identity
must remain part of the required-workflow file's own run.

## Why not just rely on GitHub's native code-scanning default setup

A parallel finding the same day (peer investigation, not part of this ADR)
enabled GitHub's native "code scanning default setup" on the 23 of 71
ruleset-covered repositories that had no CodeQL coverage from any source.
That is real, working, per-repository coverage and should stay — but it is
not equivalent to what `codeql-pr.yml` provided and is not a substitute for
this ADR:

- Native default setup's languages, query suite, and schedule are configured
  **per repository**, not centrally by `.github`. This org's stated
  preference is a single canonical owner for org-wide CI policy
  (`docs/CWL-MASTER-CONTEXT.md` §7), not 71 independently-drifting
  configurations.
- `codeql-pr.yml`'s Medium+ SARIF gate **fails the pull request check** on an
  unsuppressed Medium-or-higher security finding; native default setup by
  itself only creates code-scanning alerts, and making it a hard merge gate
  again requires attaching its dynamic, per-repository `Analyze (<language>)`
  context names to `required_status_checks` — which is exactly the
  centrally-unmanageable, per-repository configuration this org has tried to
  avoid.
- `codeql-pr.yml` additionally scanned the **merge-commit preview**
  (`analyze-merge`, catching issues introduced only by the merge itself),
  which native default setup does not do at all.

Native default setup is the right *baseline safety net* (and is now in place
everywhere); it does not replace a centrally-owned, hard-gating required
check. Both should coexist.

## Proposed architecture

Follow the same required-workflow-entrypoint-dispatches-to-native-execution
pattern already proven by `strix.yml` (`repository_dispatch` +
`Fetch pull request head for trusted scan` + `Publish same-head manual Strix
status`) and OpenCode's runner-release plus exact run/job wake-up contract.
Concretely:

```
codeql-pr.yml (required workflow, runs in target repo context)
  detect-languages          -- UNCHANGED: checkout PR head, detect languages
                                and changed-path scope. No codeql-action
                                reference; already admission-safe today.
  dispatch-analysis         -- NEW: exchange OIDC for an OpenCode app token
                                scoped to ContextualWisdomLab/.github
                                (identical exchange call already used by
                                opencode-review.yml's dispatch step), then
                                POST repos/ContextualWisdomLab/.github/dispatches
                                with event_type: codeql-scan and a payload of
                                {target_repository, pr_number, pr_head_sha,
                                pr_base_sha, matrix}. Re-validates live PR
                                state first (open, not draft-exempt in the
                                same way OpenCode's dispatch step already
                                does) before dispatching.
  analyze-head (matrix)     -- SAME REQUIRED-CHECK NAME:
                                "CodeQL compatibility analysis (${{ matrix.language }})".
                                No codeql-action reference and no
                                repository_dispatch. On attempt one it
                                re-checks the live head, consumes an
                                authenticated codeql-dispatch/<language>
                                status when one exists, and otherwise fails
                                pending to release the runner. On a later
                                run-level failed-job rerun it reads the
                                authenticated current-head status once and
                                reflects it as this job's own exit code.
  dispatch-current-head     -- needs analyze-head, runs on attempt one of an
                                open current-head PR after the shards have job
                                ids. Collects those ids from this run's jobs
                                API, POSTs event_type codeql-scan once with the
                                remaining language matrix and required_jobs:
                                [{language, job_id}, ...], and fails closed if
                                any shard job id is missing. Skips the POST
                                when every language already has a terminal
                                verdict.

.github/workflows/codeql-scan-dispatch.yml (runs natively in .github,
NOT admitted through the ruleset, so codeql-action is unrestricted here)
  on: repository_dispatch: types: [codeql-scan]
  validate-dispatch          -- Re-validate the payload against the LIVE pull
                                request in the target repository; state,
                                repository, base ref/SHA and head ref/SHA must
                                match exactly. Export the validated base/head
                                identity and exact required run/job map.
  scan (matrix over payload languages)
                              -- Exchange OIDC for a target-repo-scoped
                                OpenCode app token. Re-read the live PR before
                                the privileged scan and require the same
                                validated base/head identity. Checkout the PR
                                head at the exact validated SHA. Run
                                codeql-action/init + codeql-action/analyze with
                                upload: false, apply the shared Medium+ SARIF
                                gate, preserve SARIF, and publish
                                codeql-dispatch/<language> when credentials
                                permit.
  wake-required-codeql       -- Needs validate-dispatch + the complete scan
                                matrix and runs only after every language shard
                                terminates. Re-fetch the live PR and require
                                state=open plus exact validated base/head.
                                Re-fetch the exact required workflow run and
                                require id/event/path/head/status plus exactly
                                one pull_requests[] association whose PR
                                number, head SHA, and base SHA equal the
                                validated tuple. Revalidate every supplied
                                failed language job's id/run/head/name/status,
                                then call the exact run's
                                rerun-failed-jobs endpoint once. Missing,
                                stale, retargeted, or ambiguous identity fails
                                closed and leaves the required job failed.
```

### Concurrency identity is per pull request; language independence is the job matrix

The required `analyze-head` matrix still publishes one named check per
language. It no longer POSTs. One `dispatch-current-head` job sends every
still-pending language in a single `codeql-scan` payload (`matrix` plus
`required_jobs`). The native handler's concurrency group is
`codeql-scan-dispatch-${target_repository}-${pr_number}` with
`cancel-in-progress: true`, so a newer HEAD of the same pull request cancels
its predecessor and other repositories or pull requests stay independent.

Language independence is `strategy.fail-fast: false` on that one run's job
matrix. Each scan job publishes its own `codeql-dispatch/<language>` verdict,
but it does **not** wake the required workflow independently. One
post-matrix coordinator validates the complete required-job map and performs
one run-level failed-job rerun. This avoids both sibling cancellation and a
stale failed sibling left behind by per-job reruns.

#### 2026-09-07 amendment: one dispatch per pull request, adopted for the 60-job ceiling

The 2026-09-05 per-language run was the right fix for the accident it
recorded. contextual-orchestrator PR #1049 dispatched three current-head
language jobs, and central run `33938784437` was the sole survivor because
the handler's group omitted `required_language`. Sibling runs cancelled one
another and left their required jobs failed in the `pending` handoff state.
Sending the full language matrix in one dispatch was rejected then because
the handler validated one shard and woke one exact required job per run;
enlarging that surface had no observed need.

That need now exists. On 2026-09-07 the organization job ceiling (60 jobs)
was saturated by this fan-out: ContextualWisdomLab/.github had ~300 queued
runs, 149 of them `codeql-scan-dispatch.yml`, covering 60 PR@SHA tuples
(n=2:29, n=3:27, n=4:2). Duplicate cancellation could not collapse them:
the language is not present on the run name, the job name, or the REST
payload. The user-facing concurrency contract for pull-request workflows is
`{workflow}-{repository}-{PR}` with `cancel-in-progress: true` only for a
superseded HEAD of the same pull request, and a language suffix is
forbidden.

The 2026-09-05 rejection of "full matrix in one dispatch" is therefore
superseded. Siblings are jobs in one run, not runs in one concurrency group.
`required_jobs` remains a 1:1 map of language to canonical job id; the
post-matrix wake validates the whole map and every exact job before one
run-level rerun. A missing, stale, or mismatched identity fails closed. The
old scalar `required_job_id`/`required_language` payload is retained only as
a bounded queued-payload compatibility path where the matrix has exactly one
language; it is not the current producer contract.

#### 2026-09-09 amendment: one post-matrix wake with exact base binding

PR #2051 exposed two distinct coordination faults. First, a partial-shard
wake could rerun the required workflow while a sibling scan was still
running. The rerun's `dispatch-current-head` then posted an identical native
dispatch, and workflow/repository/PR `cancel-in-progress` cancelled valid
sibling evidence. The native handler now waits for the complete matrix and
uses one `wake-required-codeql` coordinator. The required-workflow
coordinator also preserves a queued or running central dispatch whose
immutable title matches `(repository, PR, head SHA, base SHA, required run
id)`; another head, base, required run, or terminal cancelled run does not
suppress fresh evidence.

Second, the post-matrix wake initially revalidated only the PR head and the
required run's head. A PR can retain its head while its base is retargeted.
The validated `base_sha` is therefore part of the wake identity: the live PR
must still have that exact base/head, and the required run's
`pull_requests[]` must contain exactly one association with the same PR
number/head/base. Required run `34318639845` demonstrated that GitHub exposes
that base association directly; no inferred base or mutable external state is
needed. Test-only RED `901af9f024836eadd10c6c98affbee037ffecd58`
reproduced both changed-live-base and wrong-run-base cases against the real
wake shell block; before repair each returned success and emitted one rerun
POST. `66a15d856c251f1db2f91cb3d4a2fa66afd8f48c` binds the wake to the exact
base and makes both cases fail closed with no POST. See
`docs/doctoring/codeql-partial-shard-wake-duplicate-dispatch.md`.

Per-language wake, polling/sleep, broad workflow rerun, and widening the
concurrency key to include head/base were rejected. They either recreate the
sibling-race class, consume runners while waiting, or prevent a genuinely
superseded head from cancelling its predecessor.

## Scope decision: `analyze-merge` is dropped, not migrated

`analyze-merge` ("CodeQL merge preview") is confirmed, per PR #1766's own
commit message, **required nowhere** in the current ruleset. Migrating it to
the dispatch pattern doubles the size and risk of this change for a check
that gates nothing today. It is dropped in the first implementation of this
ADR; re-adding a merge-preview scan (dispatch payload already carries
`pr_base_sha`, so the merge-commit ref could be resolved the same way) is a
follow-up once the required `analyze-head` path is live and proven, not a
blocker for this one.

## Security considerations (must be resolved during implementation, not assumed)

- **Payload forgery / TOCTOU:** the dispatch handler must re-fetch the live
  PR and refuse scan, publication, or wake when either validated head **or
  base SHA** no longer matches. At wake time the exact required workflow run
  must also carry exactly one matching PR-number/head/base association in
  `pull_requests[]`. A forged, stale, or same-head/different-base run must
  never authorize a rerun or make an unrelated base appear scanned.
- **Cross-repository checkout trust boundary:** the scan step checks out
  arbitrary target-repository PR-head content into `.github`'s own runner.
  This is the same trust boundary `strix.yml` already crosses today (its
  `Fetch pull request head for trusted scan` step) — reuse its harden-runner
  posture and its "never execute PR content from the trusted base checkout"
  invariant; the CodeQL scan only *analyzes* checked-out files, it does not
  execute them, which is a narrower risk than Strix's own scanning already
  accepts.
- **Status-publish credential scope:** the token used to publish the
  `codeql-dispatch/<language>` commit status must be scoped to `statuses:write`
  on the *target* repository only, following the same per-repository
  app-token minting `strix.yml` already performs — never a token with
  broader org access.
- **Verdict target cannot be spoofed by the PR author:** a commit status is
  writable by anyone with `statuses:write` on the repository (including,
  depending on token scoping, a workflow running with the default
  `GITHUB_TOKEN` in some configurations) — confirm during implementation
  that the rerun job in `codeql-pr.yml` verifies the status update's
  `creator`/`avatar_url`/app identity matches the expected dispatch-handler
  app, not merely the context name, so a malicious PR cannot forge its own
  passing status. `strix.yml`'s manual-status-publish step already documents
  a similar concern; follow its precedent rather than trusting context name
  alone.

## Alternatives considered and rejected

- **Attach native default-setup's `Analyze (<language>)` names to a required
  check centrally:** rejected — those names and languages vary per
  repository, which cannot be expressed in one org-wide ruleset without
  per-repository ruleset maintenance, defeating the centralization this org
  has repeatedly chosen (`docs/CWL-MASTER-CONTEXT.md` §7,
  `docs/doctoring/ci-workflow-duplication-audit-20260902.md`).
- **Leave `codeql-pr.yml` out of the ruleset permanently, rely on native
  default setup alone:** rejected as the *only* answer — it silently drops
  the hard Medium+ merge gate and the merge-preview scan this org
  deliberately built; acceptable as an interim state (already in effect
  since the emergency fix) but not the intended end state.
- **Ask GitHub support to lift the restriction:** not pursued — this is a
  documented, evidently deliberate platform limitation
  ("CodeQL requires configuration at the repository level"), not a bug
  report candidate.

## Risks and effects

- Adds one native dispatch workflow and one `scripts/ci/codeql_sarif_gate.py`
  module (with its own test file, contributing to the 100%-coverage
  requirement on `scripts/ci/`) to the org's central CI surface. The extra
  surface is offset by removing duplicated inline gate logic and by keeping
  CodeQL action execution out of the required-workflow file.
- A repository and pull request have one active native handler run. Language
  parallelism is bounded by the detected CodeQL matrix inside that run, and a
  superseded HEAD of the same pull request cancels the in-flight handler
  instead of queuing another copy per language.
- Run-level wake is deliberately stricter than commit status identity. A
  same-head base retarget invalidates the wake even when old statuses remain
  attached to the commit; fresh base-materialized evidence is required.
- Re-admitting `codeql-pr.yml` to ruleset `18156473` must happen only after
  this design is implemented, tested, and its required workflow is confirmed
  free of every `codeql-action` reference. Re-adding it with the admission bug
  still present would recreate the org-wide startup-failure incident this ADR
  exists to prevent.

## Follow-up

1. Keep `scripts/ci/codeql_sarif_gate.py` and its tests as the single Medium+
   gate used by the native handler.
2. Verify the final `codeql-scan-dispatch.yml` contract, including full-matrix
   independence, exact PR/head/base run binding, and no polling/manual escape
   path, on the exact candidate head.
3. Verify `codeql-pr.yml` contains no `codeql-action` reference and preserves
   the exact required check names while using one current-head dispatch.
4. Merge the corrected central owner normally only after exact-head hosted
   checks and qualifying independent review.
5. After protected-main integration, require a fresh real downstream PR to
   demonstrate base-materialized CodeQL dispatch, one post-matrix wake, and
   terminal required verdicts before treating consumer bootstrap as GREEN or
   declaring this ADR Accepted.
