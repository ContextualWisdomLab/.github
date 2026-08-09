# Threat model: CWL automation control plane

Status: living STRIDE-informed model for the architecture in
[ARCHITECTURE.md](ARCHITECTURE.md). Review on every trust-boundary, authority,
credential, trigger, or persistence change.

## Scope and assets

The model covers central workflow definitions and helpers, GitHub events and
API objects, target PR source, model/provider calls, runner workspaces,
credentials, logs/artifacts, branch updates, merges, releases, and
protected-main operational evidence.

The primary assets are protected refs, exact-head evidence, independent review
state, GitHub App/OIDC/PAT credentials, release/deploy authority, workflow
provenance, audit history, and the availability of the work-conserving queue.

## Actors and assumptions

- Trusted maintainers can approve policy changes but may make mistakes or have
  a compromised account.
- Contributors and fork authors control PR source and most PR metadata.
- GitHub supplies identity, refs, checks, reviews, rulesets, and merge
  transactions but its API may be delayed or unavailable.
- Model providers and model output are fallible external dependencies, not
  authorities.
- Runners are ephemeral processing environments and may handle hostile source
  or output.
- Leaf repositories are independently operated security domains.

## Trust boundaries

| Boundary | Untrusted input | Required control |
|---|---|---|
| PR to protected bootstrap | source, metadata, comment instructions | metadata-only validation; no privileged PR code execution |
| Bootstrap to dispatch | repository/ref/SHA/action envelope | strict schema, allow-list, live re-fetch, idempotency |
| Central workflow to leaf source | archive/worktree and repo-native commands | protected workflow provenance, sandbox, scoped environment |
| Runner to model provider | bounded prompt/source/evidence | minimal egress, secret isolation, timeout, output validation |
| Evidence to decision | checks, statuses, reviews, artifacts | type/producer/revision separation and eligibility checks |
| Decision to write/merge | target repository/ref/head | writer lease, live-base refresh, expected-head guard |
| Output to observer | stdout, stderr, summaries, artifacts | bounded diagnostics and publication-boundary redaction |
| Central main to fleet | reusable/required workflow revision | staged acceptance in a real enrolled consumer |

## Threat register

| ID | STRIDE | Threat and impact | Prevent/detect/recover control | Residual risk |
|---|---|---|---|---|
| TM-001 | Spoofing | A comment or dispatch claims a trusted actor/repository. | Verify GitHub actor association, installation scope, event origin, target allow-list, and live repository identity; retain actor/run evidence. | A compromised eligible account remains possible; revoke and rotate on detection. |
| TM-002 | Tampering | A force-push or base movement reuses predecessor checks/reviews. | Exact source-head and independently observed live-base binding; expected-head and `--match-head-commit` guards; invalidate stale evidence. | State can change between reads; the final atomic GitHub guard is authoritative. |
| TM-003 | Tampering | PR source changes the privileged workflow or executes during `pull_request_target`. | Use protected-base workflow code; metadata-only bootstrap; dispatch privileged work from protected default branch. | A defect already merged to central main has fleet impact; staged consumer acceptance limits closure. |
| TM-004 | Repudiation | An agent claims it tested, approved, or deployed without attributable evidence. | Record producer, run/job, exact revision, command/result, review identity, and consumer target; separate evidence types. | Third-party telemetry retention can expire; preserve bounded durable receipts. |
| TM-005 | Information disclosure | Credentials appear in subprocess output, timeout tails, artifacts, or model prompts. | Credential-scrubbed execution, minimal prompt, audience/retention controls, and publication-boundary redaction; pending hardening is tracked in `.github#842`. | Novel token shapes may evade pattern matching; rotate and expand fixtures after incident. |
| TM-006 | Information disclosure | Blanket reusable-workflow inheritance exposes unrelated secrets. | Named secret interfaces, job-scoped materialization, OIDC/App tokens, secret-use tests. | Existing `secrets: inherit` caller guidance is a migration risk. |
| TM-007 | Denial of service | Provider timeouts, API throttling, or one queued PR stalls the fleet loop. | Classified bounded retries, provider budget/fallback, per-item deferral, and work-conserving queue lanes. | A platform-wide outage can pause all GitHub-dependent work; preserve queue identity. |
| TM-008 | Denial of service | Stale work cancels or serializes current-head evidence. | Head-aware concurrency, safe cancellation rules, and current-head refetch before decision. | Runner allocation remains externally controlled. |
| TM-009 | Elevation of privilege | Advisory model output is treated as counted approval or merge authority. | Formal review eligibility, ruleset enforcement, independent non-author review, and separate guarded merger identity. | Misconfigured rulesets can weaken the outer gate; read-only fleet audit detects drift. |
| TM-010 | Elevation of privilege | A fleet auditor or repair worker gains broader write scope. | Role-specific credentials, read-only auditor policy, same-repository repair constraint, writer lease, scope tests. | Over-broad long-lived compatibility tokens remain higher impact until migrated. |
| TM-011 | Supply chain | A dependency/action/archive is replaced or fetched without integrity. | Protected workflow provenance, pinned actions, hash-locked dependencies, digest/SBOM/provenance checks, fail-closed materialization. | Upstream compromise before pinning or signing is still possible; monitor and rotate pins. |
| TM-012 | Injection | PR text or model output injects shell, YAML, path, summary, or GitHub output content. | Structured arguments, syntax validators, output sanitization, path/ref validation, no `eval`, adversarial fixtures. | Native repository test commands still execute target code only inside the bounded runner. |
| TM-013 | Replay | A previously valid dispatch, receipt, or handoff is replayed for a new state. | Idempotency key plus exact snapshot identity; reject completed/predecessor dispatch; record receipt authority. | A replay against an unchanged snapshot may be harmless but still consumes capacity. |
| TM-014 | Integrity | Malformed status/check names or synthetic success hide a missing required gate. | Treat check, status, workflow, review, dependency, and operational evidence as distinct typed records; required absent/neutral/skipped states fail closed. | Ambiguous repository policy needs an explicit mapping and audit. |

## Abuse cases that must remain executable tests

1. A fork changes workflow code and embeds a secret-print command.
2. A current-head approval exists, then the source head changes before merge.
3. The PR API exposes an old base SHA while the protected base ref advances.
4. A bot posts approval prose without an eligible formal review.
5. A provider returns a credential-shaped string in stderr or only after a
   timeout.
6. Two workers acquire the same repository/branch candidate concurrently.
7. A leaf repository asks a central dispatcher to mutate another repository.
8. A permanent checksum or TLS failure is mislabeled transient.
9. A protected-main source merge is called resolved without a consumer run.
10. A malicious output tries to forge GitHub output, Markdown, or summary
    boundaries.

## Risk treatment

High-impact threats to protected refs, credentials, reviewer eligibility, or
cross-repository scope require preventive fail-closed controls and detection.
Availability risks may degrade by deferring only the affected item. Residual
risks are accepted only through the time-bounded exception process in
[SECURITY.md](SECURITY.md); an LLM cannot accept risk on behalf of an owner.

## Review triggers

Re-evaluate this model when a new trigger, reusable workflow, provider, token
class, persistence store, deployment target, release path, auto-repair mode, or
evidence type is introduced; when GitHub changes event or token semantics; and
after every security or protected-main acceptance incident.
