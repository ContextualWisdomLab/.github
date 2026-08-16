# Automation control-plane documentation

Status: authoritative documentation index
Last reviewed: 2026-08-09
Scope: `ContextualWisdomLab/.github` organization automation and its thin repository consumers

This directory is the durable specification for the ContextualWisdomLab automation control plane. It turns decisions that were previously distributed across pull-request bodies, incident comments, workflow prose, and private conversation into a reviewable documentation graph. The implementation remains authoritative for observed behavior; these documents are authoritative for intended behavior. Any mismatch is a defect and must be recorded in [TRACEABILITY.md](TRACEABILITY.md) until repaired.

## Reading order

1. [PRD.md](PRD.md) — operator and buyer outcomes, scope, and acceptance.
2. [TRD.md](TRD.md) — normative event, evidence, identity, retry, secret, and compatibility contracts.
3. [EVENT_CONTRACTS.md](EVENT_CONTRACTS.md) — versioned dispatch, reusable-workflow, scheduler-result, sandbox-result, replay, migration, and rollback contracts; legacy runtime paths remain explicitly classified rather than upgraded by prose.
4. [ARCHITECTURE.md](ARCHITECTURE.md) — viewpoints, bounded contexts, trust boundaries, and failure domains.
5. [DATA_MODEL.md](DATA_MODEL.md) and [ERD.md](ERD.md) — conceptual evidence
   model and exact-path logical ERD; neither claims a deployed database.
6. [UML.md](UML.md) — component, sequence, state, authority, deployment, writer-rotation, and documentation-continuation flows.
7. [SECURITY.md](SECURITY.md), [THREAT_MODEL.md](THREAT_MODEL.md), and [AUTONOMY_THREATS.md](AUTONOMY_THREATS.md) — security objectives, general abuse cases, premature-termination/split-authority threats, and residual risk.
8. [TEST_STRATEGY.md](TEST_STRATEGY.md) — deterministic, security, compatibility, documentation, and protected-main acceptance gates.
9. [OPERABILITY.md](OPERABILITY.md), [INCIDENT_RUNBOOK.md](INCIDENT_RUNBOOK.md), executable [RUNBOOK.md](RUNBOOK.md), and [CONTINUATION_RUNBOOK.md](CONTINUATION_RUNBOOK.md) — service objectives, observability, diagnosis, defer/wait reason codes, double-exit sweeps, ownership, recovery, retention, rollback, and acceptance receipts.
10. [TRACEABILITY.md](TRACEABILITY.md) — requirement-to-code-to-test-to-operation evidence and known gaps.
11. [DOCUMENTATION_AUDIT.md](DOCUMENTATION_AUDIT.md) — whole-conversation fitness, central-versus-leaf ownership, maturity states, and no-soft-timeout continuation contract.
12. [adr/README.md](adr/README.md) — accepted and proposed architecture decisions.
13. [../doctoring/README.md](../doctoring/README.md) — discoverable standards/research authority, APA 7 source-quality rules, and links to implementation-specific doctoring.

## Maturity and authority discipline

A document being an accepted baseline does not mean every described behavior is already shipped. Durable claims map to the controlled maturity vocabulary in [DOCUMENTATION_AUDIT.md](DOCUMENTATION_AUDIT.md): `implemented_on_protected_main`, `active_pr`, `accepted_architecture`, `planned`, `research_only`, `superseded`, or `out_of_scope`.

The sources of truth are ordered as follows:

1. live GitHub repository, pull-request, ruleset, check, review, and workflow evidence for current state;
2. protected default-branch workflow and script source for implemented behavior;
3. this documentation set for intended cross-component contracts;
4. the indexed doctoring/reference authority for external standards, primary technical documentation, research rationale, and version decisions;
5. dated incident receipts and pull-request bodies for historical evidence only; and
6. conversation, prompts, planning packs, and model output as candidate evidence only until revalidated and canonicalized.

Historical SHAs, run IDs, check counts, and performance numbers belong in dated evidence or pull-request records, not timeless architecture. A head change makes predecessor-head checks and reviews historical. A base-branch change requires independently resolving the new live base tip and regenerating evidence.

Changes to triggers, permissions, secret names, evidence identity, retry classes, reviewer eligibility, writer authority, merge behavior, sandbox output, or protected-main closure require:

- a linked ADR update or a new ADR;
- corresponding tests and traceability rows;
- an operability and rollback review;
- current-head checks and qualifying independent review; and
- protected-main operational acceptance when the change affects runtime behavior.

## Scope boundary

The central repository owns shared policy, trusted workflow entrypoints, evidence normalization, review dispatch, and merge/fix scheduling. Product repositories own their source, product-specific tests, release gates, deployments, data, and thin calls into central contracts. Central automation must not silently become an application runtime, a product database, an approval impersonator, or a repository-specific business workflow.

The whole-conversation audit therefore does **not** copy product PRDs such as TEPP/psychometrics, OriginWeave, EmbedRelay, MHTML ETL, LifeOS, BandScope, Inkspan, pg-erd-cloud, naruon, or AppGuardrail into this repository. It records only their shared central interface and explicitly hands product semantics back to the owning repository.

The hourly commercial-maintenance automation is an orchestration policy outside GitHub Actions. GitHub Actions remains the event-driven execution and evidence plane. The hourly policy must use live repository evidence and must not treat its private memory as authority. The hourly recurrence is continuation after genuine practical execution/tool-budget exhaustion, not a voluntary soft wall-clock timeout; meta actions never replace the required fresh exit sweeps.