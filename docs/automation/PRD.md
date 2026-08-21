# Product requirements — CWL automation control plane

Status: accepted baseline
Last reviewed: 2026-08-09
Owners: ContextualWisdomLab maintainers and repository operators

## 1. Problem

ContextualWisdomLab operates many independently useful products that reuse organization-wide review, security, coverage, and merge controls. Without one control plane, repository-local workflow copies drift, a result from the wrong revision can be mistaken for current evidence, long-running reviewers can idle the whole maintenance loop, and operators must reconstruct decisions from comments and conversations.

The product is an automation control plane that converts live repository state into safe, reviewable actions while preserving human merge authority and product-repository autonomy. Its buyer-visible value is shorter and more reliable change lead time, fewer false-green gates, lower incident-reconstruction cost, and auditable organization-wide governance.

## 2. Users and stakeholders

| Persona | Primary need | Harm to prevent |
|---|---|---|
| Product maintainer | Fix and merge valid changes without babysitting every check | Stale evidence, queue starvation, destructive branch repair |
| Independent reviewer | See exact code, tests, risk, and diagnostics for the reviewed revision | Approval reuse after a push; automated approval impersonation |
| Security operator | Enforce shared security boundaries and investigate failures | Secret leakage, untrusted-code execution, fail-open scanner results |
| Product team | Reuse thin central contracts while remaining independently operable | Central coupling, credential sprawl, repository-specific policy drift |
| Buyer or auditor | Verify governance, provenance, rollback, and operational proof | Unverifiable claims based only on prose or predecessor runs |
| Automation agent | Select and execute the next safe action from fresh evidence | Private-memory authority, report-only completion, concurrent writers |

## 3. Product outcomes

- Every merge decision is bound to the exact current source head and independently resolved live base state.
- Checks, commit statuses, formal reviews, model findings, and merge authority remain separate evidence classes.
- One pending reviewer or check blocks only its action; other safe work continues.
- Shared workflows are trusted, minimally privileged, and reusable without thick copies in product repositories.
- CI evidence is useful for diagnosis but does not disclose credentials or silently erase ordinary failure context.
- Code integration is not incident closure: affected behavior is demonstrated again from protected main or a real consumer.
- Product, security, architecture, operations, and decision documents can reconstruct the system without private conversation.

## 4. Operating modes

### 4.1 PR-maintenance mode

The automation repeatedly refreshes every open pull request, exact head, live base tip, review, unresolved thread, required check, workflow run, ruleset, and writer state. It then merges a genuinely clean exact head, fixes a valid current defect test-first, removes a repository-owned blocker, advances a disjoint pull request, or records a precise non-actionable external prerequisite and moves on.

### 4.2 Product-development mode

When no PR or accepted issue is safely executable, the automation selects exactly one bounded, highest-impact control-plane or buyer-visible gap. It researches current primary standards where material, implements the slice test-first, updates authoritative documents and change history, opens or updates one reviewable pull request, and returns to the live queue.

The modes share one work-conserving ledger. Completing one merge, document, review dispatch, or product slice never implies that the remaining queue is empty.

## 5. Functional requirements

| ID | Requirement |
|---|---|
| PRD-01 | Re-fetch current repository, PR, issue, revision, gate, ruleset, and writer evidence before acting. |
| PRD-02 | Bind acceptance to an exact source head and the independently resolved current base tip; invalidate prior evidence after movement. |
| PRD-03 | Keep check runs, commit statuses, formal reviews, model output, branch protection, and merge actions as distinct authorities. |
| PRD-04 | Require qualifying non-author human approval when repository policy requires it; no agent may synthesize or impersonate approval. |
| PRD-05 | Maintain branch-local writer leases and move to disjoint work when a live writer owns the target. |
| PRD-06 | Continue useful work while checks, reviews, providers, or external governance actions are pending. |
| PRD-07 | Perform RCA, compare materially distinct remedies, prove feasibility, and implement the smallest root-cause-changing repair. |
| PRD-08 | Preserve ordinary stdout/stderr, timeout, service-tail, exit-code, and structured-result diagnostics while redacting credentials at every publication boundary. |
| PRD-09 | Treat documentation drift across PRD, TRD, architecture, UML, ERD/data model, security, tests, operations, ADRs, and traceability as executable repository debt. |
| PRD-10 | Require protected-main or real-consumer evidence before closing an operational incident. |
| PRD-11 | Preserve standalone product operation and expose stable, thin, versioned central interfaces. |
| PRD-12 | Use model credentials only for actual model calls; autonomous model-backed development uses `NVIDIA_NIM_API_KEY`, never `COPILOT_GITHUB_TOKEN`. |
| PRD-13 | Protect business PII through access control, purpose limitation, retention, audit, and controlled evidence scope; do not apply blanket PII masking that makes the workflow unusable. |
| PRD-14 | Maintain beginner-readable operator output, public documentation, and 100% owned production statement/branch/docstring evidence. |

## 6. Non-functional requirements

- **Correctness:** no stale, absent, skipped-required, queued, cancelled, synthetic-merge-only, or predecessor-head evidence is promoted to exact-head success.
- **Security:** least privilege, immutable trusted sources, fail-closed validation, bounded output, credential redaction, and no untrusted source execution in privileged events.
- **Reliability:** bounded retries only for classified transient failures; permanent integrity, authorization, TLS, ref, and schema failures fail immediately.
- **Operability:** every terminal decision has a reason, evidence identity, recovery action, and observable acceptance test.
- **Performance:** linear or bounded processing for attacker-influenced evidence; provider latency is not traded for weaker correctness.
- **Compatibility:** thin consumers survive central internal refactoring as long as versioned inputs, outputs, check names, and authority semantics remain compatible.
- **Auditability:** decisions, deviations, rollback, and current implementation status are linked through the traceability matrix.

## 7. Degraded behavior

| Condition | Required behavior |
|---|---|
| Reviewer or model provider unavailable | Keep the affected gate non-passing, defer it, and execute another safe item. |
| GitHub Actions queue saturated | Preserve queued state, avoid duplicate dispatch storms, advance local or disjoint work, and alert on queue age. |
| OIDC or App-token exchange unavailable | Do not invent a credential or broaden `GITHUB_TOKEN`; fail the privileged action closed and continue read-only work. |
| Exact head or live base changes during an action | Abort the write, discard stale acceptance, refresh state, and re-plan. |
| Redaction context cannot be established safely | Emit no potentially colliding evidence and exit with the documented setup-failure code. |
| Documentation contradicts implementation | Record the mismatch as a traceability gap and repair code or docs in the same bounded increment. |
| Independent approval is the only PR gate | Preserve expected-head-safe merge intent if policy allows, then rotate to other work. |

## 8. Success measures

The initial product acceptance requires all of the following:

- zero merges authorized solely by model, status-only, stale-head, or author-self evidence;
- zero accepted check/review records without exact revision identity;
- zero known credential disclosures through completed, timeout, exception, service-tail, command, or structured-result evidence;
- 100% owned production statement and branch coverage plus public docstrings;
- a machine-checked authoritative documentation index, ADR index, diagrams, and requirement traceability;
- a protected-main or real-consumer receipt for every operational incident declared closed; and
- a work-conserving exit sweep showing no safe remaining item before a scheduled run ends for reasons other than its real execution budget.

Proposed service-level indicators and targets are defined in [OPERABILITY.md](OPERABILITY.md). Targets without implemented telemetry are explicitly marked as gaps rather than reported as achieved.

## 9. Out of scope

- Replacing GitHub's branch protection, rulesets, review model, or merge queue.
- Letting an automated reviewer count as a qualifying human approval.
- Hosting product data or implementing product-specific release and deployment logic centrally.
- Persisting the conceptual evidence ERD as a new database without a separate approved design and migration.
- Unlimited log capture or sandbox resource quotas; those require their own implementation slice.
- Blanket masking of names, email bodies, or other business PII in a way that destroys the operator's task. Access and disclosure controls are preferred.

## 10. Release and closure

A documentation or source pull request is merge-ready only when its exact head passes deterministic tests, security and supply-chain checks, coverage/docstring gates, automated review, qualifying independent approval, thread resolution, and repository protection without bypass. A runtime incident closes only after the integrated protected head or an affected real consumer produces the acceptance evidence named in the runbook.
