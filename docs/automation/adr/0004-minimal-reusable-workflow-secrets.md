# ADR-0004: Minimal reusable-workflow secrets

Status: Accepted; migration in progress
Date: 2026-08-09
Owner: CWL automation and security maintainers

## Context

Central reusable/required workflows operate in many repository contexts and may
need GitHub App, OIDC, model-provider, branch-mutation, release, or deployment
credentials. Blanket secret inheritance is convenient but conceals the
interface, exposes unrelated credentials, makes audit difficult, and expands
the impact of untrusted source or a central defect. Long-lived fallback tokens
also risk collapsing review, mutation, merge, and deploy authority.

## Decision drivers

- Least privilege and explicit cross-repository interfaces.
- Short-lived, attributable, repository-scoped credentials.
- Compatibility with current GitHub reusable/required workflow behavior.
- Deterministic behavior when a secret is absent or an installation is missing.
- Safe migration without claiming existing broad callers are already fixed.

## Considered alternatives

1. Use `secrets: inherit` everywhere. This is simple but over-broad and opaque.
2. Use one organization PAT for all actions. This creates a high-impact shared
   authority and weak attribution.
3. Remove all secrets and privileged automation. This loses required review,
   mutation, and deployment capability.
4. Declare named secret contracts and prefer short-lived OIDC/App credentials,
   with separated purpose-specific compatibility tokens. This is selected.

## Decision

Every reusable workflow declares the minimum named secret inputs needed by
each privileged job. Secrets are optional at the workflow boundary only when
the absence has a defined fail-closed or deterministic degraded path. Jobs
receive credentials only after non-secret identity, eligibility, and input
validation passes.

Prefer job-scoped OIDC exchange or repository-scoped GitHub App installation
tokens. Keep review publication, branch mutation, merge, release, and deploy
authority separate. `NVIDIA_NIM_API_KEY` is available only to actual model-call
steps. `COPILOT_GITHUB_TOKEN` is not a development-agent credential. PAT-like
fallbacks are compatibility mechanisms with explicit scope and telemetry, not
a reason to widen the default token.

Current `secrets: inherit` guidance, including the Pages/Cloudflare reusable
caller path, is an acknowledged migration gap.

## Consequences

Callers become more verbose but their security contract is reviewable. Missing
secrets fail at a named capability boundary rather than leaking into unrelated
steps. Repository/App enrollment and rotation require more deliberate
operations. Some legacy workflows need staged dual compatibility.

## Failure and recovery

Missing authority defers only the dependent action; read-only and deterministic
work continues. A 401/403 or installation-scope failure does not trigger
fallback to a broader token automatically. On exposure, restrict evidence,
revoke/rotate the affected secret, audit its exact scope, and verify a
non-destructive authenticated probe before resuming mutation.

## Security and governance

Workflow defaults remain read-only, with job-local permission elevation.
Secrets do not enter PR-controlled commands, prompts, artifacts, summaries, or
logs. Review and merge identities remain independently eligible. Exception
records are owner/target/expiry/compensating-control scoped.

## Verification

Contract tests inspect permissions, named secret references, model-secret
boundaries, fork/untrusted events, absent secret behavior, App scope, OIDC job
scope, and over-broad inheritance. Adversarial tests attempt echo, timeout,
subprocess, output, artifact, and model-prompt disclosure.

## Migration and rollback

Inventory inherited secrets, map actual use, add named inputs and explicit
capability errors, migrate representative callers, exercise protected-main
consumers, then remove inheritance. Rollback may temporarily restore the last
known-good caller for availability under a time-bounded exception; it must not
combine authority classes or expose secrets to untrusted PR execution.

## Supersession

This ADR is current until all callers use explicit interfaces. A successor may
mandate a specific federation mechanism, but must preserve job scoping,
purpose-separated authority, deterministic absence behavior, and audited
migration.
