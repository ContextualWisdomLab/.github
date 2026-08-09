# ADR-0008: Central control plane and thin leaf contract

Status: Accepted
Date: 2026-08-09
Owner: CWL platform and automation maintainers

## Context

The organization needs consistent review, security, merge, and audit policy
across independently operable products. Copying privileged workflows and helper
scripts into each repository causes drift, inconsistent fixes, duplicated
secrets, and a larger attack surface. Fully centralizing product build/release
logic would instead couple products to one runtime and reduce repository
autonomy.

## Decision drivers

- One reviewed source for privileged organization policy.
- Independent product operation, tests, release, rollback, and ownership.
- Minimal cross-repository secret and permission surface.
- Fleet-wide auditability and staged rollout.
- Compatibility with GitHub required/reusable workflow semantics.

## Considered alternatives

1. Thick copy in every leaf. This maximizes local control but creates policy
   drift and expensive fleet remediation.
2. One monolithic central pipeline for all product build/release behavior. This
   creates runtime coupling and an excessive blast radius.
3. Advisory central templates with no enforcement. Repositories can silently
   diverge from required controls.
4. Centralize privileged control policy and keep leaf enrollment/callers thin,
   while leaf repositories own product source/build/release contracts. This is
   selected.

## Decision

`ContextualWisdomLab/.github` is the source of truth for trusted review,
security dispatch, evidence classification, merge scheduling, safe autofix,
sandboxing, and read-only fleet audit. Organization rulesets and protected
default-branch dispatch/reusable workflows select reviewed central code.

Leaf repositories retain source, domain architecture, repository-specific
tests, runtime/build/deploy definitions, environment policy, rollback, and
product ownership. Their central integration is a required-workflow enrollment
or small explicit caller/configuration with versioned inputs and named secrets.
No leaf may silently redefine a central evidence name or merge authority. A
leaf-local compatibility worker is an explicit temporary override with owner,
scope, and exit condition.

## Consequences

A central defect can affect many repositories, so protected-main consumer
canaries and rollback are mandatory. Central fixes are reviewable once and
fleet audit can detect enrollment drift. Leaf repositories remain independently
buildable and releasable, but central policy changes require careful interface
compatibility.

## Failure and recovery

If central behavior regresses, limit the affected dispatch/required-workflow
path, select the last known-good protected revision, use a reviewed revert or
explicit caller pin, and validate a representative consumer before restoring
fleet operation. One broken leaf defers only that repository unless evidence
shows a central boundary defect.

## Security and governance

Privileged code is protected and cannot be selected by PR-controlled refs.
Cross-repository inputs are strict and revalidated. Secret interfaces follow
ADR-0004; review/merge authority follows ADR-0005. The fleet auditor remains
read-only. Centralization does not grant the control plane release or deployment
authority for leaf products.

## Verification

Contract tests cover required/reusable workflow provenance, allowed inputs,
named secrets, default permissions, target-repository context, central-vs-leaf
responsibility, drift detection, and compatibility pins. Protected-main
acceptance runs the central definition in a real enrolled leaf.

## Migration and rollback

Inventory thick copies and repository-specific deviations, define the stable
central interface, enroll a canary leaf, migrate cohorts, audit drift, and
remove copies only after acceptance. Preserve each product's native tests and
release path. Rollback uses a known-good central revision or bounded leaf
compatibility bridge; it does not fork policy indefinitely.

## Supersession

This ADR is current. A successor may introduce another control-plane platform
only if it retains thin explicit leaf contracts, product independence,
least-privilege cross-repository boundaries, fleet audit, staged acceptance,
and rollback.
