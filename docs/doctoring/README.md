# Doctoring and reference authority

Status: active_pr reference index
Last reviewed: 2026-08-09
Scope: source-backed technical and standards evidence used by the `ContextualWisdomLab/.github` automation control plane

Doctoring records explain **why** a control, algorithm, compatibility boundary, incident repair, or version decision exists. They do not override live source, GitHub rulesets, exact-head evidence, the canonical automation PRD/TRD/Architecture/ADR graph, or product-owned specifications in leaf repositories.

## Canonical standards baseline

- [Automation control-plane standards baseline](automation-control-plane-standards.md) — current final versus draft version discipline; NIST SSDF and CI/CD supply-chain guidance; SLSA; ISO/IEC/IEEE architecture, requirements, testing and product-quality baselines; ISO/IEC security/AI management references; GitHub secure-use/OIDC; OpenTelemetry; SOC 2 evidence limits; conditional CSAP readiness; APA 7 references.

This file is the discoverable standards authority for the central control plane. When a final/draft status changes, update the standards baseline and its documentation-fitness test in the same reviewed change; do not silently replace the normative reference from a PR body or prompt.

## Implementation-specific doctoring

Scenario-specific doctoring remains close to the implementation it justifies. For example:

- [Trusted uv lock materialization](trusted-uv-lock-materialization.md) — exact-base Python dependency materialization and trust boundaries.

Other implementation-specific doctoring files may be added by focused PRs and linked from their ADR, traceability row, or owning workflow/test contract. They are not automatically normative for unrelated subsystems merely because they live under this directory.

## Evidence hierarchy

For current decisions, use this order:

1. live GitHub repository/PR/ruleset/check/review/workflow evidence;
2. protected-main implementation source for observed runtime behavior;
3. `docs/automation/**` and accepted ADRs for intended central contracts;
4. this doctoring set for standards/research rationale and version decisions;
5. dated PR/incident evidence for historical reconstruction; and
6. conversation, prompts, planning packs, and model output as candidate evidence only until revalidated.

## APA 7 and source-quality rules

- Prefer current official final standards, primary technical documentation, and peer-reviewed primary research where material.
- Cite draft standards only when the draft itself is relevant and label its status explicitly; a draft does not silently supersede the current final publication.
- Record retrieval dates for undated or rapidly changing online technical documentation when the version/page does not provide a durable publication date.
- Use APA 7 references in doctoring and ADR material where external evidence materially supports a design decision.
- Separate a source's factual statement from CWL's inference or control decision.
- Never use citations to imply certification, formal conformance, market value, or operating effectiveness that has not been independently established.

## Central versus leaf ownership

This index covers the shared automation control plane only. Product-specific research/design for TEPP/psychometrics, fast-mlsirm, OriginWeave, EmbedRelay, MHTML ETL, LifeOS, BandScope, Inkspan, pg-erd-cloud, naruon, AppGuardrail, and other leaf products belongs in each owning repository. Central doctoring may cite those systems only when their behavior is evidence for a reusable cross-repository automation/interface decision.