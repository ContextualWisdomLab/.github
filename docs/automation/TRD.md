# Technical requirements — CWL automation control plane

Status: accepted baseline
Last reviewed: 2026-08-10

## 1. System boundary

The control plane consists of trusted workflows in `.github/workflows/`, their helpers in `scripts/ci/`, organization/repository rulesets, GitHub API state, and thin caller workflows. The hourly maintainer policy selects work but is not an evidence authority. Product source and tests remain in each product repository.

Normative keywords **MUST**, **MUST NOT**, **SHOULD**, and **MAY** describe intended contracts. [TRACEABILITY.md](TRACEABILITY.md) identifies contracts that are not yet fully enforced.

### Requirement identifiers

| ID | Normative boundary |
|---|---|
| `TRD-EVT-01` | Trigger trust and live dispatch validation (§2) |
| `TRD-REV-01` | Exact source, live base, workflow, run, and merge identity (§3) |
| `TRD-AUTH-01` | Evidence-class and merge-authority separation (§4) |
| `TRD-RUN-01` | Work-conserving lifecycle and double exit sweep (§5) |
| `TRD-WRITE-01` | Branch-local writer lease and expected-head mutation (§6) |
| `TRD-SEC-01` | Least permission, explicit secret purpose, and PII controls (§7) |
| `TRD-RETRY-01` | Classified bounded retry and timeout behavior (§8) |
| `TRD-LOG-01` | Complete-boundary sandbox redaction and diagnostic preservation (§9) |
| `TRD-IF-01` | Versioned checks, dispatches, workflow calls, results, and receipts (§10) |
| `TRD-RET-01` | Purpose-limited evidence retention and deletion (§11) |

## 2. Trigger and execution semantics

| Trigger | Intended use | Trust requirement |
|---|---|---|
| `pull_request_target` | Metadata-only required contexts and trusted base-branch policy | MUST NOT check out or execute PR-controlled source with write credentials or secrets. |
| `pull_request` | Unprivileged exact-head source tests | Fork restrictions and read-only credentials MUST remain effective. |
| `repository_dispatch` | Default-branch privileged review, fix, retry, or agent invocation | Payload, actor, repository, PR number, head/base identity, and allowed operation MUST be validated against live state. |
| `workflow_run` | Re-evaluate after a named upstream workflow | Artifacts and reported SHAs MUST be treated as untrusted until rebound to live PR identity. |
| `workflow_call` | Stable thin consumer contract | Inputs and secrets MUST be explicit, minimal, versioned, and documented. |
| `schedule` | Queue sweep, full-tree security scan, inventory, or recovery | MUST use protected default-branch source and idempotent bounded work. |
| `issue_comment` | Authorized agent invocation in repositories where a default-branch router exists | Author association, exact comment identity, canonical payload, and replay ledger MUST be validated. |

The event cadence of GitHub workflows is independent of the hourly commercial-maintenance cadence. A scheduled maintainer run MUST derive actions from live GitHub state; it MUST NOT infer acceptance from its recurrence or memory.

## 3. Revision identity

Each decision record MUST distinguish:

- `source_revision`: the exact immutable PR head commit under review;
- `base_revision_snapshot`: the PR API's recorded base SHA for historical context;
- `live_base_revision`: the current protected base-ref tip resolved independently at decision time;
- `workflow_revision`: the immutable trusted workflow/script revision;
- `run_id` and `run_attempt`: workflow execution identity; and
- `merge_revision`: the integrated or merge-group revision when applicable.

An exact-head result proves only the source revision it names. It does not prove compatibility with a later base tip. A synthetic merge result MUST be labeled as such and MUST NOT silently substitute for source-head evidence. Any source-head change invalidates predecessor checks, reviews, and approvals unless GitHub policy explicitly and authoritatively preserves a still-applicable approval.

## 4. Evidence taxonomy and authority

| Evidence class | Examples | May establish | May not establish |
|---|---|---|---|
| `check_evidence` | GitHub Check Run, required workflow job | Deterministic gate outcome for its named revision | Human approval or merge authority |
| `status_evidence` | Commit status context, CodeRabbit status | External service signal for its named commit | Formal review or branch-protection satisfaction unless configured as required |
| `review_evidence` | Formal `APPROVED`, `CHANGES_REQUESTED`, inline thread | Reviewer decision, author, commit, and thread state | Test success or scanner execution |
| `model_evidence` | OpenCode, Noema, Strix finding/output | Advisory analysis or a configured machine gate | Qualifying human identity |
| `workflow_evidence` | Run, job, attempt, artifact receipt | Execution provenance and result | Correct source binding without validation |
| `dependency_evidence` | Upstream PR/release/attestation | Dependency state | Current consumer compatibility without consumer proof |
| `operational_acceptance` | Protected-main or real-consumer run | Runtime closure for a stated scenario | Unrelated scenarios or future revisions |

Merge authorization MUST be the intersection of actual repository policy, required current evidence, current mergeability, zero actionable unresolved threads, expected-head semantics, and qualifying reviews. No single evidence producer may redefine another authority class.

## 5. Work-conserving run lifecycle

1. Refresh repository, pull-request, issue, exact revision, gate, ruleset, and writer state.
2. Build separate lanes for mergeable PRs, defects, operations, issues, documentation, automation drift, and bounded product gaps.
3. Select the highest-value safe item.
4. For a defect, establish RED evidence before production repair when feasible.
5. Identify symptom, immediate cause, root cause, owner, distinct remedies, and feasibility.
6. Acquire or confirm a branch-local writer lease immediately before mutation.
7. Apply the smallest cohesive change; preserve unrelated user and writer changes.
8. Run focused and complete verification; bind hosted evidence to the new exact head.
9. Merge only under repository policy; then run protected-main or consumer acceptance when required.
10. Update authoritative documentation and immediately choose the next item.
11. Before stopping, perform a fresh whole-queue sweep. If it finds work, execute it and sweep again.

Pending checks, reviewer latency, rate limits, or provider cooldowns are deferred states, not whole-run blockers.

## 6. Writer lease and mutation contract

A `writer_lease` is branch-local and identifies repository, branch/ref, expected head, actor, scope, acquisition time, and expiry/heartbeat. Immediately before a source, ref, or PR-state write, the writer MUST re-fetch the target head/base and relevant writer state. Movement outside the expected lineage aborts the write.

Writers MUST NOT force-push shared history, manufacture one-shot write workflows, synthesize approval, weaken required gates, or race another write-capable actor. Read-only review and checks do not themselves constitute a writer conflict. A blocked branch MUST cause rotation to another non-conflicting lane when useful work exists.

## 7. Permissions and secrets

- Workflow and job `permissions` MUST default to read-only and be expanded only at the step/job that requires the capability.
- Cross-repository writes SHOULD use short-lived OIDC/App authority with audience and repository restrictions.
- Long-lived tokens are compatibility fallbacks, not the preferred architecture; their names and scopes MUST remain stable until a reviewed migration.
- Reusable workflows MUST declare explicit secret contracts. Blanket `secrets: inherit` MUST be removed where the callee needs fewer secrets. The current `deploy-pages.yml` inherited-secret caller pattern is a documented legacy exception and not a template for new workflows.
- `NVIDIA_NIM_API_KEY` MAY enter only model-execution jobs. It MUST NOT be supplied to deterministic tests, source materialization, checkout, artifact inspection, or anonymous/free model execution.
- `COPILOT_GITHUB_TOKEN` MUST NOT be used for autonomous development.
- Tokens and allowed environment values MUST be registered with the evidence redactor before any potentially colliding output is emitted.
- PII is not a generic secret token. Business-required PII MUST be protected by access, purpose, audience, retention, and audit controls rather than indiscriminate content masking.

## 8. Failure classification, retry, and timeout

| Class | Examples | Retry contract |
|---|---|---|
| Transient infrastructure | bounded DNS failure, connection reset, GitHub 5xx, runner acquisition failure | MAY retry with a small bounded count, backoff/jitter, total time budget, and preserved final evidence. |
| Provider capacity | rate limit, documented temporary capacity exhaustion | MAY defer or rotate provider; MUST NOT convert exhaustion to approval. |
| Integrity/authentication | checksum mismatch, invalid signature, OIDC audience mismatch, bad token | MUST fail immediately and closed; no speculative retry with broader authority. |
| Authorization/policy | 401/403, disallowed actor/repository, missing required approval | MUST fail/defer with exact prerequisite; MUST NOT invent authority. |
| Revision/ref/schema | head moved, ref missing, malformed payload, unsupported schema | MUST fail immediately, refresh state, and re-plan. |
| TLS/supply chain | certificate failure, immutable pin mismatch, unexpected redirect/origin | MUST fail immediately and closed. |
| Product/test defect | assertion, compile, lint, coverage, behavior failure | Requires RCA and source repair; rerun alone is not remediation. |

Every retry loop MUST state attempt count, per-attempt timeout, total budget, retryable classification, and final failure output. Long model reviews MAY receive hours when accuracy requires it, but a running model job cannot reserve the maintenance invocation.

## 9. Evidence output and sandbox redaction

Evidence publication includes human stdout/stderr, timeout payloads, exceptions, service log tails, command metadata, job summaries, comments, artifacts, and structured result markers. Each publication path MUST use the same canonical redaction boundary before truncation or serialization.

The redactor MUST:

- detect supported credential assignments, authorization/cookie forms, private-key material, provider tokens, JWT-like values, URL userinfo, explicit allowed values, and separated/nested command options;
- canonicalize terminal/Unicode control evasions before detection;
- parse supported JSON structurally, preserve benign keys/types, and redact sensitive string values without corrupting valid JSON;
- preserve ordinary diagnostic text, stream identity, exit code, stable result keys, and valid one-line result JSON;
- prevent cross-stream, marker, and result-boundary reassembly of an allowed value;
- reject unsafe short, whitespace-only, non-printable/control-bearing,
  marker-colliding, or wrapper-owned allowed values before execution without
  emitting colliding evidence; printable single-line values may contain spaces;
- process attacker-influenced text in bounded linear or near-linear time; and
- redact a complete service log before selecting the bounded tail.

If argument parsing or sandbox setup fails before a safe redaction context exists, the wrapper MUST emit no attacker-controlled or credential-bearing evidence and MUST return the documented setup-failure code. Output-memory and service-file quotas are separate requirements and are not implied by redaction alone.

## 10. Stable interfaces

Stable external interfaces include required check names, formal review semantics, reusable workflow input/secret names, repository-dispatch payload schemas, result-marker schemas, exit-code meanings, artifact receipt formats, and documented recovery commands. A breaking change requires a versioned bridge, consumer inventory, migration plan, rollback, and independently verified consumer acceptance.

Internal helper layout may change without a consumer migration when those stable interfaces and authority boundaries are preserved.

### 10.1 Required check and review names

| Interface | Stable emitted name | Defining source |
|---|---|---|
| OpenCode bootstrap | `required-workflow-bootstrap` | `.github/workflows/opencode-review.yml` |
| Source-tree sentinel | `coverage-source-tree` | `.github/workflows/opencode-review.yml` |
| Coverage evidence | `coverage-evidence` | `.github/workflows/opencode-review.yml` |
| OpenCode review check | `opencode-review` | `.github/workflows/opencode-review.yml` |
| Noema review check | `noema-review` | `.github/workflows/noema-review.yml` |
| Strix security check | `strix` | `.github/workflows/strix.yml` |
| Merge scheduler check | `scan-pr-queue` | `.github/workflows/pr-review-merge-scheduler.yml` |

The live ruleset inventory determines which names are required for a target.
Renaming an emitted name is a breaking consumer/ruleset change. A formal review
submission is not interchangeable with the same-named Check Run.

### 10.2 Repository-dispatch schemas

Current payloads are legacy implicit version 1: they do not carry a
`schema_version` field. Senders and receivers MUST therefore reject unknown or
missing required fields, validate live identity, and treat adding a new required
field or changing a type as breaking. The next breaking revision MUST add an
explicit version and a compatibility bridge.

| Event type | Required fields and types | Optional fields | Receiver and rejection |
|---|---|---|---|
| `opencode-review` | `target_repository: owner/name`, `pr_number: positive integer`, `pr_base_ref: string`, `pr_base_sha: 40-hex`, `pr_head_ref: string`, `pr_head_sha: 40-hex` | none in the security identity | `opencode-review-dispatch.yml`; reject unauthorized actor/target, malformed identity, fork, closed PR, or any live mismatch. |
| `strix-scan` (PR scope) | same repository/PR/base/head identity as `opencode-review` | `strix_llm: allowlisted string` | `strix.yml`; reject incomplete/malformed metadata, unallowlisted model, or live mismatch. |
| `noema-review` | `target_repository: owner/name`, `pr_number: positive integer` | none | `noema-review.yml`; resolve the live PR/head and fail rather than trust caller-supplied review evidence. |
| `pr-review-autofix` | `target_repository`, `pr_number`, `pr_base_ref`, `pr_base_sha`, `pr_head_ref`, `pr_head_sha` with the types above | `resolve_conflict: boolean-like string`, default false | `pr-review-autofix.yml`; same-repository mutable head only; reject every base/head mismatch before checkout and push. |
| `merge-scheduler` / `pr-review-fix-scheduler` | `target_repository: owner/name` for cross-repository dispatch | bounded scheduler fields matching the `workflow_call` names/types below | corresponding scheduler workflow; invalid type/range/target fails before mutation. |
| `agent-mention-noema` / `agent-mention-opencode` | `target_repository`, `pr_number`, `pr_head_sha`, `pr_base_sha`, `base_branch`, `requested_agent`, `agent_invocation_key`, `requested_by`, `source_comment_id` | OpenCode-only fixed control fields: `trigger_reviews`, `review_dispatch_limit`, `enable_auto_merge`, `update_branches`, `merge_mode` | mention dispatch workflows and `agent_mention_router.py`; exact agent/key/comment/head claim and artifact receipt must agree. |

### 10.3 Reusable workflow inputs and secret classes

| Interface | Inputs | Secret contract |
|---|---|---|
| `pr-review-merge-scheduler.yml` | `dry_run:boolean`; string-encoded bounded `max_prs`, `pr_number`, `review_dispatch_limit`, `branch_update_limit`, `stale_opencode_minutes`; `trigger_reviews:boolean`; `enable_auto_merge:boolean`; `update_branches:boolean`; `merge_mode:{direct_or_auto,auto,direct,disabled}`; `project_flow`, `base_branch` strings | Caller secrets are not declared; jobs use the scoped workflow token and configured mutation/App fallbacks only where needed. |
| `pr-review-fix-scheduler.yml` | `dry_run:boolean`; bounded string `max_prs`, `max_dispatches`, `retry_hours`; `target_repository`, `autofix_workflow`, `autofix_repository`, `base_branch`, `canonical_ref` strings | Mutation fallback is limited to `PR_REVIEW_MERGE_TOKEN` or `OPENCODE_APPROVE_TOKEN`; target and head are revalidated. |
| `deploy-pages.yml` | required `project_name:string`, `build_dir:string`; optional `custom_domain:string` | Legacy caller uses `secrets: inherit`, but the callee consumes only `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID`; explicit declarations are the required migration. |

Credential classes remain purpose-specific: model-provider secrets (including
`NVIDIA_NIM_API_KEY`, Noema/provider keys), review-publication/App authority,
branch/merge mutation tokens, cloud deployment secrets, and the per-job GitHub
token MUST NOT be aliased merely because one route is unavailable.

### 10.4 Sandbox result schemas and exit codes

Both markers are exactly one ASCII line: a literal marker, one space, then a
valid JSON object with keys serialized deterministically. They are currently
implicit version 1; consumers MUST reject unknown missing required keys, and a
future incompatible schema MUST add `schema_version`.

| Marker | Required JSON fields and types |
|---|---|
| `SANDBOXED_VERIFY_RESULT` | `allowed_env:string[]`, `command:string[]`, `cwd:string`, `elapsed_seconds:number`, `evidence_note:string`, `exit_code:integer`, `network:{default,required,not-required}`, `sandbox:string`, `sandboxed:true` |
| `SANDBOXED_WEB_E2E_RESULT` | `allowed_env:string[]`, `backend_cmd:string`, `backend_ready:boolean`, `cwd:string`, `e2e_cmd:string`, `elapsed_seconds:number`, `evidence_note:string`, `exit_code:integer`, `frontend_cmd:string`, `frontend_ready:boolean`, `network:{default,required,not-required}`, `sandbox:string`, `sandboxed:true` |

| Exit | Meaning |
|---:|---|
| child code | Completed verification/E2E process; preserve its exact return code. |
| `2` | Safely redacted command-line usage error after an unambiguous preflight context exists. |
| `124` | Verification or E2E timeout. |
| `125` | Web backend/frontend readiness did not become true within the startup contract. |
| `126` | Unsafe allow-value preflight, sandbox/setup/launch/cleanup, or another wrapper failure. Preflight/setup paths without a safe context emit no attacker-controlled result. |

The marker and exit value MUST agree. If the final marker would contain a
sensitive literal it is suppressed, and suppression cannot turn failure into a
success-shaped receipt.

### 10.5 Scheduler and mention receipts

`pr_review_merge_scheduler.py` emits one final JSON object with
`schema_version: "pr-review-merge-scheduler/v2"`, counts, run configuration,
and per-PR decisions. Each decision carries PR number, internal action,
contract decision, reason, notes, and optional typed guidance. Allowed
`merge_mode` values are `direct_or_auto`, `auto`, `direct`, and `disabled`.

Agent invocations use the exact-name artifact prefix
`cwl-agent-invocation-<opaque-key>` as the durable idempotency ledger. The key
binds repository, PR, source comment, requester, requested agent, complete
downstream controls, and head/base identity. A reaction or acknowledgement
comment is user feedback, not the authoritative receipt.

## 11. Data retention and privacy

Raw PR source, logs, and artifacts MUST use the shortest retention compatible with review and incident needs. Evidence stores SHOULD retain hashes, classifications, decisions, and bounded diagnostic excerpts rather than unlimited raw content. Access to unmasked business PII MUST be purpose-bound and auditable. Credentials MUST never be retained as evidence.

## 12. Audited implementation state and gaps

The stronger contracts above are not all protected-main behavior. These gaps
stay non-passing wherever their target contract is required; their live object
type and maturity are mapped in [TRACEABILITY.md](TRACEABILITY.md).

| ID | Audited protected-main behavior | Required closure |
|---|---|---|
| `IG-001` | Mention wrappers bind a claim, but the complete downstream review path does not yet preserve every versioned field, live-base observation, and review-only policy through authoritative publication. | Integrate and accept Draft [PR #1021](https://github.com/ContextualWisdomLab/.github/pull/1021), the bounded successor to closed-unmerged [PR #840](https://github.com/ContextualWisdomLab/.github/pull/840). |
| `IG-002` | Bot/model identities remain advisory; a counted qualifying independent non-author human approval is still externally required. | Establish the governance path in [Issue #772](https://github.com/ContextualWisdomLab/.github/issues/772). |
| `IG-003` | Privileged targeted scheduler, OpenCode, and Strix paths reject external heads while older policy prose described them as reviewable. | Align every entrypoint under [Issue #889](https://github.com/ContextualWisdomLab/.github/issues/889). |
| `IG-004` | Per-workflow concurrency, invocation claims, and expected-head guards exist, but there is no shared owner/TTL/heartbeat/fencing record across branch-mutating workflows. | Implement [Issue #890](https://github.com/ContextualWisdomLab/.github/issues/890). |
| `IG-005` | A provider/backend outage can leave Strix without authoritative exact-head scan evidence while a transport/check shape may be skipped or neutral. | Add the fail-closed gate in [Issue #891](https://github.com/ContextualWisdomLab/.github/issues/891). |
| `IG-006` | Workflow-token preference coexists with App/token fallbacks, and merge-mode/credential authority is not one executable table. | Align authority under [Issue #892](https://github.com/ContextualWisdomLab/.github/issues/892). |
| `IG-007` | A post-claim pre-forward mention failure is an at-most-once dead-letter during retention and needs a new trusted comment. | Add recoverable states/fencing under [Issue #893](https://github.com/ContextualWisdomLab/.github/issues/893). |
| `IG-008` | The scheduler records PR-local mutation failure as `action_error` and continues; the accepted repair preserves the complete bounded scan and summary, then returns non-passing only when a material decision is `action_error`. | Integrate and accept [PR #899](https://github.com/ContextualWisdomLab/.github/pull/899), then verify the protected scheduler receipt and process exit contract. |

An accepted ADR, diagram, prompt, issue, or this register cannot promote these
gaps to `implemented_on_protected_main`.

## 13. Verification

The minimum verification classes are defined in [TEST_STRATEGY.md](TEST_STRATEGY.md). Requirement-to-implementation status is maintained in [TRACEABILITY.md](TRACEABILITY.md); documentation presence is not proof of implementation.
