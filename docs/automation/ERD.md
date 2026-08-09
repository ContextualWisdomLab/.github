# Evidence and automation domain model

Status: normative conceptual/logical model. This is not a claim that the
entities below are persisted in one database.

Editable companion: [CWL Automation Evidence Domain Model in
FigJam](https://www.figma.com/board/4x8YSMb8teJhU19nDjdkcy). The Mermaid ERD
below is the repository-versioned source of truth.

## Persistence boundary

Most entities are **conceptual** and currently materialize across GitHub PRs,
refs, workflow runs, check runs, statuses, reviews, Actions artifacts, job logs,
issues, and summaries. `handoff_record` and `operational_acceptance` may be
persisted as issue/PR comments, artifacts, or run summaries. A future service
may persist normalized rows, but it must preserve GitHub object identifiers and
source provenance rather than inventing replacement authority.

Database implementations must use descriptive two-or-more-word `snake_case`
object names. The entity names below already follow that rule.

```mermaid
erDiagram
    repository_target ||--o{ automation_run : receives
    repository_target ||--o{ pull_request_snapshot : owns
    repository_target ||--o{ writer_lease : grants
    repository_target ||--o{ operational_acceptance : proves
    automation_run }o--|| workflow_evidence : produces
    automation_run ||--o{ secret_requirement : materializes
    automation_run ||--o{ handoff_record : creates
    automation_run ||--o{ incident_hypothesis : investigates
    pull_request_snapshot }o--|| source_revision : binds
    pull_request_snapshot }o--|| base_revision : observes
    pull_request_snapshot ||--o{ check_evidence : evaluates
    pull_request_snapshot ||--o{ review_evidence : evaluates
    pull_request_snapshot ||--o{ dependency_evidence : constrains
    pull_request_snapshot ||--o{ workflow_evidence : executes
    pull_request_snapshot ||--o| writer_lease : controls
    workflow_evidence ||--o{ check_evidence : publishes
    workflow_evidence ||--o{ review_evidence : publishes
    incident_hypothesis ||--o{ handoff_record : records
    operational_acceptance }o--|| source_revision : validates
    operational_acceptance }o--|| workflow_evidence : exercises

    repository_target {
        string repository_name PK
        string default_branch
        string enrollment_state
        datetime observed_at
    }
    automation_run {
        string automation_run_id PK
        string repository_name FK
        string trigger_event
        string run_state
        datetime started_at
        datetime completed_at
    }
    pull_request_snapshot {
        string snapshot_key PK
        string repository_name FK
        int pull_request_number
        string source_revision_sha FK
        string base_revision_sha FK
        datetime observed_at
    }
    source_revision {
        string source_revision_sha PK
        string source_ref_name
        string source_repository
        datetime committed_at
    }
    base_revision {
        string base_revision_sha PK
        string base_ref_name
        string base_repository
        datetime resolved_at
    }
    check_evidence {
        string check_evidence_id PK
        string snapshot_key FK
        string check_name
        string check_conclusion
        string producer_identity
    }
    review_evidence {
        string review_evidence_id PK
        string snapshot_key FK
        string review_state
        string reviewer_identity
        bool counted_approval
    }
    workflow_evidence {
        string workflow_evidence_id PK
        string automation_run_id FK
        string workflow_path
        string workflow_revision_sha
        string run_conclusion
    }
    dependency_evidence {
        string dependency_evidence_id PK
        string snapshot_key FK
        string dependency_type
        string dependency_identity
        string dependency_state
    }
    incident_hypothesis {
        string incident_hypothesis_id PK
        string automation_run_id FK
        string failure_boundary
        string failure_class
        string hypothesis_state
    }
    handoff_record {
        string handoff_record_id PK
        string automation_run_id FK
        string target_lane
        string deferred_reason
        datetime next_eligible_at
    }
    operational_acceptance {
        string acceptance_record_id PK
        string repository_name FK
        string source_revision_sha FK
        string workflow_evidence_id FK
        string consumer_repository
        string acceptance_state
    }
    secret_requirement {
        string secret_requirement_id PK
        string automation_run_id FK
        string secret_name
        string required_scope
        string materialization_step
    }
    writer_lease {
        string writer_lease_id PK
        string repository_name FK
        string branch_name
        string holder_identity
        string expected_head_sha
        datetime acquired_at
        datetime expires_at
    }
```

## Identity and cardinality rules

1. One snapshot binds exactly one source revision and one independently
   observed base revision. A new source head or live-base observation creates a
   new snapshot identity.
2. Evidence records are append-only observations. A newer record may supersede
   authority, but history is not rewritten.
3. A review record carries `counted_approval` because review state and reviewer
   eligibility are separate facts.
4. A writer lease is optional for a read-only run and exclusive for a branch
   mutation. It never grants merge, release, or deployment authority by itself.
5. A secret requirement identifies the exact step and scope. It does not store
   the secret value.
6. Operational acceptance references both the integrated source revision and
   the workflow evidence exercised by a real consumer.

## Mapping to current systems

| Entity | Current materialization |
|---|---|
| `automation_run` | GitHub Actions workflow run/job |
| `repository_target` | GitHub repository plus ruleset enrollment |
| `pull_request_snapshot` | Live PR API/GraphQL payload plus scheduler decision |
| `source_revision`, `base_revision` | Git refs and 40-character commit SHAs |
| `check_evidence` | Check run or required context |
| `review_evidence` | GitHub pull-request review object |
| `workflow_evidence` | Workflow source SHA, run, job, and artifact metadata |
| `dependency_evidence` | Stack/base/reusable-workflow/ruleset condition |
| `incident_hypothesis` | Issue/PR RCA and evidence note |
| `handoff_record` | Deferred-lane ledger, issue/PR note, or run summary |
| `operational_acceptance` | Protected-main consumer run evidence |
| `secret_requirement` | Workflow input/secret contract and job environment |
| `writer_lease` | Fresh branch/ref checks plus single-writer policy |
