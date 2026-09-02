# ADR-0021: Ecosystem admin-web architecture — Keyverse SSO and Keyvault

- **Status:** Accepted
- **Date:** 2026-09-02
- **Scope:** cross-repository admin-web architecture for `noema`, `contextual-orchestrator`, and `keyverse`

## Context

The owner asked for admin web UIs across three repositories
(`noema`, `contextual-orchestrator`, `keyverse`) and for mutual
integration so `keyverse` — currently a Keycloak-fronting central Identity
Provider — can also be used as a Keyvault (secrets/credential management,
analogous to Azure Key Vault or HashiCorp Vault), later expanded by the
owner to two further Keyverse capabilities: service-to-service ABAC/RBAC,
and a "login credential store" for service-account/machine credentials.

Direct repository research (cloned fresh, not assumed) found:

- **`contextual-orchestrator`** already runs a real, serving `/admin`
  operator console (`admin.py`, inline stdlib HTML/JS, eight Figma-grounded
  screens) with no per-model LLM timeout control — the exact gap
  `docs/product-goal-directive.md` §8 already names. An `admin_ui/`
  React+Storybook scaffold exists but is confirmed (by direct inspection,
  matching that repo's own planning ADR 0036, superseded) to be the
  unmodified Vite demo output — no admin-web work in flight there. This
  was the readiest of the three repos: it already had a serving console,
  an established KV/audit pattern (`credentials.py`, `model_group`
  family), and an explicit product requirement to build against.
- **`keyverse`** had no encrypted secrets store (`kv_store.py`'s
  `idp_config_entries` is its own internal, unencrypted config — never a
  generic secrets product surface) and no frontend of any kind. PR #103
  (open, Draft) already implements most of the requested service
  ABAC/RBAC capability (`authorization_plane.py`, `org_authorization.py`,
  ADRs 0010–0012) but is not currently mergeable.
- **`noema`** is a Cloudflare Worker OIDC/credential-exchange broker with
  only `/health`, `/ready`, `/exchange` and Durable-Object-only internal
  state — no admin-readable HTTP surface exists to build a console on top
  of today. The least ready of the three.

Per this repo's own scoping guidance for genuinely multi-week product
work, the correct first iteration is the smallest real, honestly-scoped
slice per repo — not three parallel half-built admin webs.

## Decision

1. **Keyverse is the shared SSO provider for every admin web in this
   ecosystem.** It is already the org's central IdP; admins authenticate
   to each product's admin console via Keyverse OIDC rather than a
   per-repo local admin credential. This is itself the "상호 연계"
   (mutual integration) the owner asked for, independent of the Keyvault
   question. **Design only in this iteration** — `contextual-orchestrator`'s
   `/admin` still uses its existing shared-bearer-token session model
   (`/admin/session`); wiring Keyverse OIDC in is the next concrete step
   for that console, tracked as an explicit open item rather than
   silently deferred.
2. **Each repo's admin web stays a thin frontend over that repo's own
   backend API**, not a shared cross-repo frontend package — there is no
   second consumer of shared UI primitives yet (matching
   `contextual-orchestrator`'s own ADR 0033 reasoning for why Storybook/
   component tooling stays deferred there specifically).
3. **Keyverse's Keyvault is a bounded context separate from its IdP
   identity/config modules**, sharing only the KV storage *pattern*
   (Protocol + in-memory/SQLite backends) already proven in that repo,
   not any shared table. `contextual-orchestrator`'s existing
   `CredentialBackend` Protocol (pluggable backends, KV-not-env
   discipline) is the natural adapter target for a future
   `KeyverseCredentialBackend` — the motivating first consumer, not
   implemented in this pass. Full reasoning: `keyverse` ADR-0014.
4. **Service ABAC/RBAC is not rebuilt here.** Keycloak's built-in
   Authorization Services (UMA 2.0) exist but are unconfigured in this
   deployment and do not natively cover the hierarchical org-path
   inheritance CWL's Orgmetra-owned org tree requires; PR #103 already
   implements that hierarchy. Recommendation: reconcile and land PR #103
   rather than duplicate it. Full reasoning: `keyverse` ADR-0015.
5. **"Login credential store" is Keyvault plus per-service
   Anti-Corruption Layers, not a fourth Keyverse module.** Centralizing
   secret *storage* in Keyverse while each consuming service keeps its
   own credential-taxonomy knowledge (via its own Protocol adapter, e.g.
   `contextual-orchestrator`'s `CredentialBackend`) avoids growing
   Keyverse into a service that must change whenever any consumer's
   credential schema changes. Full reasoning: `keyverse` ADR-0016.
6. **The first implemented slice is `contextual-orchestrator`'s per-model
   LLM timeout admin surface** (view/set/clear/restore, units, priority/
   inheritance, validation, audit history, API contract — the exact §8
   requirement), extending the existing `/admin` console in place per its
   own ADR 0033/0042. `keyverse`'s Keyvault (write/read/delete/list APIs,
   encryption at rest via Fernet, audit logging) is implemented alongside
   it as the second slice, since it was independently ready and directly
   answers the Keyvault half of the owner's request. `noema` gets no code
   change this iteration — it has no admin-relevant state to expose yet;
   the honest next step there is deciding what operational state (OIDC
   exchange health/rate, App-token issuance evidence) is worth exposing
   before building a console around it.

## Consequences

- No repo gained a half-built parallel admin frontend; each shipped
  either a real, tested slice or an explicit, evidenced "not yet, and
  here is why" record.
- Cross-repo SSO and the Keyvault-as-credential-backend consolidation are
  both real, next, concretely-scoped follow-ups — not vague future work —
  recorded here and in the two repos' own ADRs so the next iteration does
  not have to re-derive this research.
- `keyverse` PR #103 (service authorization) is now more clearly the
  blocking dependency for capability #2 of the owner's three-capability
  Keyverse request; this ADR does not change its status, only records
  that a competing implementation was deliberately not built.

## Rejected alternatives

- **Build out `admin_ui/` (React+Storybook) for `contextual-orchestrator`
  instead of extending `admin.py`.** Rejected: contradicts that repo's own
  operative ADR 0033, and no revisit trigger from that ADR is met by this
  work.
- **Build a from-scratch policy engine for Keyverse service ABAC/RBAC.**
  Rejected: PR #103 already implements the actual (hierarchical,
  org-path-aware) requirement; a second implementation would duplicate
  ~2,000 lines of already-written, already-tested domain logic.
- **Centralize per-service credential semantics inside Keyverse.**
  Rejected: violates this org's minimal-Shared-Kernel/Anti-Corruption-Layer
  DDD convention and would couple Keyverse's deploy cadence to every
  consuming service's credential taxonomy.
- **Force a code change into all three repos this iteration regardless of
  readiness.** Rejected per this org's own genuinely-multi-week scoping
  guidance: `noema` had no admin-relevant surface to build against yet,
  and forcing one would have meant fabricating state or shipping a
  console with nothing real to show.

## References

- `contextual-orchestrator` planning ADR 0033 (admin console UI tooling
  boundary), 0036 (superseded React/Storybook proposal), 0042 (per-model
  timeout admin surface — this iteration's `contextual-orchestrator`
  slice).
- `keyverse` ADR-0014 (Keyvault bounded context), ADR-0015 (service
  authorization plane), ADR-0016 (login credential store).
- `docs/product-goal-directive.md` §8 (LLM/orchestration; the per-model
  timeout admin requirement this ADR's first slice closes).
