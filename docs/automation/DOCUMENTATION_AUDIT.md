# Automation documentation fitness audit

Status: active_pr

## Scope and conclusion

This audit evaluates whether the canonical `ContextualWisdomLab/.github` automation-control-plane documentation can faithfully absorb the durable automation/governance decisions established across the current CWL project conversation without turning chat history into shipped claims.

**Conclusion:** the original PR #886 baseline was structurally strong but not sufficient for the full conversation-derived control-plane contract. It covered PR maintenance, product development, exact-head/live-base identity, evidence separation, writer leases, RCA, independent approval, protected-main acceptance, central/leaf ownership, security, threats, tests, operability, incidents, traceability, UML, and a conceptual ERD. It did not explicitly model the external scheduled agent/orchestrator plane, the same-invocation continuation/handoff rule after prompt or documentation changes, a double exit sweep, or the conversation-to-canonical-GitHub reconciliation boundary. Those gaps are corrected in this documentation line and protected by the documentation fitness test.

This audit does **not** claim that every product-specific design discussed anywhere in the wider CWL project is duplicated into `.github`. Product-specific PRD/TRD/ADR/UML/ERD remain authoritative in their owning repositories. The central control plane records ownership and handoff semantics instead of creating a second specification authority.

## Fitness matrix

| Artifact | Before this audit | Required correction | Current status in this PR |
|---|---|---|---|
| PRD | Partial | Make user-visible status/prompt/doc updates non-terminal; require same-invocation continuation and conversation reconciliation | active_pr |
| TRD | Partial | Add external automation control evidence, `continuation_handoff`, queue-wide double exit sweep, reconciliation contract | active_pr |
| Architecture | Partial | Separate External orchestration plane from GitHub execution and evidence plane; add canonical documentation plane | active_pr |
| Conceptual ERD / data model | Partial | Add `automation_control_record`, `execution_lane`, `deferred_item`, `continuation_handoff`, documentation baseline/fitness entities | active_pr |
| UML | Partial | Add continuation state machine, external-scheduler authority view, and conversation-to-repository reconciliation sequence | active_pr |
| ADR index | Partial | Existing ADR-0003 covered work conservation, but no dedicated handoff/reconciliation authority decision existed | active_pr |
| Security | Adequate for central scope | Preserve credential/evidence/writer boundaries; no new secret authority is introduced by reconciliation | active_pr |
| Threat model | Adequate for central scope | Premature termination and split documentation authority are governance/availability threats and should remain traceable through ADR/operability | active_pr |
| Test strategy | Partial | Documentation test must require the audit, all ten ADR families, and continuation/reconciliation invariants | active_pr |
| Operability | Adequate but needs traceability | Premature termination is an operational defect requiring prompt/control repair plus resumed queue execution | active_pr |
| Incident runbook | Adequate for RCA mechanics | Treat early stop as a control-plane incident when safe work demonstrably remained | active_pr |
| Traceability | Partial | Map continuation/reconciliation and external automation authority without claiming GitHub-native implementation | active_pr |
| AGENTS / CLAUDE / CHANGELOG | Structurally adequate | Keep links and behavioral summary aligned with the amended canonical graph | active_pr |

## Central-versus-leaf documentation boundary

The following durable topic families have appeared in the wider CWL project conversation. They are **not** specifications owned by `.github`; they are handoff obligations to their product repositories or dedicated documentation lines.

| Product/domain family | Central responsibility | Leaf responsibility |
|---|---|---|
| Psychometrics / fast-mlsirm / psychometrics-commons | shared automation, evidence, CI/security, writer-lease policy | mathematical model, Rust CPU/GPU estimator, multilevel/multiple-membership/time modeling, simulation/recovery evidence |
| Temporal Event Psychometrics / TEPP | shared automation and standards/doctoring conventions | temporal/event ontology, multi-clock model, TDT/CHRONOS integration, longitudinal ESEM/DSEM, product data model and UI |
| naruon | shared CI/review/release controls | language/product functionality such as topic modeling, grammar/spell checking, connectors and end-user workflows |
| pg-erd-cloud | shared CI/review/release controls | forward engineering, saved-view workspace, schema-change workflows, ERD/data product UX and Figma contracts |
| BandScope | shared CI/review/release controls | real-audio/stem accuracy, rehearsal handoff, accessibility and music-analysis product contracts |
| Inkspan | shared CI/review/release controls | deterministic document rendering, collaboration and document-product behavior |
| OriginWeave | shared CI/review/release controls | agentic browser runtime, Chromium compatibility boundary, resource governor, provenance and browsing policy |
| EmbedRelay | shared CI/review/release controls | embedding-space identity, directed adapters, migration/backfill, fidelity benchmarks and vector-store connectors |
| MHTML ETL Gateway | shared CI/review/release controls | immutable raw ingestion, MHTML parsing, schema inference, PostgreSQL loading, lineage and enterprise data-model contracts |
| LifeOS | shared CI/review/release controls | personal goal/project/habit/task product model, cloud/self-host deployment, auth and user-experience contracts |
| AppGuardrail and security products | shared security/review evidence | scanner/rule-engine detection coverage and product-specific adversarial regression corpus |

A central automation change may link to or verify a leaf requirement, but it must not silently restate a leaf design as central ownership. Conversely, a durable shared automation requirement must not remain only in a product PR, conversation, or downloadable planning pack.

## Required reconciliation algorithm

1. Identify a material decision in conversation, an automation prompt, an incident, an active PR, or a planning artifact.
2. Refetch protected-main implementation and the current active PRs that may already own the decision.
3. Resolve the canonical owner: `.github` for shared automation/control-plane semantics; the product repository for product behavior.
4. Reuse the existing canonical documentation branch/PR when one exists.
5. Classify the decision using the controlled maturity vocabulary.
6. Update every affected artifact class, not only an ADR or PR body.
7. Update traceability and machine-checkable documentation contracts.
8. Return through `continuation_handoff` to the live executable queue; documentation completion is not run completion.

## Residual gaps and non-claims

- This PR does not prove that every leaf repository already contains its complete product-specific PRD/TRD/ADR/UML/ERD pack. That requires repository-by-repository live audits under each repository's writer lease.
- This PR does not make external scheduled-agent state GitHub-native or persist it in a central database.
- This PR does not implement the active review-quality, model-routing, fleet-coordination, sandbox-redaction, or security/coverage changes represented by other active PRs. It documents authority and maturity so those lines can be integrated without evidence conflation.
- A documentation file being present is not evidence that the described behavior is shipped. Only protected-main source and required operational acceptance can promote a decision to `implemented_on_protected_main`.

## Acceptance

The central documentation graph is sufficient for this control-plane conversation slice when:

- every required artifact is indexed and uses the controlled maturity vocabulary;
- the external orchestration, GitHub execution/evidence, and canonical documentation planes are explicit;
- work-conserving same-invocation continuation and double exit sweeps are normative;
- the conceptual ERD contains continuation/defer/handoff and documentation-fitness entities without inventing persistence;
- ADR-0010 records conversation/prompt/documentation-to-executable handoff authority;
- traceability distinguishes active/accepted behavior from protected-main implementation;
- the dependency-free documentation contract passes on the unchanged exact head; and
- the invocation returns to other safe queue work instead of treating this audit as completion.
