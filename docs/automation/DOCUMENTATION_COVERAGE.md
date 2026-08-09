# Documentation coverage assessment

Assessment date: 2026-08-09. Baseline protected-main revision:
`6eb06cdd08c79a06f7b390069d4ffa49e2eb7dba`.

## Verdict

The baseline documentation was **insufficient** for the automation control
plane described in repository code and the operating conversation. It had one
focused comment-invocation document but no discoverable PRD, TRD, architecture,
UML, ERD, security contract, threat model, test strategy, operability contract,
incident runbook, traceability matrix, or durable ADR set. Large README/audit
prose contained useful fragments but could not answer which behavior was
implemented, pending, policy-only, or operationally accepted.

This change creates the minimum complete documentation spine and a machine
contract that prevents silent deletion or loss of discoverability. It does not
turn pending PR behavior into protected-main truth.

The baseline audit also found executable/prose contradictions: Strix is
PR-number scoped with `cancel-in-progress: true` rather than head-SHA scoped and
non-cancelling; `code-reviewer` cannot execute commands; pg-erd-cloud uses the
central autofix worker by default; the current ruleset audit expects exactly
two approvals rather than a single-maintainer gate; and the scheduler still has
an exchanged App-token fallback. This change corrects those statements and
adds invariant tests so dated narrative cannot silently override code.

## Coverage matrix

| Concern | Baseline | This spine | Remaining evidence boundary |
|---|---|---|---|
| Product outcomes and users | scattered narrative | covered by [PRD.md](PRD.md) | validate changes against buyer/operator outcomes |
| Technical identity, gates, retries, secrets | partial across README/code | covered by [TRD.md](TRD.md) | keep state labels current with protected main |
| Bounded contexts/trust boundaries | absent as a coherent view | covered by [ARCHITECTURE.md](ARCHITECTURE.md) | update on new provider/trigger/authority |
| Interaction and state behavior | absent | covered by [UML.md](UML.md) | keep Mermaid rendered in GitHub; Figma is supplemental |
| Evidence/domain relationships | absent | conceptual/persistence mapping in [ERD.md](ERD.md) | add physical schema only if a dedicated store is introduced |
| Security invariants | scattered | covered by [SECURITY.md](SECURITY.md) | hardening in `.github#842` remains pending |
| Threats and abuse cases | absent | covered by [THREAT_MODEL.md](THREAT_MODEL.md) | re-evaluate after incidents/boundary changes |
| Verification and 100% owned coverage | partial implementation guidance | covered by [TEST_STRATEGY.md](TEST_STRATEGY.md) | per-change execution evidence remains required |
| SLIs, queue, rollback, handoff | absent | covered by [OPERABILITY.md](OPERABILITY.md) | telemetry availability must be reported honestly |
| Incident response/closure | scattered | covered by [INCIDENT_RUNBOOK.md](INCIDENT_RUNBOOK.md) | each incident needs protected-main consumer proof |
| Durable architectural decisions | absent | eight minimum ADRs indexed under [adr/](adr/README.md) | supersede rather than silently rewrite decisions |
| Requirement-to-code/incident/standard map | absent | covered by [TRACEABILITY.md](TRACEABILITY.md) | revise on workflow/test/issue lineage changes |
| Discoverability | no canonical entry point | root/agent/master-context links plus index | contract test enforces links |

## Implementation honesty

### Implemented on the audited protected main

- central required/reusable review, security, merge-scheduler, autofix, and
  fleet-audit surfaces named in [TRD.md](TRD.md);
- exact-head guards and live-base comparison in scheduler/replay paths;
- differentiated check/review/scheduler evidence and guarded merge behavior;
- sandbox, sanitization, security, coverage, SBOM/provenance, and contract-test
  infrastructure represented by tracked workflows/scripts/tests.

### Pending open changes

- strict `cwl.agent-invocation/v2` three-key dispatch envelope and
  snapshot-only review route: `ContextualWisdomLab/.github#840`;
- credential-shaped subprocess-log redaction at the publication boundary:
  `ContextualWisdomLab/.github#842`;
- external-head policy/runtime alignment: `ContextualWisdomLab/.github#889`;
- shared cross-workflow writer lease and fencing:
  `ContextualWisdomLab/.github#890`;
- fail-closed authoritative Strix evidence: `ContextualWisdomLab/.github#891`;
- scheduler merge-mode and mutation-credential authority alignment:
  `ContextualWisdomLab/.github#892`;
- recoverable mention invocation claim state:
  `ContextualWisdomLab/.github#893`;
- terminally non-passing scheduler action errors while preserving the bounded
  queue summary: `ContextualWisdomLab/.github#894`.

### Policy or conceptual contracts

- one logical writer lease per repository/branch is the governing target;
  current concurrency and live-head guards reduce races but do not globally
  serialize different writer workflows;
- the ERD defines evidence identities that are currently persisted across
  GitHub objects, workflow outputs, artifacts, and handoffs rather than one
  database;
- work-conserving anti-idle behavior is an automation/policy contract, not a
  repository queue daemon;
- protected-main consumer acceptance is recorded per operational change and
  cannot be inferred globally.

## Quality gate

`tests/test_automation_documentation_contract.py` requires every canonical
document and ADR, validates entry-point discovery and workflow links, checks
supported Mermaid fences, requires the evidence/authority vocabulary and ERD
entities, compares the documented secret registry to workflow usage, checks
current Strix/reviewer/ruleset/autofix invariants, and rejects ambiguous
unfinished markers. Code review must still evaluate semantic accuracy; even an
executable contract cannot prove unqueried live GitHub settings.
