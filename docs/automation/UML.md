# UML and behavior diagrams

Status: accepted baseline
Last reviewed: 2026-08-10

These diagrams are normative at the boundary level. Detailed step names remain in workflow source and are checked through [TRACEABILITY.md](TRACEABILITY.md).

An editable FigJam companion board is available at <https://www.figma.com/board/4x8YSMb8teJhU19nDjdkcy>. It is **supplemental visualization**, not an authority source: Mermaid and the Git-tracked contracts in this directory remain canonical. The board currently visualizes the central control plane, PR-governance sequence, evidence state machine, and conceptual evidence entities; it must be refreshed or labelled historical when those canonical diagrams change materially.

## 1. Bounded-context component view

```mermaid
flowchart TB
  Governance["GitHub governance context"]
  Review["Review and evidence context"]
  Execution["Sandbox execution context"]
  Scheduling["Maintenance and merge context"]
  Product["Product repository context"]

  Product --> Governance
  Governance --> Review
  Review --> Execution
  Review --> Scheduling
  Scheduling --> Governance
  Governance --> Product
```

## 2. PR-maintenance sequence

```mermaid
sequenceDiagram
  participant A as Maintainer automation
  participant G as GitHub
  participant C as Central workflows
  participant R as Review providers
  participant H as Human reviewer

  A->>G: Fetch PRs, exact heads, live bases, gates, writers
  G-->>A: Current state snapshot
  A->>C: Run smallest safe test-first repair
  C->>R: Request current-head machine evidence
  R-->>G: Check, status, or formal bot review
  H-->>G: Qualifying current-head review
  A->>G: Re-fetch and merge with expected head
  G-->>A: Protected merge or precise rejection
  A->>G: Request protected-main acceptance
```

The final merge request occurs only if the machine, human, ruleset, thread, mergeability, and freshness evidence all authorize it. Any wait returns the automation to another ledger lane.

## 3. Product-development sequence

```mermaid
sequenceDiagram
  participant A as Maintainer automation
  participant G as GitHub queue
  participant D as Deterministic gates
  participant M as Optional model path
  participant H as Human reviewer

  A->>G: Prove no higher-priority safe PR or issue action
  A->>A: Select one bounded buyer/control-plane gap
  A->>D: Add failing contract then minimum implementation
  D-->>A: Tests, coverage, security, docs evidence
  opt Model-backed analysis is material
    A->>M: Invoke with scoped NVIDIA credential
    M-->>A: Validated advisory or gate evidence
  end
  A->>G: Open or update exact-head PR
  H-->>G: Independent review
  A->>G: Return to whole queue
```

## 4. Evidence gate state machine

```mermaid
stateDiagram-v2
  [*] --> Observed
  Observed --> Incomplete: required evidence absent or pending
  Observed --> Failed: current evidence fails
  Observed --> Stale: head or live base moves
  Incomplete --> Observed: evidence event
  Failed --> Repairing: root cause and feasible remedy
  Repairing --> Observed: new exact head
  Stale --> Observed: refresh identity
  Observed --> GateClean: all current gates satisfied
  GateClean --> Stale: head or live base moves
  GateClean --> Integrated: expected-head protected merge
  Integrated --> Accepted: protected-main or consumer proof
  Accepted --> [*]
```

`GateClean` is not incident closure. `Accepted` is scenario-specific and can be reopened by contradictory live evidence.

## 5. Reviewer and merge authority flow

```mermaid
flowchart TB
  Machine["Checks, statuses, model evidence"]
  Formal["Formal review submissions"]
  Policy["Ruleset and required-gate policy"]
  Scheduler["Expected-head merge scheduler"]
  Merge["GitHub protected merge"]

  Machine --> Scheduler
  Formal --> Scheduler
  Policy --> Scheduler
  Scheduler -->|all authorities agree| Merge
  Scheduler -->|anything absent, stale, or failed| Policy
```

Machine evidence cannot enter the `Formal` authority class. A qualifying human approval cannot replace a failed deterministic check.

## 6. Deployment and control-plane topology

```mermaid
flowchart TB
  Required["Organization required workflows"]
  Central["Protected .github default branch"]
  Runner["Ephemeral GitHub-hosted runner"]
  Target["Target product repository"]
  Provider["OIDC/App and review providers"]

  Required --> Central
  Central --> Runner
  Target --> Required
  Runner --> Provider
  Runner --> Target
  Provider --> Runner
```

The protected central source is trusted code; the target PR source is untrusted input. Short-lived provider or App authority is scoped to the job that needs it.

## 7. Retry and failure classification

```mermaid
flowchart TB
  Failure["Observed failure"]
  Classify{"Evidence-backed class?"}
  Transient["Bounded transient retry"]
  Permanent["Fail closed and repair or defer"]
  Continue["Record evidence and continue queue"]

  Failure --> Classify
  Classify -->|DNS, reset, 5xx, capacity| Transient
  Classify -->|auth, integrity, TLS, ref, schema, test| Permanent
  Transient -->|budget remains| Failure
  Transient -->|exhausted| Continue
  Permanent --> Continue
```

## 8. Sandbox evidence publication sequence

```mermaid
sequenceDiagram
  participant W as Verify/web wrapper
  participant P as Child process or service
  participant X as Shared redactor
  participant E as CI evidence sink

  W->>P: Execute unchanged command in bounded sandbox
  P-->>W: stdout, stderr, timeout, exception, or service log
  W->>X: Complete output plus explicit sensitive values
  X-->>W: Canonicalized and redacted evidence
  W->>E: Preserve stream context, exit code, and valid result JSON
  Note over W,E: Redact before tail selection or serialization
```

If safe redaction cannot be established before parsing or setup output, the wrapper returns its setup-failure code without publishing attacker-controlled evidence.

## 9. Mention routing and idempotency sequence

```mermaid
sequenceDiagram
  participant G as GitHub event
  participant R as Mention router
  participant L as Artifact ledger
  participant A as Approved agent

  G->>R: Comment event or authenticated sweep
  R->>G: Re-fetch actor, comment, PR, and exact head
  R->>L: Claim canonical invocation key
  alt completed or active claim exists
    L-->>R: Duplicate; no side effect
  else claim acquired
    R->>A: Canonical allowlisted request
    A-->>R: Bounded result receipt
    R->>L: Complete claim with outcome
  end
```

Visible mention text never becomes executable input. Comment edits, agent
changes, and head changes produce a new identity or invalidate the old request;
redelivery of the same identity is observable but side-effect free.

## 10. Merge-mode and external-head state

```mermaid
stateDiagram-v2
  [*] --> Inspecting
  Inspecting --> Blocked: evidence, thread, policy, or mergeability fails
  Inspecting --> ExternalWait: fork or external head
  Inspecting --> DirectAttempt: clean and direct or direct_or_auto
  Inspecting --> AutoQueued: auto mode and policy eligible
  DirectAttempt --> Integrated: expected-head merge succeeds
  DirectAttempt --> AutoQueued: direct_or_auto eligible fallback
  DirectAttempt --> Blocked: non-fallback error or head moved
  AutoQueued --> Inspecting: head, base, review, or check event
  ExternalWait --> Inspecting: maintainer repair or new live evidence
  Blocked --> Inspecting: new live evidence
  Integrated --> [*]
```

`direct_or_auto` is an ordered policy, not two simultaneous writers. External
heads remain reviewable, but central automation neither direct-merges nor queues
auto-merge for them; it records the maintainer prerequisite and continues other
work.

## 11. Writer lease and branch rotation

```mermaid
flowchart TB
  Select["Select highest-value executable lane"]
  Refetch["Re-fetch target head, base, blob/ref, writer state"]
  Lease{"Branch writer available and identity unchanged?"}
  Write["Acquire branch-scoped writer_lease and mutate"]
  Verify["Run exact-head tests and evidence"]
  Defer["Freeze only this exact branch/head/action"]
  Rotate["Rotate to another non-conflicting lane"]
  Sweep["Fresh whole-queue sweep"]

  Select --> Refetch
  Refetch --> Lease
  Lease -->|yes| Write
  Lease -->|no| Defer
  Write --> Verify
  Verify --> Rotate
  Defer --> Rotate
  Rotate --> Select
  Select -->|no immediate lane| Sweep
  Sweep -->|work exists| Select
  Sweep -->|none; first sweep only| Sweep
```

The lease is branch-scoped, not an implicit repository- or organization-wide mutex. A pending review/check, external approval, or another branch writer blocks only that exact lane. A second fresh all-lanes-nonactionable sweep—or genuine practical run/tool-budget exhaustion—is required before termination.

## 12. Documentation assessment to repository mutation and continuation

```mermaid
flowchart LR
  Evidence["Conversation, planning, PR, incident, protected-main evidence"]
  Revalidate["Revalidate ownership and live implementation"]
  Fitness{"Canonical artifact fitness"}
  Docs["Repair PRD/TRD/Architecture/UML/ERD/ADR/traceability"]
  Tests["Add documentation fitness tests"]
  SourceGap{"Implementation gap discovered?"}
  Source["Create or repair source/test/workflow/issue slice"]
  Review["Exact-head checks and review"]
  Continue["Return to live executable queue"]
  Leaf["Hand leaf product semantics to owning repository"]

  Evidence --> Revalidate
  Revalidate --> Fitness
  Fitness -->|stale, partial, missing| Docs
  Fitness -->|leaf-owned| Leaf
  Docs --> Tests
  Tests --> SourceGap
  SourceGap -->|yes| Source
  SourceGap -->|no| Review
  Source --> Review
  Review --> Continue
  Leaf --> Continue
```

A documentation assessment or update is never completion by itself. Candidate conversation/planning evidence becomes canonical only after revalidation, maturity classification, Git-tracked mutation, and machine/reviewer checks. Product-specific architecture remains with its leaf repository; central documentation owns only shared automation and interface contracts.

## 13. User-redirection incident recovery

```mermaid
sequenceDiagram
  participant U as User/operator
  participant A as Maintainer automation
  participant G as GitHub live queue
  participant D as Documentation control plane

  U->>A: Work remained; prior invocation stopped early
  A->>A: Classify USER_REDIRECTION_INCIDENT
  A->>G: Re-fetch protected main, all PRs/issues, heads, live bases, writers, gates
  G-->>A: Fresh executable and deferred lanes
  opt Control contract was incomplete
    A->>D: Repair prompt/docs/test contract
    D-->>A: META_INTERMEDIATE only; zero completion credit
  end
  alt At least two independent safe lanes exist
    A->>G: Execute first substantive safe action
    A->>G: Execute second materially distinct safe action
    Note over A,G: At least one action is non-documentation when available
  else Exactly one safe lane exists
    A->>G: Execute the sole safe action
  end
  A->>G: Fresh whole-queue sweep 1
  G-->>A: Current queue
  alt Any executable lane exists
    A->>G: Execute and reset sweep count
  else No executable lane
    A->>G: Fresh whole-queue sweep 2 from new reads
  end
```

`USER_REDIRECTION_INCIDENT` is never terminal. Recovery must occur in the **same invocation**. Prompt, documentation, RCA, status, one commit, or one merge has zero completion credit while another safe lane exists. If two independent safe lanes exist, at least two materially distinct actions are required and a safe **non-documentation** lane must be included when available. When only one lane exists, two fresh whole-queue sweeps must prove no second executable lane before voluntary termination.