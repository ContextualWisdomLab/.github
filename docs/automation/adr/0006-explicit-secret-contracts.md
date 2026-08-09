# ADR-0006 — Use explicit minimal reusable-workflow secrets

Status: active_pr

## Context

Blanket secret inheritance obscures which credentials a reusable workflow needs and can materialize model or merge authority before deterministic gates.

## Drivers

Least privilege, auditable interfaces, confused-deputy resistance, and lower blast radius.

## Alternatives

1. Continue blanket inheritance. 2. Copy secrets into leaf repositories. 3. Declare named purpose-bound secrets and materialize them only on authorized jobs.

## Decision

Choose option 3. Deterministic open-PR, policy, source and product gates run without model secrets. OIDC/App authority is preferred where it satisfies the exact operation.

## Consequences

Callers become explicit and migrations may require coordinated central/leaf changes, but secret exposure and accidental coupling decrease.

## Failure and recovery

Missing optional model secrets defer only model-backed work. Missing required mutation authority fails closed with the exact permission boundary.

## Security and governance impact

Credentials cannot substitute across model, status, review, merge, release, or deployment authorities. Secret values never enter reports or arguments.

## Tests and acceptance

Static contracts reject unnecessary inheritance; synthetic credential-shaped tests cover stdout, stderr, timeout and service-tail paths; real OIDC/App canaries prove envelope consumption.

## Migration and rollback

Migrate one reusable interface at a time with compatibility telemetry, then remove inherited secrets. Roll back the caller/interface pair together.

## Supersession conditions

Supersede only with an equally explicit capability-based interface whose effective permissions are no broader.
