# Automation control-plane threat model

Status: active_pr

## Assets and adversaries

Assets include protected refs, workflow definitions, reviewer identity, merge/release authority, OIDC/App credentials, model secrets, evidence artifacts, and operator trust. Adversaries include malicious pull-request authors, compromised dependencies/actions, prompt-injected comments or source, confused-deputy callers, spoofed reviewers, and accidental automation races.

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

## Assumptions

GitHub protection and organization policy remain external governance authorities. Automated reviewers are advisory and cannot create human approval. A provider outage can delay one lane but cannot authorize bypass.

## Residual risks

Hosted-runner saturation, provider outages, organization billing/policy, and reviewer capacity may remain external. They are reported as exact prerequisites while other safe lanes continue.
