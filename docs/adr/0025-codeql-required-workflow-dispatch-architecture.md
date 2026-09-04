# 0025 — Restore central CodeQL as a required workflow via repository_dispatch

**Status:** Proposed · **Date:** 2026-09-03 · **Owner intent recorded:** loop-brief item 41

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
status`) and `opencode-review.yml` (`Request current-head OpenCode review
execution` dispatch + `Fail closed without a current-head OpenCode verdict`
bounded poll). Concretely:

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
  analyze-head (matrix)     -- RENAMED INTERNALLY, SAME REQUIRED-CHECK NAME:
                                "CodeQL compatibility analysis (${{ matrix.language }})".
                                needs: [detect-languages, dispatch-analysis].
                                No codeql-action reference. Polls (bounded
                                wall-clock deadline + transport-failure
                                tolerance, identical shape to opencode-review.yml's
                                poll loop) for a commit status posted by the
                                dispatch handler at context
                                "codeql-dispatch/${{ matrix.language }}" on
                                the live PR head SHA, re-validating live PR
                                head/state each iteration exactly like
                                opencode-review.yml's poll does (a superseded
                                head must retire this poll, not report a
                                stale result). Reflects the polled
                                conclusion as this job's own exit code.

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
                                "codeql-dispatch/<language>" using the
                                target-scoped token (identical mechanism to
                                strix.yml's "Publish same-head manual Strix
                                status" multi-token fallback chain), state
                                success/failure, description carrying a short
                                finding count, target_url pointing at this
                                .github run's own log for full evidence.
                              -- Upload the SARIF as an artifact on this
                                .github-side run for audit trail (mirrors
                                strix.yml's "Preserve CodeQL SARIF evidence"
                                / artifact retention today).
```

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
  step and `opencode-review.yml`'s poll-time revalidation. A forged or stale
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
- **Poll target cannot be spoofed by the PR author:** a commit status is
  writable by anyone with `statuses:write` on the repository (including,
  depending on token scoping, a workflow running with the default
  `GITHUB_TOKEN` in some configurations) — confirm during implementation
  that the polling job in `codeql-pr.yml` verifies the status update's
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
  the `pr_review_merge_scheduler.py`-scale poll/dispatch pattern is already
  proven at scale (Strix, OpenCode, Noema all use it today) and this is the
  fourth application of the same design, not a new pattern to validate from
  scratch.
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
3. Rewrite `codeql-pr.yml`'s `analyze-head` job into the dispatch+poll shape;
   delete `analyze-merge` (tracked as future work, not silently lost — this
   ADR is the record).
4. Add a permanent contract test asserting no `codeql-action` reference
   exists anywhere in `codeql-pr.yml`.
5. Only then, re-add `.github/workflows/codeql-pr.yml` to ruleset `18156473`'s
   required `workflows` list (admin:org PUT, same mechanism used to remove
   it) and verify a real PR observes a successful, correctly-named required
   check before declaring this ADR's status Accepted.
