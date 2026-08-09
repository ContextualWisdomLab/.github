# Technical requirements: CWL automation control plane

Status: normative technical contract. See
[TRACEABILITY.md](TRACEABILITY.md) for implementation evidence.

## System boundary

The central repository owns trusted workflow definitions, review and merge
decision helpers, sandboxed evidence tooling, organization audit logic, and
shared tests. Target repositories own product source, repository-specific
tests, branch policy, and thin enrollment/caller configuration. GitHub owns the
event bus, rulesets, formal review objects, check runs, statuses, refs, and
merge transaction.

## Trigger and event semantics

| Path | Trusted entrypoint | Purpose | Mutation authority |
|---|---|---|---|
| Required review bootstrap | `.github/workflows/opencode-review.yml` | Stable ruleset context; no PR code execution | None |
| Privileged OpenCode review | `.github/workflows/opencode-review-dispatch.yml` | Default-branch authenticated exact-head evidence and formal model review | Review publication only through configured identity; scheduler follow-up is separate |
| Noema review | `.github/workflows/noema-review.yml` | Independent advisory review with App/OIDC/PAT credential selection | Formal review publication by Noema identity |
| Strix evidence | `.github/workflows/strix.yml` | Exact-head changed-path security evidence | Status/check publication; no merge authority |
| Merge scheduler | `.github/workflows/pr-review-merge-scheduler.yml` | Classify current PR state, dispatch missing evidence, update/merge with guards | Explicit job-scoped mutation credential |
| Autofix scheduler | `.github/workflows/pr-review-fix-scheduler.yml` | Select conservative current-head repair candidates | Dispatch only |
| Autofix worker | `.github/workflows/pr-review-autofix.yml` | Produce a validated source repair on one same-repository PR head | Branch write only after repeated snapshot guards |
| Fleet auditor | `.github/workflows/audit-central-ruleset.yml` | Read organization ruleset enrollment and drift | Read-only by policy |
| Mention router | `.github/workflows/agent-mention-router.yml` | Validate trusted comments and enqueue bounded review requests | Repository dispatch only |

On the audited protected main, Strix concurrency is scoped by event,
repository, and PR number and uses `cancel-in-progress: true`. A replacement in
the same event class cancels its predecessor and resolves the current PR head
when it executes. `repository_dispatch` and `pull_request_target` are distinct
event classes so one cannot cancel the other's required-check context. This is
the executable behavior, replacing older prose that described head-SHA-scoped,
non-cancelling Strix runs.

`pull_request_target` entrypoints must use protected-base workflow code and must
not execute PR-controlled source while holding secrets or write permission.
Privileged execution is moved to a default-branch `repository_dispatch` path
that re-fetches live PR metadata. `workflow_call` is used only when its explicit
inputs and secret contract are sufficient; callers cannot select an unreviewed
privileged implementation ref.

## Revision identity

A `pull_request_snapshot` is valid only for one tuple:

`(repository, pr_number, source_ref, source_head_sha, base_branch, live_base_sha, observed_at)`.

- `source_head_sha` is the exact source revision under review.
- `base_branch` is the target ref name.
- `live_base_sha` is resolved independently from the current base ref at the
  decision boundary. A PR API base snapshot is historical evidence, not an
  alias for the current protected ref tip.
- The scheduler's compare-API path resolves branch freshness from the base ref
  and head ref. Mutating actions additionally use expected-head or
  `--match-head-commit` protection.
- Any source-head movement invalidates predecessor checks, statuses, reviews,
  test claims, and merge simulation. Any live-base movement requires a new
  freshness and mergeability decision.

The strict three-key `cwl.agent-invocation/v2` dispatch envelope and
snapshot-only review route are **pending** in
`ContextualWisdomLab/.github#840`; they are not protected-main behavior in this
baseline. Until integrated, existing dispatch fields remain subject to the
same identity requirements and GitHub's ten-property `client_payload` limit.

## Evidence and authority taxonomy

| Evidence class | What it proves | What it cannot authorize |
|---|---|---|
| Check evidence | A named check run evaluated a revision and concluded a state | Formal approval, merge, release |
| Status evidence | A producer published a context/state for a commit | Formal approval or replacement of a required check |
| Workflow evidence | A workflow/run/job executed from a known provenance with recorded inputs | Correctness outside the observed scope |
| Formal review evidence | GitHub recorded a review by a named identity on a head | Merge unless reviewer eligibility and all other gates pass |
| Dependency evidence | A predecessor/base/reusable-workflow condition is satisfied | Product correctness |
| Operational acceptance | Protected-main behavior succeeded in an enrolled real consumer | Universal fleet health |

Check evidence, status evidence, workflow evidence, and formal review evidence
remain separate records. Merge authority belongs only to the guarded scheduler
or GitHub native merge transaction under ruleset enforcement. Release authority
belongs to the repository release workflow/environment and is never implied by
review approval. Deployment authority is separately scoped. A model verdict is
advisory content until an eligible identity creates the required GitHub object.

## Review and merge gates

The same exact head must satisfy all applicable gates:

1. PR is open, non-draft when policy requires, and has valid repository/ref/SHA
   identity.
2. The live base and mergeability state are freshly resolved.
3. Required checks and security/provenance gates are successful; pending,
   skipped-required, cancelled, absent, neutral-required, action-required,
   predecessor-head, or synthetic-only states are not success.
4. No valid unresolved review thread or current-head change request remains.
5. Automated OpenCode/Noema/Strix evidence is current-head when required.
6. Ruleset-required counted non-author approval is present and not stale.
7. The final mutation compares the expected head. A head mismatch aborts.

The organization ruleset auditor's executable contract requires exactly two
eligible approving reviews for enrolled repositories, stale-review dismissal,
last-pusher protection, and review-thread resolution. Historical rollout
entries showing zero or one review are dated migration evidence. The central
`.github` repository's missing reliable counted-independent-review path remains
tracked by `ContextualWisdomLab/.github#772`; automation cannot self-satisfy it.

The configured `code-reviewer` model subagent can read, grep, glob, and list
trusted bounded evidence. Bash, task/subagents, network, LSP, MCP,
external-directory access, edits, installation, and mutation are denied.
Execution receipts are prepared by the trusted workflow, not run by the model.

## Permissions, identities, and secrets

- Workflow defaults are `contents: read`; jobs elevate only the permissions
  they use.
- `id-token: write` is job-scoped to OIDC exchange paths.
- GitHub App installation tokens are repository-scoped and short lived.
- PAT-like fallbacks (`PR_REVIEW_MERGE_TOKEN`, `OPENCODE_APPROVE_TOKEN`,
  `NOEMA_REVIEW_TOKEN`) are compatibility paths, not justification for broader
  permissions.
- The scheduler prefers `github.token` for same-repository mechanical work but
  still implements an exchanged repository-scoped OpenCode App token in its
  cross-repository credential chain. It is not described as removed.
- `NVIDIA_NIM_API_KEY` is exposed only to a real model-call step. Deterministic
  metadata, eligibility, open-PR, syntax, and release gates precede model-secret
  materialization.
- `COPILOT_GITHUB_TOKEN` is not an accepted development-agent credential.
- Reusable workflows define named secret requirements. Blanket
  `secrets: inherit` is a migration gap where still present, including the
  current Cloudflare Pages caller guidance.
- Reviewer, writer, merger, releaser, and deployer identities are independently
  auditable and must not be collapsed to make a gate pass.

The complete current secret-name inventory, purpose, owner, absence behavior,
and rotation/revocation contract is maintained in [SECURITY.md](SECURITY.md).

## Audited implementation state and gaps

Protected main currently centralizes seven required workflows through ruleset
`18156473`: close-empty PR, Noema, OpenCode, merge scheduler, security scan,
Strix, and Semgrep. `scripts/ci/audit_central_required_workflows.py` detects
drift and review-rule weakening but does not mutate or repair the ruleset.
The audited paths are `.github/workflows/close-empty-pr.yml`,
`.github/workflows/noema-review.yml`, `.github/workflows/opencode-review.yml`,
`.github/workflows/pr-review-merge-scheduler.yml`,
`.github/workflows/security-scan.yml`, `.github/workflows/strix.yml`, and
`.github/workflows/sast-semgrep.yml`.

| ID | Audited protected-main behavior | Required closure |
|---|---|---|
| IG-001 | Mention wrappers validate review-only flags and exact identity, but the authoritative OpenCode/Noema route does not preserve every flag/SHA through the final review boundary. | End-to-end strict dispatch snapshot, live-base, and review-only semantics in `ContextualWisdomLab/.github#840`. |
| IG-002 | Noema is a distinct review identity; its handoff is non-blocking, and the merge scheduler checks generic formal approval/ruleset state rather than requiring that identity. | Reliable counted independent non-author review in `ContextualWisdomLab/.github#772`. |
| IG-003 | Privileged scheduler/OpenCode/Strix targeted dispatch rejects external heads, while older policy prose described them as reviewable. | Select one safe product contract and align all entrypoints in `ContextualWisdomLab/.github#889`. |
| IG-004 | Per-workflow concurrency, immutable invocation claims, and mutation head guards exist; there is no shared writer owner/TTL/heartbeat/fencing record across merge, autofix, and rebase workflows. | Durable cross-workflow writer lease in `ContextualWisdomLab/.github#890`. |
| IG-005 | A provider/backend outage can produce a skipped or neutral Strix shape without authoritative scan evidence. | Terminal fail-closed security evidence gate in `ContextualWisdomLab/.github#891`. |
| IG-006 | The scheduler prefers the workflow token for same-repository work but still selects an exchanged OpenCode App token; merge-mode/state policy is not one machine-checked table. | Align mutation credentials and merge modes in `ContextualWisdomLab/.github#892`. |
| IG-007 | Mention artifacts are claimed before forwarding; failure after claim is at-most-once dead-letter behavior and requires a new comment during the 30-day claim window. | Recoverable claim state/fencing in `ContextualWisdomLab/.github#893`. |
| IG-008 | The scheduler preserves queue progress by recording PR-local mutation failures as `action_error`, but its CLI still returns success after the scan. | Preserve the structured summary and make material action failures terminally non-passing in `ContextualWisdomLab/.github#894`. |

These gaps are non-passing where their stronger target contract is required.
They must not be inferred as implemented from the PRD, ADR acceptance status,
UML, ERD, FigJam, or prompt.

## Failure classification and retry

| Class | Examples | Response |
|---|---|---|
| Transient infrastructure | GitHub 5xx, bounded DNS/network reset, runner allocation delay | Bounded retry with jitter or documented fallback; retain original evidence |
| Provider capacity | Model timeout, rate limit, exhausted pool | Try a distinct configured provider within budget; otherwise defer without approval |
| Permanent input | Malformed repo/ref/SHA, unsupported payload shape, size/property limit | Fail closed; repair producer/contract |
| Integrity/security | Digest mismatch, untrusted workflow ref, checksum/signature failure, TLS validation failure | Immediate fail closed; no blind retry |
| Authority | 401/403, missing installation, ineligible reviewer, ruleset denial | Defer affected action; obtain legitimate authority or continue another lane |
| Product/source | Test, security, compatibility, migration, or behavior failure | RCA, realistic RED, narrow fix, GREEN, full relevant verification |

Retries are capped by attempt count and wall-clock budget. Repeated identical
failure does not become evidence of success. Three materially distinct failed
remedies across layers trigger architecture reassessment.

## Concurrency and writer leases

The policy unit of source-write ownership is `(repository, branch)`. Before
every write, the actor re-fetches the target ref, PR state, review state, and
base tip. A source-affecting move freezes writes to that branch for the run.
Read-only fleet audit, different branches, and different repositories may
continue. The current per-workflow controls do not globally serialize different
writer workflows; the durable lease implementation is tracked in
`ContextualWisdomLab/.github#890`.

Concurrency groups may cancel predecessor work only when doing so cannot allow
a stale request to cancel or replace newer valid evidence. A queued or running
review is a deferred state, not a repository-wide lock. The work-conserving
automation contract is specified in
[ADR-0007](adr/0007-work-conserving-automation.md).

## Diagnostics and PII

Sandboxed commands scrub ambient credentials and publish bounded structured
result markers. Credential-shaped values in stdout, stderr, timeout evidence,
and service logs must be redacted before publication while retaining the
ordinary error, exit code, timeout, failing step, and useful non-secret tail.
The replacement implementation is pending in
`ContextualWisdomLab/.github#842`.

PII is not indiscriminately masked when doing so prevents review or incident
response. Instead use least-privilege access, purpose limitation, bounded
retention, encrypted transport/storage, audience-scoped disclosure, and audit
records. Secrets and authentication material are never treated as ordinary PII.

## Protected-main acceptance

Source merge is integration evidence, not operational closure. A central
workflow repair closes its incident only after an enrolled consumer executes
the protected-main path and records target repository, workflow source,
source-head, live-base, run/job identity, conclusion, and recovery behavior.
