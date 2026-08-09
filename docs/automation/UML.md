# CWL Automation Control Plane — UML Views

Status: Proposed baseline

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
  B --> V[Exact acceptance evidence]
  X --> V
  P --> V
  H --> V
  D --> V
```
