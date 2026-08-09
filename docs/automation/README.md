# CWL automation control-plane documentation

Status: authoritative documentation index for `ContextualWisdomLab/.github`.

This directory is the canonical, code-reviewable documentation spine for the
organization automation control plane. It describes what is implemented on the
protected default branch, what is policy, and what remains pending in an open
pull request. Conversation history, automation prompts, PR bodies, and check
summaries may provide evidence, but they do not replace this spine.

## Reading order

| Document | Question answered |
|---|---|
| [README.md](README.md) | Which document is authoritative? |
| [PRD.md](PRD.md) | Who needs the control plane and what outcomes must it deliver? |
| [TRD.md](TRD.md) | What are the technical contracts and authority boundaries? |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Where are the bounded contexts and trust boundaries? |
| [UML.md](UML.md) | How do the main interactions and state transitions work? |
| [ERD.md](ERD.md) | What evidence identities and relationships must be preserved? |
| [SECURITY.md](SECURITY.md) | What security invariants bind implementation? |
| [THREAT_MODEL.md](THREAT_MODEL.md) | Which threats, controls, and residual risks exist? |
| [TEST_STRATEGY.md](TEST_STRATEGY.md) | What proves a change at source, exact head, and protected main? |
| [OPERABILITY.md](OPERABILITY.md) | Which SLIs, SLOs, and operating signals matter? |
| [INCIDENT_RUNBOOK.md](INCIDENT_RUNBOOK.md) | How is an automation incident classified, contained, and closed? |
| [TRACEABILITY.md](TRACEABILITY.md) | Which requirements, ADRs, code, tests, incidents, and standards connect? |
| [DOCUMENTATION_COVERAGE.md](DOCUMENTATION_COVERAGE.md) | What was missing and how complete is this documentation set? |
| [adr/README.md](adr/README.md) | Which durable decisions govern the control plane? |

The focused [review-agent comment invocation](review-agent-comment-invocation.md)
document remains authoritative for the `@cwl-noema-review` and
`@opencode-agent` comment path. It is subordinate to the shared identity,
authority, security, and operability contracts in this directory.

## Truth labels

- **Implemented** means the behavior exists on the protected default branch and
  is backed by a named workflow, script, or test.
- **Pending** means a linked open PR contains the candidate implementation. It
  is not operational truth until protected-main acceptance passes.
- **Policy** means the requirement governs future and current changes even when
  no persistence or enforcement mechanism exists yet.
- **Conceptual** means the domain object is required for reasoning and
  traceability but is not necessarily stored in a database.

The documents were baselined against protected main at
`6eb06cdd08c79a06f7b390069d4ffa49e2eb7dba` on 2026-08-09. That SHA is dated
audit evidence, not a timeless architecture constant.

## Compact glossary

| Term | Meaning |
|---|---|
| exact head | immutable source commit to which evidence is bound |
| live base | target branch tip independently resolved at the decision boundary |
| evidence | typed observation with producer, revision, provenance, and conclusion |
| authority | legitimate permission and eligibility to perform a named action |
| writer lease | logical exclusive source-write ownership for one repository/branch |
| deferred item | exact queue item waiting on an external state change or authority |
| operational acceptance | real enrolled consumer proof from protected-main central code |

## Ownership

The CWL automation maintainers own this spine. Workflow owners update it in the
same PR that changes a governed boundary. Security owners review credential,
trust, provenance, and incident-policy changes; repository maintainers retain
leaf product/build/release ownership. ADR status never substitutes for an
eligible code review or protected-main acceptance.

## Change rule

A change that alters triggers, workflow provenance, snapshot identity,
evidence authority, permissions, secrets, retries, concurrency, writer
ownership, reviewer eligibility, merge/release authority, or incident closure
must update the applicable PRD/TRD/architecture/UML/ERD/ADR/traceability files
in the same bounded change. A roadmap behavior must never be described as
implemented until the protected default branch and a real consumer run prove it.
