# CWL Automation Control Plane — UML Views

Status: active_pr

## PR maintenance sequence

```mermaid
sequenceDiagram
  participant S as Scheduler
  participant E as Evidence
  participant F as Feasibility
  participant W as Writer
  participant C as Checks/Reviews
  participant M as Merge
  S->>E: Refetch exact head + live base + gates
  E->>F: Non-passing evidence
  F->>F: RCA and distinct remedy evaluation
  alt executable remedy
    F->>W: Exact bounded mutation
    W->>C: Exact-head verification
    C-->>S: Authority-separated evidence
  else waiting/external/read-only
    F-->>S: Defer exact lane identity
  end
  S->>M: Merge only if real gates pass
  S->>S: Rotate to next executable lane
```

## Product development sequence

```mermaid
sequenceDiagram
  participant S as Scheduler
  participant D as Deterministic gates
  participant L as Optional model path
  participant R as Repository
  S->>D: Confirm no higher-priority executable integration work
  D->>D: Scope, lease, security and release gates
  alt model is materially required
    D->>L: Materialize NVIDIA_NIM_API_KEY only here
    L-->>D: Bounded proposal/evidence
  end
  D->>R: Test-first bounded implementation
  R-->>S: Exact-head evidence
  S->>S: Return to integration queue
```

## Continuation and handoff state machine

```mermaid
stateDiagram-v2
  [*] --> QueueRefetch
  QueueRefetch --> Execute: executable lane exists
  QueueRefetch --> ExitSweepOne: no executable lane observed
  Execute --> RefetchAffectedState: action, merge, RCA, doc or prompt mutation
  RefetchAffectedState --> Execute: another safe lane exists
  RefetchAffectedState --> ExitSweepOne: no execute-now lane observed
  ExitSweepOne --> Execute: first sweep finds work
  ExitSweepOne --> ExitSweepTwo: first sweep finds none
  ExitSweepTwo --> Execute: second sweep finds work
  ExitSweepTwo --> BoundedTermination: second sweep finds none
  BoundedTermination --> [*]
```

A user-visible status, prompt update, review request, merge, documentation edit, or defer decision never transitions directly to `BoundedTermination`. It must return through queue selection and the required exit sweeps unless the practical invocation/tool budget is exhausted.

## Conversation-to-repository reconciliation

```mermaid
sequenceDiagram
  participant H as Conversation/Prompt/Artifact
  participant G as GitHub Live State
  participant C as Canonical Documentation
  participant T as Documentation Contract
  participant Q as Executable Queue
  H->>G: Identify material durable decision candidate
  G->>G: Refetch protected main + active PR implementation
  G->>C: Classify shipped/active/accepted/planned/research/superseded/out-of-scope
  alt canonical line already exists
    C->>C: Extend existing authority
  else no canonical line exists
    C->>C: Create one discoverable authority
  end
  C->>T: Update affected PRD/TRD/Architecture/ADR/UML/Data Model/Security/Operations/Traceability
  T-->>C: Machine-check fitness
  C->>Q: continuation_handoff to next executable lane
```

## Evidence/gate state machine

```mermaid
stateDiagram-v2
  [*] --> Observed
  Observed --> Actionable: repository-owned root cause
  Observed --> Deferred: pending/external/read-only
  Actionable --> Verifying: mutation executed
  Verifying --> Actionable: failed with new evidence
  Verifying --> GateClean: exact-head gates pass
  GateClean --> MergeWaiting: counted external approval only
  GateClean --> Merged: all merge gates pass
  MergeWaiting --> Merged: approval arrives, head unchanged
  Merged --> OperationalAcceptance: runtime proof required
  OperationalAcceptance --> Closed: protected-main evidence passes
  Merged --> Closed: no runtime proof required
  Deferred --> Observed: material state change
```

## Reviewer and merge authority

```mermaid
flowchart LR
  A[Automated model/reviewer] -->|advisory evidence| G[Gate evaluator]
  H[Independent formal review] -->|counted only if eligible/current| G
  C[Checks/statuses] -->|separate evidence| G
  P[Rulesets/branch protection] --> G
  G -->|all actual gates pass| M[Merge authority]
  G -->|otherwise| D[Defer or remediate]
```

## External scheduler and GitHub authority

```mermaid
flowchart LR
  X[External scheduler/orchestrator] -->|invocation + writer lease| Q[Execution queue]
  Q -->|read/write under lease| R[GitHub repository]
  R --> C[Checks]
  R --> V[Formal reviews]
  R --> S[Commit statuses]
  R --> W[Workflow runs]
  C --> G[Gate evaluator]
  V --> G
  S --> G
  W --> G
  X -. cannot substitute .-> G
```

## Incident classification

```mermaid
flowchart TD
  F[Observed failure] --> R[RCA]
  R --> T{Failure class}
  T -->|transient transport/bootstrap| B[Bounded classified retry]
  T -->|integrity/auth/TLS/ref/policy| X[Fail closed]
  T -->|repository product defect| P[Test-first product repair]
  T -->|central dependency| H[Read-only handoff to owner]
  T -->|reviewer/provider capacity| D[Defer lane and rotate]
  T -->|premature termination| C[Repair continuation policy and resume queue]
  B --> V[Exact acceptance evidence]
  X --> V
  P --> V
  H --> V
  D --> V
  C --> V
```
