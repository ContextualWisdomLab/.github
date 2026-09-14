# ADR-0029: Review sidecar lazy-fill preflight

- **Status:** Superseded on 2026-09-14 by ADR-0003 and the `#1629` one-shot review-admission contract
- **Original date:** 2026-09-06
- **Scope:** Historical central review-sidecar preflight policy

## Historical decision

This ADR proposed a repository-owned lazy-fill algorithm for review-sidecar startup. The proposal bounded candidate and probe counts, used a readiness target, retried or postponed routes after selected transport outcomes, allocated a small initial output-token budget with a larger semantic escalation, and retained an evidence-triggered priced fallback path.

The policy was implemented in protected source while this ADR still had `Proposed` status. Subsequent organization evidence showed that the design mixed three authorities that must remain separate: provider/model routing owned by Contextual-Orchestrator, review-workflow admission owned by the central repository, and hosted-runner occupancy/reclamation owned by the workflow control plane. It also caused central CI to author model-compute policy (`max_tokens`, sampling, retry/escalation budgets) and made sidecar provisioning perform more live inference than was required to establish compatibility.

The original measurements, amendments, probe-count analyses, `Retry-After` observations, and rate-limit evidence remain available in this file's Git history and in the linked issue/PR evidence (`#1948`, `#1949`, `#1957`). They remain useful incident evidence but are no longer executable policy.

## Superseding decision

ADR-0003 is normative for model lifecycle and timeout semantics. For central GitHub review admission:

1. Each evidence-eligible route receives at most one provider-default semantic compatibility observation during launcher preflight.
2. Central CI does not author `max_tokens`, `temperature`, model-name allowlists, provider/model/group preference, paid fallback, inference retry counts, semantic token escalation, or a total model wall-clock deadline.
3. Reasoning-only, length-exhausted, malformed, transport-failed, or otherwise unusable observations are recorded as bounded rejection evidence and do not allocate another model call.
4. Independently credentialed provider-account lanes may progress concurrently; routes sharing one account remain serialized so startup does not create a same-credential burst. Completion order does not become routing preference.
5. The shell provisioner does not replay `/v1/chat/completions` after launcher preflight. `/healthz` plus persisted per-route evidence form the provisioning readiness boundary. The real review consumer is the first post-provisioning gateway workload.
6. Model timeout defaults to `None`. Explicit user cancellation, provider termination, stale-head cancellation, and administrative workflow termination remain distinct lifecycle events. Progress/idle-based runner reclamation is owned separately and must not become an elapsed-time model cutoff.
7. Provider discovery, credentials, free-pool eligibility, routing, TTC policy, and provider capability belong to the versioned Contextual-Orchestrator owner boundary. Central CI consumes that boundary and fails closed when the required capability is unavailable.

## Consequences

The former `REVIEW_PREFLIGHT_MAX_TOTAL_ROUTES`, readiness targets, probe budgets, fixed 16→4096 token escalation, repository-authored sampling values, transient inference retry budgets, account-specific lazy-fill rules, and priced fallback behavior are retired from the central review-admission contract. They must not be restored from historical tests or documentation without a new accepted ADR and owner-boundary evidence.

This supersession does **not** claim that provider failures disappear or that all review jobs immediately obtain hosted runners. Queue admission and runner occupancy remain separately observable control-plane concerns. Current-head jobs with no runner and no executed steps are incomplete admission evidence, not source GREEN or RED.

## Verification

`#1629` owns the source transition and exact-head regression evidence. The acceptance path is:

- focused one-shot/provider-default preflight contracts,
- normal repository CI/security/supply-chain gates on the same exact head,
- independent review,
- protected integration without bypass or force push,
- immutable Contextual-Orchestrator release for the shared owner contract,
- unchanged downstream-consumer evidence.

Until those gates complete, this ADR's supersession records the intended contract but does not by itself authorize merge or release.
