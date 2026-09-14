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
provider discovery, OpenRouter ZDR lookup, DNS/TLS setup, and local health checks
have no repository-authored total model deadline. Explicit user cancellation,
provider termination, obsolete-head cancellation and administrative termination
remain distinct lifecycle events.

Central review preflight is evidence-only. Each admitted route receives one
provider-default semantic observation. The central repository does not author
`max_tokens`, `temperature`, inference retry counts or semantic token
escalation. A reasoning-only, length-exhausted, malformed or transport-failed
response is bounded rejection evidence and does not allocate another model call.
The shell provisioner does not replay a second live `/v1/chat/completions`
request after launcher preflight; `/healthz` plus the persisted per-route report
form the readiness boundary before the real review consumer exercises the
OpenAI-compatible endpoint.

The former token budgets, attempt counts, retry ceilings and timeout values in
this ADR are historical evidence only and must not be restored.

## 2026-09-02 startup-latency amendment

Admission evidence and runtime readiness are distinct. The central free-only
catalog retains every evidence-eligible route. Startup probes independent
provider-account lanes concurrently, while routes sharing one provider account
remain serialized to avoid a same-credential burst. Each route still receives
exactly one provider-default observation, and published evidence is restored to
deterministic input order, so completion timing cannot become routing
preference. Concurrency changes no route membership, priority, cost/ZDR
decision, provider preference or compute allocation.

The regression uses a synchronization barrier across independent
provider-account lanes rather than a wall-clock threshold. It proves those
lanes can enter probing before either lane is allowed to complete and
deliberately does not claim simultaneous probing of routes that share one
provider account.
