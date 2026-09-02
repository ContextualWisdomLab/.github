# G-17 through G-22 evidence and decision trace

Status: Proposed evidence for PR #1696. This note is not production authority until the PR merges to protected `main`.

## Scope

This doctoring note records the evidence boundary behind G-17 through G-22 in `docs/product-technical-gap-baseline.md`. It distinguishes observed repository state from organization-level engineering requirements so that a later Agent can revalidate each claim without treating an open PR as released authority.

The governing policy source is [CWL DEVELOPMENT PHILOSOPHY v2026-09-02B](../CWL-DEVELOPMENT-PHILOSOPHY.md). The repository copy is versioned with this PR so subsequent audits can resolve every policy-attributed requirement to a stable repository path instead of relying on conversation state.

## Exact-head evidence snapshot

- `ContextualWisdomLab/.github` protected `main`: `acbb8e7ceef6d1fc0fee67d553a622ac5d707a9b` after PR #1708. Branch protection still requires the established security, coverage, Noema, and OpenCode contexts.
- `ContextualWisdomLab/contextual-orchestrator` protected `main`: `8839081659df587b19642be17b9114f9dee8b666`.
- `ContextualWisdomLab/contextual-orchestrator#1017`: open, not merged, exact head `fe043f4e6db8b24a6ab719fc5801bbbf40e046ae` at this audit. Its provider-name endpoint repair therefore remains **Proposed** and must not be described as protected-main production authority. The open PR also contains adjacent routing-category/naming work; consumers must wait for an immutable released owner version rather than copying its source.
- Current protected-main search still finds provider identity used in provider-specific telemetry/discovery code such as `contextual_orchestrator/openrouter_uptime.py`. That is not automatically a routing-policy violation: the violation criterion is provider identity controlling selection, endpoint rewrite, or failover where a declared capability should do so. Each match must be classified at its actual responsibility boundary.
- Protected-main persistence evidence still includes legacy one-word schema vocabulary in the orchestration persistence fixtures (`seq`, `kind`, `key`, `payload`) and the agent-pool contract still exposes one-word fields such as `priority`/`disabled`. G-22 is therefore a migration/contract gap, not permission to rename storage destructively.

## G-18 — model execution timeout versus transport failure

[CWL DEVELOPMENT PHILOSOPHY v2026-09-02B](../CWL-DEVELOPMENT-PHILOSOPHY.md) requires the default **model execution timeout** across application, Agent, and Gateway to be `null`; a reasoning, streaming, or tool-call operation must not be terminated merely because elapsed model time crossed a generic ceiling. It separately requires provider communication failure to terminate upstream and requires attribution among user cancellation, provider termination, and an explicitly configured administrator timeout.

These are different failure domains. A `null` model-execution deadline does **not** require retaining a dead socket forever. Transport implementations must observe provider/connection termination and propagate communication failures; connection lifecycle and liveness handling remain transport responsibilities. RFC 9112 explicitly separates HTTP connection failures/timeouts and graceful connection closure from application semantics, and does not require either endpoint to have a fixed persistent-connection timeout. Consequently, the repair criterion is:

1. no implicit elapsed-time ceiling for a healthy, progressing model operation;
2. provider/network termination or communication failure propagates immediately and releases resources;
3. an administrator may configure a model-specific timeout, with get/set/clear/restore, units, priority/inheritance, validation, and audit;
4. cancellation cause is observable as user cancel, provider end/failure, or configured administrator timeout;
5. clearing an administrator timeout restores the inherited/null model-execution policy rather than inventing a paid or hidden fallback.

This resolves the apparent contradiction between long-running inference and resource safety without weakening the governing no-elapsed-time-termination rule.

## G-19 — p95 <= 20 ms is an internal SLO, not an external universal threshold

The `p95 <= 20 ms` requirement is an explicit ContextualWisdomLab engineering SLO in [CWL DEVELOPMENT PHILOSOPHY v2026-09-02B](../CWL-DEVELOPMENT-PHILOSOPHY.md). It is **not** claimed to be a universal HCI standard or a threshold derived from the cited papers. Peer-reviewed latency research instead supports the narrower premise that interaction latency below the traditional 100 ms guideline can still be perceptible and affect interaction; Forch et al. measured approximately 60 ms perception thresholds in a simple mouse task, while Attig et al. reviewed evidence that sub-100 ms latency can matter.

Accordingly, G-19 requires each UI-owning product to define the measured page/action boundary, workload, sample design, environment, cold/warm-cache policy, and failure denominator, then prove the organization SLO with executed k6/E2E evidence. The current central baseline records the absence of such evidence **in this audit ledger**; it is not an exhaustive proof that no repository anywhere has ever run a latency test. A product that has current executed evidence should link its exact head/run and make the gap row narrower rather than suppress the SLO.

## G-20 — i18n topology is a governance requirement

DB-backed, versioned translation resources; screen-key-scoped fetch/cache; separation of UI translations from ontology labels; and review/approval/deploy/rollback authority are organization architecture requirements in [CWL DEVELOPMENT PHILOSOPHY v2026-09-02B](../CWL-DEVELOPMENT-PHILOSOPHY.md). They are not presented as a W3C mandate. The gap is that this central baseline currently has no verified canonical-owner release/API evidence for that shared responsibility. Until an owner is verified and released, products preserve the boundary with ports/ACLs/test doubles and do not copy an unreleased owner source tree or download a full browser catalog as a workaround.

## G-21 — Rust-first scope is hot-path and risk based

The Rust-first rule in [CWL DEVELOPMENT PHILOSOPHY v2026-09-02B](../CWL-DEVELOPMENT-PHILOSOPHY.md) does not authorize a wholesale rewrite of every Python orchestration module. The governing scope is mathematical/psychometric/EDA/data-science core and performance/security-critical runtime, including vector/matrix algebra, token size, CPU multithreading, GPU work, and other measured hot paths. Python remains allowed only for a validated Python-only ML runtime without practical Rust parity, with an ADR that records evidence, bounded scope, and removal conditions. G-21 therefore calls for profiling and boundary identification before migration; an unmeasured `orchestrator.py` rewrite would itself violate the policy.

## G-22 — schema migration safety

The two-semantic-word naming rule in [CWL DEVELOPMENT PHILOSOPHY v2026-09-02B](../CWL-DEVELOPMENT-PHILOSOPHY.md) applies to organization-owned DB objects and fields, but migration must preserve persisted data and released consumer contracts. Repair therefore requires a RED naming/migration contract first, an item-safe migration or compatibility layer, GREEN owner CI, and only then an immutable owner release and consumer bump. Existing one-word external/released boundary names are translated at the anti-corruption boundary until the owner version changes; they are not silently rewritten in consumers.

## Revalidation checklist

Before merging or later marking any row complete:

1. Re-fetch protected `main` for both `.github` and each canonical owner.
2. Re-fetch the exact PR head, reviews/threads, required checks, and release/tag evidence; an open PR remains Proposed.
3. Re-run the repository/code/API search used by the row and record the exact head/module or remove the claim if it no longer reproduces.
4. For G-19/G-20, replace central "evidence not recorded" wording with concrete owner evidence as soon as a current run/release exists.
5. For G-18/G-21/G-22, land owner RED -> fix -> integrated GREEN -> immutable release -> consumer version bump; do not copy branch source into consumers.

## References

Attig, C., Rauh, N., Franke, T., & Krems, J. F. (2017). System latency guidelines then and now—Is zero latency really considered necessary? In D. Harris (Ed.), *Engineering psychology and cognitive ergonomics: Cognition and design* (Lecture Notes in Computer Science, Vol. 10276, pp. 3–14). Springer. https://doi.org/10.1007/978-3-319-58475-1_1

Fielding, R., Nottingham, M., & Reschke, J. (Eds.). (2022). *HTTP/1.1* (RFC 9112). Internet Engineering Task Force. https://www.rfc-editor.org/rfc/rfc9112.html

Forch, V., Franke, T., Rauh, N., & Krems, J. F. (2017). Are 100 ms fast enough? Characterizing latency perception thresholds in mouse-based interaction. In D. Harris (Ed.), *Engineering psychology and cognitive ergonomics: Cognition and design* (Lecture Notes in Computer Science, Vol. 10276, pp. 45–56). Springer. https://doi.org/10.1007/978-3-319-58475-1_4
