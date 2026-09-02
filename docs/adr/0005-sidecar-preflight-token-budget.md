# ADR-0005: Sidecar preflight token-budget diagnostics

- Status: Superseded by ADR 0003 on 2026-08-31
- Date: 2026-08-30
- Scope: Central OpenCode, Noema, and Strix review sidecars

## Historical context

This ADR originally proposed fixed wall-clock budgets and bounded retries for
review-sidecar readiness and generation. Those timing decisions are no longer
normative. They failed for legitimately slow models and for provider discovery,
OpenRouter ZDR lookup, DNS/TLS setup, and local `/healthz` checks.

## Superseding decision

ADR 0003 governs these operations. Inference, initial ping/preflight, warmup,
retry/repair, provider discovery, OpenRouter ZDR lookup, DNS/TLS setup, and local
health checks have no fixed wall-clock timeout. Work ends only through an
operator action or cancellation of an obsolete PR head.

Response validation remains fail closed. Token-budget diagnostics may explain
empty or truncated output, but they do not impose a wall-clock deadline.

The former attempt counts, retry ceilings, and timeout values in this ADR are
historical evidence only and must not be restored.

## 2026-09-02 startup-latency amendment

Admission evidence and runtime readiness are distinct. The central free-only
catalog retains every evidence-eligible route. Startup probes independent
provider-account lanes concurrently, while routes sharing one provider account
remain serialized to avoid a same-credential burst. Every route retains the
same per-route base/escalation semantics, and published evidence is restored to
deterministic input order, so one slow provider account cannot serialize
unrelated provider-account lanes. Concurrency changes no route membership,
priority, cost/ZDR decision, or provider preference; it only removes additive
startup latency across independent account lanes. The regression uses a
synchronization barrier across independent provider-account lanes rather than a
wall-clock threshold, proving those lanes can enter probing before either lane
is allowed to complete; it deliberately does not claim simultaneous probing of
routes that share one provider account.
