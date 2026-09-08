# 0025 — Restore central CodeQL as a required workflow via repository_dispatch

**Status:** Proposed, amended 2026-09-08 (one dispatch and exact-run settlement per pull request; language independence is the handler job matrix) · **Date:** 2026-09-03 · **Owner intent recorded:** loop-brief item 41

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
                                pending to release the runner. On a settled
                                later attempt the shard reads the
                                authenticated current-head/current-base
                                status once and reflects it as this job's own
                                exit code.
  dispatch-current-head     -- NEW: needs analyze-head, runs for an open
                                current-head PR after the shards
                                have job ids. Collects those ids from this
                                run's jobs API, POSTs event_type codeql-scan
                                once with the remaining language matrix and
                                required_jobs: [{language, job_id}, ...], and
                                fails closed if any shard job id is missing.
                                Skips the POST when every language already
                                has a terminal verdict. Later workflow
                                attempts repeat this evidence test instead of
                                treating run_attempt as a dispatch receipt.

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
                                success/failure/error, description binding the
                                exact head and workflow, target_url pointing
                                at this .github run's own log for full evidence.
                              -- Upload the SARIF as an artifact on this
                                .github-side run for audit trail (mirrors
                                strix.yml's "Preserve CodeQL SARIF evidence"
                                / artifact retention today).
                              -- After every language has a trusted terminal
                                receipt, re-fetch the open PR, exact required
                                workflow run, and every exact failed language
                                job. Require the failed-job set to equal the
                                1:1 language map before calling the exact run's
                                rerun-failed-jobs endpoint. A concurrent wake
                                counts only after newer attempts for every
                                mapped job are proved. Missing, stale, closed,
                                extra-failed, or mismatched identity fails closed.
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
matrix. Each scan job analyzes and preserves its run/attempt SARIF artifact
with `actions: read`. A single non-matrix settlement job runs after all shards
and alone receives `actions: write`; it validates every language before it can
change the shared required run. One language's failure cannot cancel or skip a
sibling, and no matrix shard independently changes shared run state.

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
superseded. The sibling-cancel failure mode is gone because siblings are
jobs in one run, not runs in one concurrency group. `required_jobs` is a 1:1
map of language to canonical job id, and a missing, stale, or mismatched
identity still fails closed. The old scalar
`required_job_id`/`required_language` payload is retired.

#### 2026-09-08 amendment: exact-run settlement resolves the two-language wake race

Central handler runs `34077342761` (actions) and `34077321864` (Python) both
passed their finding, SARIF-preservation, and base-bound publication gates for
required run `34071540279`. Actions woke job `101632671065`; Python then tried
to wake job `101632672530` and GitHub returned HTTP 403 because the shared run
was already running. Per-job callbacks therefore could not converge.

The selected repair uses one non-matrix settlement job after every mapped
language has terminated. It validates every original failed job plus the
required run path/head, rejects any failed job outside that exact map, and
then reruns failed jobs on that exact run. The pending scan matrix contains
only languages without a trusted terminal receipt, but `required_jobs` keeps
the complete failed compatibility-job set for run-wide settlement. Thus a
trusted receipt suppresses a redundant scan without removing that language's
failed job from the exact rerun authority. Every pending language must still
map to one of those failed jobs. If a concurrent settlement wins,
the loser succeeds only after the jobs API proves a newer attempt for every
mapped language; a bare 403 is still failure. Issuing an unbound run-wide
rerun, accepting `already running` without evidence, polling, and restoring
per-language dispatch runs were rejected because they respectively broaden
authority, lose the callback, occupy runners, or recreate the 60-job ceiling.

#### 2026-09-08 amendment: self-repository status fallback has run provenance

When the target is `ContextualWisdomLab/.github`, the OpenCode App token can
complete the scan but receive HTTP 403 while publishing the commit status.
The handler's own `GITHUB_TOKEN` may publish that self-repository status as
`github-actions[bot]`; accepting that creator globally would let any status
writer forge the context and is forbidden.

The narrow fallback is accepted only for the `.github` target and handler.
Every receipt description carries the exact required-run ID. The consumer
resolves the numeric central run URL and verifies the unique
`repository_dispatch` workflow path, protected `main` source SHA, app actor and
triggering actor, generated run title bound to target/PR/head/base/required run,
the successful validation job, the terminal language gate, and its successful
SARIF upload plus unexpired exact run/attempt artifact. The handler's settlement
step may accept its own current-run receipt because it executes inside that
already-authenticated run. If every status POST is forbidden, the same complete
current-run evidence is sufficient without a receipt; this preserves fail-closed
identity while avoiding a circular dependency on `statuses:write`. Every other
target still requires either an OpenCode App receipt or that exact direct
evidence. Run discovery, exact job proof, and exact artifact proof consume every
paginated response; the first 100 objects are not an evidence boundary. Missing
or mismatched provenance remains pending/failure; creator,
URL, or a bare HTTP 403 alone is never enough.

The verification above applies equally to an OpenCode App receipt. App creator
identity admits a candidate for validation; it does not replace producer
evidence. This prevents a correctly authenticated but premature or misbound
status from becoming a terminal verdict before the exact language job and
SARIF artifact exist. The `github-actions[bot]` path retains its additional
self-repository restriction.

A retry may create more than one handler run with the same bound title. Shard
and coordinator consumers therefore do not use title-count uniqueness as
evidence. They fully authenticate every candidate's run metadata, source
ancestry, exact language gate, SARIF preservation, and unexpired run/attempt
artifact, then require exactly one evidence-complete candidate. An incomplete
predecessor cannot hide its complete successor; two complete candidates remain
ambiguous and fail closed.

The target pull request base SHA (`A`) and central handler workflow source SHA
(`S`) are separate identities. `A` binds the result to the target review base;
`S` is the immutable `github.workflow_sha` of the required workflow that made
the dispatch. The producer passes `S` in the payload and binds it into the
handler title and terminal receipt. Because `repository_dispatch` selects its
receiver from the default branch, handler runtime source `T` can advance after
the required run fixed `S`. Admission and every direct-evidence consumer accept
either `S == T` or GitHub compare evidence that `S` is the exact merge base of
`T`, `T` is ahead, and it is not behind. This keeps the immutable producer
identity while allowing a later protected-main receiver to preserve the
validated payload contract. Divergent, reversed, missing, malformed, or
unverifiable ancestry fails closed. Moving either repository's `main` ref after
run creation cannot substitute for the immutable run `head_sha`; comparison is
between the two recorded commit objects. Run 34186647327 returned an empty
`referenced_workflows` array, so that optional field is deliberately excluded
from source authority.

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
- **Run-wide rerun authority:** `rerun-failed-jobs` is allowed only when the
  required run is the exact pull-request run/path/head, every mapped original
  failed compatibility job remains in the settlement map even when its
  language already has a trusted receipt, every pending language maps to an
  exact failed job, every language has either a trusted
  head/base/workflow/required-run receipt or exact validated central-run gate
  and artifact evidence, and the complete failed-job set equals that map. A
  concurrent call is accepted only with exact newer-attempt evidence. Only the
  one non-matrix settlement job has `actions: write`.
- **Central source authority:** the payload, handler title, and receipt agree on
  immutable producer source `S`; the exact handler run records runtime source
  `T`. Every consumer requires `S == T` or exact GitHub compare proof that `S`
  is `T`'s merge base and `T` is strictly ahead without being behind. Neither
  identity is inferred from target base `A`, a mutable branch tip, or optional
  `referenced_workflows` metadata.

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
- **Wake each failed language job independently:** rejected after the
  2026-09-08 two-language reproduction; GitHub moves the whole workflow run
  back to running after the first job wake and rejects the sibling callback.

## Risks and effects

- Adds one new workflow file and one new `scripts/ci/codeql_sarif_gate.py`
  module (with its own test file, contributing to the 100%-coverage
  requirement on `scripts/ci/`) to the org's central CI surface — more
  surface area to maintain, offset by removing ~70 lines of duplicated
  inline Python between `analyze-head`/`analyze-merge` today.
  exact run/job settlement follows the OpenCode runner-release pattern while
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
3. Rewrite `codeql-pr.yml`'s `analyze-head` job into the dispatch+exact-run-settlement shape;
   delete `analyze-merge` (tracked as future work, not silently lost — this
   ADR is the record).
4. Add a permanent contract test asserting no `codeql-action` reference
   exists anywhere in `codeql-pr.yml`.
5. Only then, re-add `.github/workflows/codeql-pr.yml` to ruleset `18156473`'s
   required `workflows` list (admin:org PUT, same mechanism used to remove
   it) and verify a real PR observes a successful, correctly-named required
   check before declaring this ADR's status Accepted.
