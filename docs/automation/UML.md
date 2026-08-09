# UML and interaction views

Status: normative diagram-as-code views. The prose contracts in
[TRD.md](TRD.md) take precedence if a renderer changes layout.

Editable architecture, ERD, sequence, and runtime-state companion:
[CWL Automation Control Plane FigJam](https://www.figma.com/board/4x8YSMb8teJhU19nDjdkcy).

## Component and bounded-context view

```mermaid
flowchart LR
    eventContext["Enrollment and event context"] --> snapshotContext["Snapshot and provenance context"]
    snapshotContext --> evidenceContext["Evidence execution context"]
    evidenceContext --> decisionContext["Decision and mutation context"]
    decisionContext --> protectedRef["Protected repository ref"]
    repairContext["Repair context"] --> snapshotContext
    decisionContext --> repairContext
    auditContext["Read-only fleet audit context"] --> eventContext
    acceptanceContext["Operational acceptance context"] --> evidenceContext
    externalModels["External model providers"] -. "Advisory output" .-> evidenceContext
```

## PR maintenance sequence

```mermaid
sequenceDiagram
    participant GitHub
    participant Scheduler
    participant Strix
    participant OpenCode
    participant Noema
    participant Ruleset

    GitHub->>Scheduler: PR event with identity
    Scheduler->>GitHub: Fetch head and live base
    Scheduler->>Strix: Dispatch exact-head scan
    Strix-->>GitHub: Publish security evidence
    Scheduler->>OpenCode: Dispatch exact-head review
    OpenCode-->>GitHub: Publish advisory review
    OpenCode->>Noema: Handoff eligible head
    Noema-->>GitHub: Publish independent review evidence
    Scheduler->>Ruleset: Evaluate current gates
    Ruleset-->>Scheduler: Eligible or deferred
    Scheduler->>GitHub: Head-guarded update or merge
```

The scheduler does not wait in place between the Strix, OpenCode, and Noema
messages. A queued/running item enters a deferred set while another safe lane is
processed.

This sequence is the target interaction contract. On the audited protected
main, Noema handoff is non-blocking and the scheduler does not validate the
Noema identity; `ContextualWisdomLab/.github#772` owns that governance gap.
End-to-end mention snapshot and review-only semantics remain pending in
`ContextualWisdomLab/.github#840`. The current scheduler records a PR-local
mutation failure as `action_error` and continues the queue, but the CLI can
still exit successfully; terminal workflow propagation is tracked in
`ContextualWisdomLab/.github#894`.

## Product-development sequence

```mermaid
sequenceDiagram
    participant Maintainer
    participant DeterministicGates
    participant ModelPlane
    participant GitHub
    participant Consumer

    Maintainer->>GitHub: Create bounded branch from protected main
    Maintainer->>DeterministicGates: Run RED regression
    DeterministicGates-->>Maintainer: Confirm intended failure
    Maintainer->>GitHub: Implement narrow repair
    Maintainer->>DeterministicGates: Run focused and full gates
    DeterministicGates-->>GitHub: Publish exact-head evidence
    GitHub->>ModelPlane: Request optional model review
    ModelPlane-->>GitHub: Publish advisory verdict
    GitHub->>GitHub: Enforce counted approval and ruleset
    GitHub->>Consumer: Run protected-main acceptance
    Consumer-->>GitHub: Record operational evidence
```

Model credentials are not materialized until deterministic identity and
eligibility gates pass. A provider failure cannot replace deterministic or
formal governance evidence.

## Evidence and gate state machine

```mermaid
stateDiagram-v2
    direction LR
    [*] --> Observed
    Observed --> Invalid: identity mismatch
    Observed --> Collecting: identity valid
    Collecting --> Deferred: gate running
    Deferred --> Collecting: state changed
    Collecting --> Failed: authoritative failure
    Failed --> Collecting: repaired head
    Collecting --> Complete: all evidence complete
    Complete --> Stale: head or live base moved
    Stale --> Collecting: new snapshot
    Complete --> Eligible: authority gates pass
    Eligible --> Integrated: guarded merge
    Integrated --> Accepted: consumer proof
    Invalid --> [*]
    Accepted --> [*]
```

## Reviewer and merge authority state flow

```mermaid
stateDiagram-v2
    direction LR
    [*] --> Unreviewed
    Unreviewed --> AdvisoryReviewed: model verdict
    AdvisoryReviewed --> ChangesRequested: valid finding
    ChangesRequested --> Unreviewed: new repaired head
    AdvisoryReviewed --> AwaitingCountedApproval: advisory clean
    AwaitingCountedApproval --> Approved: eligible formal review
    Approved --> StaleApproval: new head
    StaleApproval --> Unreviewed: refresh evidence
    Approved --> MergeEligible: all other gates pass
    MergeEligible --> Merged: expected head matches
    Merged --> [*]
```

An OpenCode, Noema, Strix, CodeRabbit, check, status, comment, or reaction does
not skip `AwaitingCountedApproval` when the ruleset requires an eligible
independent review.

## Deployment and control-plane topology

```mermaid
flowchart TB
    orgRuleset["Organization ruleset"] --> leafA["Leaf repository A"]
    orgRuleset --> leafB["Leaf repository B"]
    centralDefault["Protected .github default branch"] --> leafA
    centralDefault --> leafB
    leafA --> centralDispatch["Central default-branch dispatch receivers"]
    leafB --> centralDispatch
    centralDispatch --> githubApp["Repository-scoped GitHub App or OIDC token"]
    centralDispatch --> modelProvider["NVIDIA NIM or configured model provider"]
    centralDispatch --> targetEvidence["Target checks, statuses, and reviews"]
    fleetAuditor["Read-only fleet auditor"] --> orgRuleset
    consumerProbe["Protected-main consumer probe"] --> targetEvidence
```

## Incident retry and failure-classification flow

```mermaid
flowchart TD
    failure["Observe exact failing boundary"] --> classify{"Classify failure"}
    classify -->|"Transient infrastructure"| boundedRetry["Bounded retry with backoff"]
    classify -->|"Provider capacity"| alternateProvider["Use distinct configured provider"]
    classify -->|"Input or policy"| repairContract["Repair producer or contract"]
    classify -->|"Integrity or security"| failClosed["Fail closed and contain"]
    classify -->|"Authority"| deferAction["Defer affected action"]
    classify -->|"Product source"| redRegression["Reproduce RED and fix root cause"]
    boundedRetry --> verify["Verify exact-head outcome"]
    alternateProvider --> verify
    repairContract --> verify
    redRegression --> verify
    failClosed --> incidentRecord["Record and investigate incident"]
    deferAction --> otherLane["Continue another safe lane"]
    verify --> consumerProof["Run protected-main consumer acceptance"]
    consumerProof --> closeOrReopen{"Closure evidence complete?"}
    closeOrReopen -->|"Yes"| closeIncident["Close incident"]
    closeOrReopen -->|"No"| incidentRecord
```
