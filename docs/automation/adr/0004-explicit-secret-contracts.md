# ADR-0004: Use explicit minimal secret contracts for reusable workflows

Status: Accepted
Date: 2026-08-09
Decision owners: CWL security and workflow maintainers

## Context

Reusable workflows can receive explicitly named secrets or inherit a caller's full secret set. Inheritance is convenient but violates purpose limitation, complicates review, increases disclosure impact, and may supply model/deploy/write credentials to deterministic jobs that never need them.

Historical Agent Tasks guidance also used the name `COPILOT_GITHUB_TOKEN` for a fine-grained GitHub API token. That naming conflated an API authority with Copilot/model identity and now directly conflicts with the organization policy that autonomous development must not use `COPILOT_GITHUB_TOKEN`. The historical alias is superseded rather than grandfathered into the current credential registry.

## Decision drivers

- Least privilege and clear data-flow review.
- Stable credential identities during reviewed migrations.
- Short-lived OIDC/App authority where possible.
- Prevent secrets from reaching free/anonymous providers or untrusted code.
- Preserve compatible deployments while legacy callers migrate.
- Keep GitHub API authority, reviewer identity, and model-provider credentials distinct by name and purpose.

## Alternatives considered

1. **Use `secrets: inherit` everywhere.** Rejected as over-broad and unauditable.
2. **Use one organization super-token or reuse a model/reviewer-looking token name for API mutation.** Rejected due blast radius and authority conflation.
3. **Explicit named secrets plus scoped OIDC/App exchange; narrow documented legacy exceptions.** Selected.

## Decision

Every reusable workflow declares the minimum named secrets and documents purpose, required/optional status, consumer job, provider, and failure behavior. Deterministic jobs receive no model secret. `NVIDIA_NIM_API_KEY` is used only for actual approved model calls; `COPILOT_GITHUB_TOKEN` is prohibited for autonomous development and must not be reused as a GitHub API credential alias. Anonymous/free provider execution receives no unrelated credential.

If a future GitHub API integration cannot use the workflow's minimum `GITHUB_TOKEN` permissions or a short-lived OIDC/App exchange, it requires a separately reviewed, purpose-bound explicit secret whose name describes the authority it grants. That secret must remain separate from model credentials and independent reviewer identities. Existing reviewer credential names/scopes remain unchanged until a separately reviewed migration.

Cross-repository privileges prefer short-lived OIDC/App exchange constrained by trusted workflow source and target. The current inherited-secret deploy pattern is a legacy exception to remove, not precedent.

## Consequences

Positive: smaller blast radius, readable contracts, provider isolation, and easier audit. Negative: caller updates and compatibility bridges are required; OIDC/App availability becomes an explicit dependency, and legacy token aliases require explicit migration rather than silent reuse.

## Failure and recovery

Missing or failed exchange causes only the privileged/model operation to fail closed. Do not fall back to a broader undocumented token or repurpose `COPILOT_GITHUB_TOKEN`. Continue deterministic/read-only work. Rotate/revoke any exposed credential and inspect every job that could have inherited it.

## Security and governance impact

This implements least privilege, separation of duties, purpose limitation, and auditable credential flow. Credential availability never grants review or merge authority beyond GitHub policy. A token name is part of the authority contract: misleading aliases are treated as security debt because they make reviewer, model, and repository-mutation boundaries harder to audit.

## Tests and acceptance

- workflow contracts enumerate allowed secrets and job permissions;
- deterministic and anonymous paths assert model/write secrets absent;
- autonomous development contracts reject `COPILOT_GITHUB_TOKEN`;
- historical Agent Tasks guidance is explicitly marked superseded rather than accepted as a credential exception;
- future non-default GitHub API authority uses a purpose-bound explicit secret or reviewed short-lived App/OIDC exchange, not a model/reviewer alias;
- OIDC audience/target/actor negative tests;
- redaction covers all secret transport and error paths;
- real positive/negative consumer canary after migration.

## Migration and rollback

Inventory inherited callers and legacy credential aliases, add explicit callee declarations, update one low-risk caller, run positive and missing-secret controls, then migrate the fleet. Remove or rename any historical `COPILOT_GITHUB_TOKEN` API alias through a reviewed consumer migration rather than retaining two meanings for one name. Rollback restores a prior caller only if it does not re-expose a known credential or resurrect the superseded alias; otherwise disable the optional deployment/review path.

## Supersession conditions

Supersede when GitHub enforces callee-declared per-secret purpose and automatic least-privilege token attenuation across reusable workflows with equivalent audit evidence, while preserving distinct reviewer, model, and repository-mutation authorities.