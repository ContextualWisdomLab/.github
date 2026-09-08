# 0025 — Restore central CodeQL as a required workflow via repository_dispatch

**Status:** Proposed, amended 2026-09-07 (one dispatch per pull request; language independence is the handler job matrix) · **Date:** 2026-09-03 · **Owner intent recorded:** loop-brief item 41

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
                                authenticated base-bound
                                codeql-dispatch/<language>/<base_sha>
                                status when one exists, and otherwise fails
                                pending to release the runner. The trusted
                                handler publishes the terminal status and
                                later settles the failed run once. On the woken
                                attempt the shard reads the authenticated
                                current-head status once and reflects it as
                                this job's own exit code.
  dispatch-current-head     -- NEW: needs analyze-head, runs on attempt one
                                of an open current-head PR after the shards
                                have job ids. Collects those ids from this
                                run's jobs API, POSTs event_type codeql-scan
                                once with the complete rerun language matrix and
                                required_jobs: [{language, job_id}, ...], and
                                fails closed if any shard job id is missing.
                                Skips the POST when every language already
                                has a terminal verdict. github.run_attempt == 1
                                is required: a run-wide wake re-runs
                                dependents, and a second dispatch would cancel
                                the in-flight multi-language handler. A partial
                                matrix cannot authorize unscanned job ids.

.github/workflows/codeql-scan-dispatch.yml (NEW, runs natively in .github,
NOT admitted through the ruleset, so codeql-action is unrestricted here)
  on: repository_dispatch: types: [codeql-scan]
  validate-dispatch          -- Re-validate the payload against the LIVE pull
                                request in the target repository (identical
                                pattern to strix.yml's "Validate repository
                                dispatch against live pull request metadata":
                                reject if state/base/head don't match exactly).
  scan (matrix over payload languages)
                              -- Exchange OIDC for a target-repo-scoped
                                OpenCode app token (identical exchange used
                                by strix.yml's target_app_token step).
                                Checkout the target repository's PR head at
                                the exact validated SHA (harden-runner
                                audited, matching strix.yml's checkout
                                posture). Run codeql-action/init +
                                codeql-action/analyze with upload: false
                                (same as today). Apply the Medium+ SARIF gate
                                (extracted to scripts/ci/codeql_sarif_gate.py
                                with its own unit tests, replacing the
                                current inline-Python duplicated between
                                analyze-head and analyze-merge -- one script,
                                one test file, used from both the merge
                                preview path if it returns and this dispatch
                                handler).
                              -- Publish the result as a commit status on the
                                TARGET repository at context
                                "codeql-dispatch/<language>/<base_sha>" using the
                                target-scoped token (identical mechanism to
                                strix.yml's "Publish same-head manual Strix
                                status" multi-token fallback chain), state
                                success/failure, a structured description bound
                                to head/run/producer-source, and target_url
                                pointing at this .github run's own log.
                              -- Upload the SARIF as an artifact on this
                                .github-side run for audit trail (mirrors
                                strix.yml's "Preserve CodeQL SARIF evidence"
                                / artifact retention today).
  settle-required-run        -- After every matrix job is terminal, re-fetch
                                the open PR and exact failed required workflow
                                run; require matching repository/base/head,
                                every distinct run/job/name/conclusion, each
                                exact gate step and SARIF artifact, and no
                                unrelated failed job. One actions:write owner
                                then calls the run-wide rerun endpoint. Missing,
                                stale, closed, or mismatched identity fails
                                closed and leaves the required run failed.
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
matrix. Each scan job publishes `codeql-dispatch/<language>` and preserves its
SARIF evidence. A single non-matrix settlement job runs only after the complete
matrix is terminal, revalidates every required job and language artifact, and
issues one run-wide rerun. A partial matrix is rejected because it cannot prove
an omitted required language without duplicating the producer's receipt trust
logic in the mutation owner. One language's failure cannot cancel or skip a
sibling, and two siblings cannot race mutations on the same required run.

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
superseded. The sibling-cancel failure mode is gone because siblings are jobs
in one run, not runs in one concurrency group. `required_jobs` remains a 1:1
map of language to distinct canonical job ids. The settlement owner validates
the complete map before one run-wide mutation; a missing, stale, duplicated,
unrelated, or mismatched identity fails closed. The old scalar
`required_job_id`/`required_language` payload remains a bounded compatibility
input for already queued calls only.

### 2026-09-08 amendment: one attempt-level settlement owner

Protected handler runs `34220757095` and `34220806323` established two coupled
failures. In the first, the actions shard completed analysis, gate, SARIF, and
status publication and woke the required workflow; the Python shard then
received HTTP 403 because the same workflow was already running. In the
second, #1902's valid ten-property dispatch reached the handler, but the
handler read only legacy top-level `required_jobs` and exposed
`SUPPLIED_REQUIRED_JOBS: null` instead of the nested
`rerun_request.required_jobs`.

Constraints are: preserve every live repository/PR/base/head/run/job binding;
retain the target-scoped App-token fallback chain; support already queued
legacy payloads without trusting two representations; never let a matrix shard
own Actions mutation; and never rerun unrelated failed work. Alternatives were
rejected as follows: serial job-level reruns retain timing-dependent shared
state; blind cancellation loses valid completed evidence; and copying both
payload representations exceeds or approaches GitHub's ten-property limit and
creates conflicting authority.

The selected contract accepts exactly one of legacy top-level rerun fields or
`rerun_request:{mode,required_jobs}`, validates `mode` as `failed|all`, requires
unique language and job identities, and normalizes the result. Matrix jobs have
`actions: read`. One `actions: write` settlement job authenticates every
terminal scan and unexpired exact-name SARIF artifact, re-fetches the open PR
and unchanged base/head plus the complete required-run job list, rejects
unrelated failures in `failed` mode, then calls `/rerun-failed-jobs` once or
`/rerun` once. Missing evidence or exhausted credentials terminates without a
mutation. #1902 remains Draft until this handler contract lands normally and
the producer is non-force restacked for exact end-to-end evidence.

#### 2026-09-08 amendment: version the head tuple to stay within GitHub's dispatch limit

**Status: Proposed.** Exact-head CodeQL run
[`34214980549`](https://github.com/ContextualWisdomLab/.github/actions/runs/34214980549),
coordinator job
[`102028015000`](https://github.com/ContextualWisdomLab/.github/actions/runs/34214980549/job/102028015000),
failed before creating a handler run because GitHub rejected the producer's
11-property `client_payload` with HTTP 422: no more than ten top-level
properties are accepted. The extra properties are not disposable: live base,
head, producer revision, required-run, job, and matrix identities are all
security or exact-evidence bindings.

The selected migration groups only the head tuple into one versioned object:
`pr_head: {schema: "1", ref: <ref>, sha: <sha>}`. The handler lands first and
accepts this object while retaining the two legacy scalar fields for in-flight
dispatches. When the nested object is present, it requires schema `"1"` and
rejects missing or unknown versions before trusting the tuple. After that
compatibility foundation is merged and proven, the #1902
producer may replace `pr_head_ref` plus `pr_head_sha` with `pr_head`, reducing
its top-level count to ten without weakening live-PR or exact-head checks.

Alternatives were rejected as follows: deleting an identity field loses a
validation invariant; compacting unrelated fields creates an unnecessarily
large schema transition; and changing the producer before the default-branch
handler understands the envelope makes the repairing PR unable to produce its
own exact-head hosted evidence. The legacy fallback is temporary compatibility,
not authority to accept conflicting shapes: producer tests must emit only one
shape, and a later cleanup may remove the scalars after no live caller remains.

#### 2026-09-08 amendment: bind provenance to the live synthetic merge revision

**Status: Proposed.** A required workflow runs against GitHub's synthetic pull-request
merge commit, while the protected native handler runs from `.github`'s default branch.
Those revisions are from different repositories and histories, so requiring the former
to be an ancestor of the latter is not a valid provenance relation. The selected contract
requires `producer_source_sha` to equal the live pull request's `merge_commit_sha`, fetches
that immutable commit from the target repository, and requires exactly two ordered parents:
the current live base SHA followed by the current live head SHA. A missing, stale, rewritten,
or differently parented merge revision fails before scan or settlement authority is granted.

The same boundary treats raw JSON as authoritative for type information. `pr_head` must be
an object with string `schema`, `ref`, and `sha`; its values must match the workflow-extracted
scalars, and any independently supplied legacy head fields must be equivalent. This carries
#2044's valid envelope delta into #2040 without duplicating settlement ownership.

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
  PR from the API and refuse to scan or publish anything if the dispatched
  `pr_head_sha` no longer matches the live head, exactly like `strix.yml`'s
  existing `Validate repository dispatch against live pull request metadata`
  step and the exact-job wake-time revalidation. A forged or stale
  dispatch must never be able to make an unrelated head appear scanned.
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

- Adds one new workflow file and one new `scripts/ci/codeql_sarif_gate.py`
  module (with its own test file, contributing to the 100%-coverage
  requirement on `scripts/ci/`) to the org's central CI surface — more
  surface area to maintain, offset by removing ~70 lines of duplicated
  inline Python between `analyze-head`/`analyze-merge` today.
  exact run/job wake-up follows the OpenCode runner-release pattern while
  avoiding one occupied runner per language for the scan's full duration.
- A repository and pull request have one active native handler run. Language
  parallelism is bounded by the detected CodeQL matrix inside that run, and a
  superseded HEAD of the same pull request cancels the in-flight handler
  instead of queuing another copy per language.
- Re-admitting `codeql-pr.yml` to ruleset `18156473` must happen only after
  this design is implemented, tested, and its `detect-languages`/
  `dispatch-analysis`/`analyze-head` jobs are confirmed free of any
  `codeql-action` reference (grep the final file for `codeql-action` and
  assert zero matches, as a permanent contract test) — re-adding it with
  the bug still present would recreate the exact org-wide 100%-startup_failure
  incident this ADR exists to prevent.

## Follow-up

1. Implement `scripts/ci/codeql_sarif_gate.py` + its test, extracted from
   the current inline gate in `codeql-pr.yml`.
2. Implement `codeql-scan-dispatch.yml` per the design above.
3. Rewrite `codeql-pr.yml`'s `analyze-head` job into the dispatch+exact-job-wake shape;
   delete `analyze-merge` (tracked as future work, not silently lost — this
   ADR is the record).
4. Add a permanent contract test asserting no `codeql-action` reference
   exists anywhere in `codeql-pr.yml`.
5. Only then, re-add `.github/workflows/codeql-pr.yml` to ruleset `18156473`'s
   required `workflows` list (admin:org PUT, same mechanism used to remove
   it) and verify a real PR observes a successful, correctly-named required
   check before declaring this ADR's status Accepted.
