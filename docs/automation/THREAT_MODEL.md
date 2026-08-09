# Automation control-plane threat model

Status: active_pr

## Assets and adversaries

Assets include protected refs, workflow definitions, reviewer identity, merge/release authority, OIDC/App credentials, model secrets, evidence artifacts, writer-lease state, finite scheduled execution capacity, the canonical documentation authority, and operator trust. Adversaries include malicious pull-request authors, compromised dependencies/actions, prompt-injected comments or source, confused-deputy callers, spoofed reviewers, accidental automation races, and control-plane configuration drift.

## Threats and controls

| Threat | First failing boundary | Preventive controls | Detection and recovery |
|---|---|---|---|
| Token or model-secret disclosure | Secret materialization/logging | Minimal named secrets, child-only environment, redaction, no PR-controlled echo | Secret scan, synthetic credential-shaped tests, revoke and replay |
| Excessive `secrets: inherit` | Reusable-workflow interface | Explicit per-secret contracts and deterministic gates before secrets | Documentation/test contract and workflow review |
| Confused deputy via dispatch | Caller/target identity binding | Allowlisted repository, event, ref, source revision, audience and permission checks | Reject receipt with bounded identity evidence |
| Stale or synthetic evidence | Evidence-to-head binding | Exact source head plus independently resolved live base | Recollect exact-head evidence; never transfer predecessor success |
| Malicious PR content or prompt injection | Untrusted content enters model/shell | Fixed argv, quoted data channels, no arbitrary evaluation, schema validation | Adversarial fixtures and abstaining model verdicts |
| Reviewer spoofing | Review eligibility | GitHub-counted non-author formal review on the exact head | Ignore comments, statuses, reactions, dismissed and stale reviews |
| Supply-chain compromise | Action/bootstrap provenance | Immutable action pins, hash verification, origin/redirect validation | Fail closed, isolate provider, restore trusted pin |
| Unbounded egress or SSRF | Network request construction | Trusted-origin policy, redirect revalidation, allowlists and timeouts | Egress logs, negative redirect/private-address tests |
| Writer race | Branch/ref mutation | Branch-local lease, refetch-before-write, non-force CAS/fast-forward | Abort on moved head; reconcile read-only |
| Gate weakening during outage | Failure classification | Integrity/auth/TLS/ref errors never retried or downgraded | Incident classification, rollback and protected-main replay |
| Premature termination / queue starvation | External scheduler continuation policy | Work-conserving queue, branch-local defer identity, same-invocation reselection, double exit sweep | Detect safe executable lane after terminal output; repair prompt/control and resume queue |
| Split documentation authority | Conversation/prompt/PR body bypasses canonical owner | One indexed canonical documentation line, explicit central-vs-leaf ownership, maturity vocabulary, reconciliation algorithm | Documentation fitness audit, supersession trace, freeze only conflicting documentation lane |
| External automation authority conflation | Scheduler state treated as GitHub evidence | Separate external orchestration, GitHub execution/evidence, and canonical documentation planes | Reject cross-channel substitution; require source/check/review/runtime evidence from its own authority |

## Assumptions

GitHub protection and organization policy remain external governance authorities. Automated reviewers are advisory and cannot create human approval. A provider outage can delay one lane but cannot authorize bypass. External scheduler/orchestrator configuration can assign an accepted writer lease but cannot manufacture GitHub source, check, review, merge, or protected-main acceptance evidence.

## Residual risks

Hosted-runner saturation, provider outages, organization billing/policy, reviewer capacity, external scheduler outages, and incomplete leaf-repository documentation audits may remain external or distributed. They are recorded as exact prerequisites while other safe lanes continue. Conversation-wide product documentation completeness cannot be centrally claimed until each owning repository has been audited under its own writer lease.
