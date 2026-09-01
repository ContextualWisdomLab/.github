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
catalog retains every evidence-eligible route. Startup probes those admitted
routes concurrently, with identical per-route base/escalation semantics and
deterministic input-order evidence, so one slow provider cannot serialize the
whole catalog and consume the review workflow deadline. Concurrency changes no
route membership, priority, cost/ZDR decision, or provider preference; it only
removes additive startup latency. The regression uses a synchronization barrier
rather than a wall-clock threshold, proving that all admitted routes enter the
probe before any one route is allowed to complete.
