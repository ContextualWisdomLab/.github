# ADR-0008: Central control-plane ownership with thin product consumers

Status: Accepted
Date: 2026-08-09
Decision owners: CWL architecture maintainers

## Context

Copying OpenCode, Strix, Noema, merge, and security workflows into every repository creates policy drift, duplicate fixes, inconsistent credentials/check names, and an acquisition liability. Moving product-specific build/release/deployment into the central repository would create the opposite failure: tight coupling and loss of independent product operation.

## Decision drivers

- One reviewed source for organization-wide governance and trust boundaries.
- Independently deployable and usable products.
- Stable, explicit, versioned interfaces.
- Product-owned domain quality and release behavior.
- Safe gradual migration from thick local copies.

## Alternatives considered

1. **Full workflow copy in every repository.** Rejected due drift and repair multiplication.
2. **Centralize all product CI/CD and data.** Rejected due coupling, privilege concentration, and product autonomy loss.
3. **Central shared policy/trusted execution plus thin versioned callers; product-specific gates stay local.** Selected.

## Decision

`ContextualWisdomLab/.github` owns required/reusable governance workflows, trusted dispatchers, evidence schemas/normalization, shared security policy, and merge/fix schedulers. Product repositories own product code/data, domain tests, platform matrices, release/deploy/migrations, and thin calls or ruleset enrollment.

Central interfaces declare stable events, inputs, secret contracts, result/check names, revision semantics, and failure behavior. Internal central implementation may evolve behind those interfaces. Products remain functional when optional central model services are unavailable, while required governance gates remain truthfully non-passing.

## Consequences

Positive: high-leverage fixes and uniform policy with modular products. Negative: central defects have fleet blast radius; compatibility and canary discipline are mandatory.

## Failure and recovery

On a central regression, stop/disable only the affected optional route or revert to a reviewed compatible central version. Product-specific build/release paths continue. Do not restore thick copies as an untracked permanent workaround.

## Security and governance impact

Central trust concentrates responsibility, so immutable source, minimal permissions, consumer allowlists, explicit secrets, and protected-main canaries are required. Product repositories cannot weaken central required gates through local copies.

## Tests and acceptance

- central workflow contract and immutable-source tests;
- thin consumer input/secret compatibility;
- product-local gate independence;
- one positive and negative real consumer canary;
- inventory rejects unexpected thick duplicates; and
- rollback retains product operability.

## Migration and rollback

Inventory local copies, identify product-specific logic, move only shared policy centrally, replace each repository copy with a thin caller/ruleset enrollment, verify exact consumers, then remove the duplicate. Rollback pins/reverts the thin contract or central version without recreating divergent policy.

## Supersession conditions

Supersede if GitHub provides organization-native policy modules with equivalent versioning, testing, secret attenuation, trusted source identity, and product-specific extension points.
