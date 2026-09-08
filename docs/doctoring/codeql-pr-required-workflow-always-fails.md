# `codeql-pr.yml` as a required workflow can never succeed — removed from the ruleset

## 2026-09-09 handler-first schema cutover

### Problem and exact evidence

The proposed producer in `.github#2040` emits rerun identity as
`rerun_request: {mode, required_jobs}`. Protected
`main@7fd571dbcdbae6acf29d8f4ee704d7ba6297e4db` still consumes only the legacy
top-level fields. CodeQL run `34249195529` therefore reached handler run
`34249932036`, but validation job `102141468869` observed
`SUPPLIED_REQUIRED_JOBS: null` and rejected the request. Deploying producer
and consumer in one PR cannot repair that first invocation: the dispatch
handler always executes from protected `main`.

### Constraints and decision

The handler must remain fail closed, retain queued legacy messages, and issue
no duplicate mutations. A producer-side compatibility shim was rejected
because it leaves the protected consumer unable to validate the new contract;
an admin bypass or synthetic status was rejected because neither repairs the
protocol. The selected predecessor changes only the handler: accept either
the nested or legacy representation, reject any mixed representation, and
move settlement after the complete scan matrix so exactly one job owns the
run-level rerun request.

### Operational scene, risks, and follow-up

When a pull request's CodeQL shards return `verdict=pending`, the handler
validates the exact repository, PR, head, base, required run, and job set, then
submits one `failed` or `all` rerun for that attempt. Conflicting identities
stop before checkout or mutation. The compatibility surface is deliberately
temporary: after this predecessor merges ordinarily and queued legacy payloads
age out, `.github#2040` can be non-force restacked and the legacy inputs can be
removed in a separately reviewed cleanup. Until then this decision is
**Proposed**, not deployed capability.

## Incident

Loop-brief item 41 ("PR Run Failed at startup 류는 모두 해소하라", example:
`ContextualWisdomLab/wardnet` run `33710719228`) traced to a platform-level
GitHub restriction, not a configuration bug in this repository. Every
ruleset-injected run of `CodeQL PR` (`.github/workflows/codeql-pr.yml`,
dispatched via the org required-workflow ruleset `18156473`) observed across
every sampled repository — `wardnet` (8/8), `naruon` (4/4),
`contextual-orchestrator` (6/6), `keyverse` (8/8), `html4tree` (9/9), plus
`bandscope`/`aFIPC`/`pg-erd-cloud`/`xtrmLLMBatchPython` per an earlier,
independent investigation the same day — ends in `startup_failure` with
**zero check runs created**. The success rate across every repository
sampled is 0/43+.

## Root cause

The REST API exposes no reason for a `startup_failure` on a required-workflow
run (empty `jobs` array, no error field). The reason is only visible in the
GitHub web UI's run page under "Annotations":

> The following actions are not allowed to be used inside a required
> workflow: `github/codeql-action/analyze@<sha>`,
> `github/codeql-action/init@<sha>` (both `init` and `analyze` cited twice,
> once per job that uses them — `analyze-head` and `analyze-merge`).

This is a documented GitHub platform limitation, not specific to this org or
this pinned version: CodeQL's `init`/`analyze` actions are categorically
disallowed inside a "required workflow" (the same restriction applies to the
legacy repository-level required-workflows feature and to a ruleset's
`workflows` rule type, which is the mechanism `18156473` uses), because
"CodeQL requires configuration at the repository level" that a
centrally-dispatched required workflow cannot provide
(github.com/google/github-team#5, GitHub's own stated reason). There is no
official workaround that keeps CodeQL invoked directly inside a
required-workflow file — any exact SHA pin will hit the same restriction,
confirmed by resolving the cited SHA (`db488ddef3bf6cb639b32c2e9a7c0a7ea8271d28`)
to a real, valid `codeql-action` v4.37.8 release commit.

## Why this was worse than "one broken check"

`18156473`'s `pull_request` rule requires 1 approving review and its
`workflows` rule required `codeql-pr.yml` among nine others, with no
`do_not_enforce_on_create` exemption applying to ongoing merges (that
parameter only affects whether a check blocks *branch/PR creation*, not
merge eligibility). A required check that always resolves to a terminal
`startup_failure` is not "pending forever" — it is a required, always-failing
status, meaning **every ordinary (non-admin-bypass) merge attempt on every
non-excluded repository in the organization was blocked by a check that
could never pass**, independent of and in addition to the separately
diagnosed Actions plan concurrency ceiling
([[project-actions-plan-concurrency-ceiling]]) and per-repo Strix starvation
([[project-strix-concurrency-starvation-unfixed]]). Every merge that landed
today on a ruleset-covered repository did so via `OrganizationAdmin` bypass,
not because this check ever genuinely passed.

## Coverage is not zero, though

Some repositories already carry GitHub's native "code scanning default
setup" independently of this ruleset (`wardnet`: confirmed
`code_scanning_default_setup: {state: "configured", languages: ["actions",
"rust"]}`, producing real, successful `Analyze (<language>)` check runs
under `event: "dynamic"`, `path: "dynamic/github-code-scanning/codeql"` —
naruon shows the same pattern). These are a *different* mechanism from
`codeql-pr.yml` (different check names: `Analyze (X)` vs. `CodeQL
compatibility analysis (X)`) and were unaffected by this fix. Coverage
outside those repositories is a real, separate, still-open gap — this fix
removes an always-failing gate, it does not add coverage where none existed.

## Fix applied

Removed `.github/workflows/codeql-pr.yml` from ruleset `18156473`'s
`workflows` rule via `PUT /orgs/ContextualWisdomLab/rulesets/18156473`
(all nine other required workflows, the `pull_request`/`deletion`/
`non_fast_forward` rules, and `bypass_actors` left untouched — diffed the
before/after JSON to confirm only the one array entry changed).
`codeql-pr.yml` itself is untouched in this repository; only its membership
in the required-workflow list changed, since the file cannot function in
that role regardless of its own content.

## Recommended follow-up (not done here)

Restoring real central CodeQL coverage requires the same architecture
already proven by `strix.yml`/`opencode-review.yml`: a thin required-workflow
entrypoint (safe subset only — language detection, changed-path
classification, no `codeql-action` calls) that dispatches the actual
`init`/`analyze` work via `repository_dispatch` to a workflow that runs
*natively* in `.github`'s own context (not subject to the required-workflow
restriction), which checks out the target repository's PR head with a scoped
token and publishes the `CodeQL compatibility analysis (<language>)` /
`CodeQL merge preview (<language>)` check-run or commit-status contexts back
onto the target repository, mirroring `strix.yml`'s
`Publish same-head manual Strix status` step. This is a substantial,
carefully-scoped rewrite (dynamic per-language check names, target-repo
checkout security boundary) deliberately not attempted in the same tick as
the emergency ruleset fix above — tracked as a follow-up, not silently
dropped.
