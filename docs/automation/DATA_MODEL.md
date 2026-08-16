# Conceptual data model and ERD

Status: accepted conceptual model; no new persistence is implied
Last reviewed: 2026-08-09

## 1. Purpose and persistence boundary

The control plane already exchanges these concepts through GitHub API objects, workflow payloads, artifacts, comments, local JSON, and in-memory structures. This document gives them stable names so exact revision identity and authority do not collapse into an informal boolean such as `passed`.

The model is **conceptual and logical**. It is not a claim that ContextualWisdomLab operates a database with these tables. GitHub remains the durable system of record today. A future materialized evidence store would require a separate ADR, retention/privacy design, migrations, tenancy model, backup/restore, and rollback plan.

All entity names contain at least two words and use `snake_case`, matching the organization naming rule.

## 2. Identity and run ERD

```mermaid
erDiagram
  repository_target ||--o{ automation_run : executes_for
  repository_target ||--o{ pull_request_snapshot : contains
  pull_request_snapshot }o--|| source_revision : observes_head
  pull_request_snapshot }o--|| base_revision : observes_base
  automation_run }o--o| source_revision : evaluates
  automation_run }o--o| base_revision : compares
  automation_run }o--o| merge_revision : may_integrate
  repository_target ||--o{ merge_revision : protects
  source_revision ||--o{ merge_revision : integrates_as
  base_revision ||--o{ merge_revision : integrates_against

  repository_target {
    string repository_uid PK
    string repository_full_name UK
    string default_branch_name
    string repository_visibility
  }
  automation_run {
    string automation_run_uid PK
    string run_mode
    string trigger_kind
    datetime started_at
    datetime completed_at
    string run_outcome
    string issuer_kind
    string external_run_locator
    string source_not_applicable_reason
  }
  pull_request_snapshot {
    string pull_request_snapshot_uid PK
    int pull_request_number
    datetime observed_at
    string mergeability_state
    string review_decision
  }
  source_revision {
    string source_revision_uid PK
    string head_commit_sha UK
    string head_branch_name
    string head_repository_name
  }
  base_revision {
    string base_revision_uid PK
    string live_base_commit_sha
    string base_branch_name
    string pr_snapshot_base_sha
  }
  merge_revision {
    string merge_revision_uid PK
    string merge_commit_sha UK
    string merge_kind
    string protected_ref_name
    datetime integrated_at
  }
```

`pr_snapshot_base_sha` and `live_base_commit_sha` are deliberately separate. The former explains what GitHub recorded with the PR snapshot; the latter is resolved from the current protected ref at decision time.

For explanatory UML/ERD views the two roles may also be labelled `pr_base_snapshot` and `live_base_revision`; those labels are aliases of the two separate fields carried by `base_revision`, not permission to collapse them into one SHA.

## 3. Evidence ERD

```mermaid
erDiagram
  automation_run ||--o{ workflow_evidence : produces
  source_revision ||--o{ check_evidence : binds
  source_revision ||--o{ status_evidence : binds
  source_revision ||--o{ review_evidence : binds
  source_revision ||--o{ model_evidence : binds
  source_revision o|--o{ workflow_evidence : optionally_binds
  source_revision ||--o{ dependency_evidence : depends_on
  workflow_evidence ||--o{ check_evidence : reports
  workflow_evidence ||--o{ model_evidence : reports
  merge_revision o|--o{ workflow_evidence : may_validate

  check_evidence {
    string check_evidence_uid PK
    string check_name
    string conclusion_name
    bool required_flag
    string source_kind
    datetime observed_at
  }
  status_evidence {
    string status_evidence_uid PK
    string context_name
    string state_name
    string creator_login
    datetime observed_at
  }
  review_evidence {
    string review_evidence_uid PK
    string reviewer_login
    string review_state
    string reviewed_commit_sha
    bool qualifying_human_flag
  }
  model_evidence {
    string model_evidence_uid PK
    string provider_name
    string model_name
    string normalized_outcome
    string evidence_digest
  }
  workflow_evidence {
    string workflow_evidence_uid PK
    string workflow_name
    string workflow_commit_sha
    bigint workflow_run_id
    int workflow_run_attempt
    string workflow_conclusion
    string evidence_issuer_kind
    string external_run_locator
    string subject_kind
  }
  dependency_evidence {
    string dependency_evidence_uid PK
    string dependency_locator
    string dependency_revision
    string dependency_state
    datetime observed_at
  }
```

Evidence classes remain separate because their issuers and permissions differ.
`check_evidence.source_kind` distinguishes a Check Run from another configured
check source; a Commit Status remains `status_evidence`. Neither is silently
converted into `review_evidence`, and normalized model output remains
`model_evidence` even when a workflow uses it as one configured gate input.

`model_evidence` is the conceptual equivalent of a `model_judgment` when a
reviewer/model verdict is discussed in prose. The stored authority class remains
model evidence unless GitHub independently records a formal review through a
reviewer identity whose eligibility is validated separately.


### 3.1 Runtime receipt and issuer aliases

| Observed object | Canonical entity | Required issuer and identity mapping |
|---|---|---|
| GitHub Actions workflow/job/attempt | `workflow_evidence` | `evidence_issuer_kind=github_actions`, workflow name/source SHA, run ID, attempt, conclusion, and exact subject kind. |
| External hourly or manual bounded execution | `automation_run` | `issuer_kind`, auditable `external_run_locator`, run mode/outcome, and either exact source/base links or `source_not_applicable_reason`; an `orchestration_run` parent is optional. |
| Organization-wide scheduled invocation | `orchestration_run` plus repository-scoped `automation_run` children | External scheduler identity, start/end/outcome, and one child per repository; it is not itself a source revision or writer lease. |
| Protected merge API response | `merge_revision` | Merge commit, kind, protected ref, integration time, and optional validating `workflow_evidence`; it is never aliased to a source-head check. |
| Commit Status, Check Run, formal review, or model output | `status_evidence`, `check_evidence`, `review_evidence`, or `model_evidence` respectively | Preserve native issuer, object identity, observed revision, and authority class; similar display names do not permit conversion. |

`workflow_evidence.subject_kind` is one of source revision, live-base
observation, merge revision, scheduled inventory, or explicit
`not_applicable`. A non-PR scheduled run therefore has no invented
`source_revision`; it records the protected workflow source and reason.
External run locators are identifiers or receipt URLs, never credential values.

## 4. Operations, RCA, continuation, and documentation ERD

```mermaid
erDiagram
  automation_run ||--o{ incident_hypothesis : investigates
  incident_hypothesis ||--o{ remediation_candidate : evaluates
  remediation_candidate }o--o| scheduler_decision : selected_by
  automation_run ||--o{ continuation_handoff : emits
  continuation_handoff ||--o{ handoff_record : carries
  repository_target ||--o{ writer_lease : protects
  merge_revision ||--o{ operational_acceptance : validates
  automation_run ||--o{ secret_requirement : evaluates
  incident_hypothesis ||--o{ operational_acceptance : closes_with
  documentation_artifact ||--o{ traceability_record : contributes
  traceability_record }o--o| source_revision : implementation
  traceability_record }o--o| check_evidence : verification

  incident_hypothesis {
    string incident_hypothesis_uid PK
    string symptom_summary
    string root_cause_claim
    string owner_boundary
    string hypothesis_state
  }
  remediation_candidate {
    string remediation_candidate_uid PK
    string remedy_kind
    string feasibility_state
    string rejection_reason
    bool selected_flag
  }
  continuation_handoff {
    string continuation_handoff_uid PK
    string continuation_state
    string deferred_identity_digest
    string next_action
    datetime recorded_at
  }
  handoff_record {
    string handoff_record_uid PK
    string blocked_action
    string external_prerequisite
    string continuation_action
    datetime recorded_at
  }
  operational_acceptance {
    string operational_acceptance_uid PK
    string acceptance_scenario
    string protected_commit_sha
    string consumer_repository_name
    string acceptance_outcome
  }
  secret_requirement {
    string secret_requirement_uid PK
    string secret_name
    string purpose_name
    string consumer_job_name
    bool required_flag
  }
  writer_lease {
    string writer_lease_uid PK
    string branch_ref_name
    string expected_head_sha
    string writer_identity
    datetime acquired_at
    datetime expires_at
  }
  documentation_artifact {
    string documentation_artifact_uid PK
    string document_path UK
    string maturity_state
    string artifact_digest
    datetime reviewed_at
  }
  traceability_record {
    string traceability_record_uid PK
    string requirement_id
    string decision_id
    string implementation_locator
    string evidence_locator
    string traceability_state
  }
```

A `remediation_candidate` is one materially distinct possible root-cause-changing
remedy and retains feasibility/rejection evidence. Merely naming a blocker is
not a candidate remedy. A `continuation_handoff` exists only when a finite run
must transfer exact deferred identities and next executable work because a real
practical run/tool budget ended; it is never generated merely because a prompt,
document, review request, check dispatch, commit, or merge completed.

A `handoff_record` is the concrete external-prerequisite/continuation item carried
by the handoff. `documentation_artifact` and `traceability_record` make document
fitness and requirement/decision-to-implementation evidence first-class without
claiming a database.

## 5. Governance and dispatch ERD

```mermaid
erDiagram
  organization_target ||--o{ repository_target : governs
  organization_target ||--o{ orchestration_run : schedules
  orchestration_run o|--o{ automation_run : optionally_contains
  organization_target ||--o{ ruleset_snapshot : observes
  repository_target ||--o{ ruleset_snapshot : applies_to
  automation_run ||--o{ dispatch_envelope : emits
  dispatch_envelope ||--o{ invocation_claim : claims
  automation_run ||--o{ scheduler_decision : records
  scheduler_decision }o--|| source_revision : binds

  organization_target {
    string organization_target_uid PK
    string organization_login UK
    datetime observed_at
  }
  orchestration_run {
    string orchestration_run_uid PK
    string orchestration_mode
    datetime started_at
    datetime completed_at
    string orchestration_outcome
  }
  ruleset_snapshot {
    string ruleset_snapshot_uid PK
    bigint ruleset_id
    string ruleset_digest
    string enforcement_state
    datetime observed_at
  }
  dispatch_envelope {
    string dispatch_envelope_uid PK
    string event_name
    string payload_schema_version
    string expected_head_sha
    string authenticated_actor
  }
  invocation_claim {
    string invocation_claim_uid PK
    string idempotency_key UK
    string claim_state
    datetime claimed_at
    datetime expires_at
  }
  scheduler_decision {
    string scheduler_decision_uid PK
    string decision_name
    string reason_code
    string expected_head_sha
    datetime decided_at
  }
```

A ruleset snapshot is a dated observation, not an eternal property of a
repository. An invocation claim gives at-least-once GitHub delivery an
idempotent side-effect boundary. A scheduler decision records a proposed or
completed action; it is not review evidence.

## 6. Review, sandbox, and supply-chain ERD

```mermaid
erDiagram
  source_revision ||--o{ review_thread : discusses
  source_revision ||--o{ security_finding : affects
  source_revision ||--o{ sandbox_evidence : validates
  source_revision ||--o{ sbom_snapshot : inventories
  workflow_evidence ||--o{ sandbox_evidence : publishes
  workflow_evidence ||--o{ sbom_snapshot : produces

  review_thread {
    string review_thread_uid PK
    string thread_state
    bool outdated_flag
    datetime observed_at
  }
  security_finding {
    string security_finding_uid PK
    string scanner_name
    string severity_name
    string finding_state
    string source_location
  }
  sandbox_evidence {
    string sandbox_evidence_uid PK
    string result_schema_version
    int child_exit_code
    string redaction_policy_version
    string evidence_digest
  }
  sbom_snapshot {
    string sbom_snapshot_uid PK
    string format_name
    string format_version
    string artifact_digest
    datetime generated_at
  }
```

These entities store bounded metadata and digests, not unrestricted logs,
credentials, source archives, or personal data. A scanner finding, review
thread, sandbox result, and SBOM are different evidence authorities and must not
be collapsed into one pass/fail row.

## 7. Entity definitions

| Entity | Meaning | Current physical representation |
|---|---|---|
| `automation_run` | One finite maintainer, scheduler, reviewer, or recovery execution | GitHub Actions run or external automation invocation; not centrally persisted as this schema |
| `repository_target` | Repository and protected-branch policy context | GitHub repository/ruleset APIs and configured allowlists |
| `pull_request_snapshot` | Time-bounded observation of PR state | GitHub PR API/GraphQL response |
| `source_revision` | Immutable source head under evaluation | Git commit SHA and head repository/ref |
| `base_revision` | Both PR snapshot base and independently resolved live base tip | PR API plus Git ref/API lookup |
| `merge_revision` | Protected integrated commit or merge-group revision, distinct from the PR source head | Pull request merge response and protected ref/workflow evidence |
| `check_evidence` | Check Run result with source kind and revision | GitHub Check Runs API |
| `status_evidence` | Commit status context, creator, state, and revision | Commit Status API |
| `review_evidence` | Formal review submission with author, state, and commit | Pull Request Review API/GraphQL |
| `model_evidence` | Normalized provider/model output with digest and revision; prose alias `model_judgment` | Bounded review/security artifact or job output |
| `workflow_evidence` | Workflow/run/job/attempt and artifact provenance | Actions APIs and bounded artifacts |
| `dependency_evidence` | Cross-PR, package, workflow, or release prerequisite | GitHub/package/attestation evidence |
| `incident_hypothesis` | Falsifiable RCA statement and owner boundary | Incident notes, PR body, or run artifact |
| `remediation_candidate` | One materially distinct remedy with feasibility, rejection, and selection evidence | RCA/PR review notes or bounded maintainer result; not persisted as a table |
| `continuation_handoff` | Finite-run transfer of exact deferred identities and next executable lanes after genuine budget exhaustion | External automation continuation ledger or bounded handoff artifact |
| `handoff_record` | Precise external prerequisite plus autonomous continuation item carried by a handoff | Maintainer ledger, issue, or PR comment when needed |
| `operational_acceptance` | Protected-main or real-consumer scenario proof | Workflow run, check, artifact receipt, and dated traceability row |
| `secret_requirement` | Explicit secret-to-purpose-to-job contract | `workflow_call` declaration, job environment, and security docs |
| `writer_lease` | Branch-scoped exclusive mutation intent | Live Project/issue assignment, branch/head observation, or automation ledger |
| `documentation_artifact` | Canonical document path, digest, review time, and controlled maturity state | Repository Markdown plus Git blob/commit identity |
| `traceability_record` | Requirement/decision to implementation, test/evidence, maturity and closure mapping | `TRACEABILITY.md`, ADR links, tests, workflow/check receipts |
| `organization_target` | Organization scope and observation time for fleet governance | GitHub organization API identity |
| `orchestration_run` | One fleet/hourly invocation grouping repository-scoped child runs | External continuation ledger or top-level Actions sweep receipt |
| `ruleset_snapshot` | Dated ruleset parameters, targets, exclusions, and digest | GitHub ruleset API response plus audit artifact |
| `dispatch_envelope` | Canonical authenticated event fields and schema version | `repository_dispatch`, workflow inputs, or validated local JSON |
| `invocation_claim` | Idempotency claim and completion state for one routed request | Bounded GitHub Actions artifact ledger |
| `scheduler_decision` | Exact-head action, reason, and outcome selected by a scheduler | Job summary/result JSON and workflow evidence |
| `review_thread` | Current/outdated and resolved/unresolved review conversation state | Pull request review-thread GraphQL nodes |
| `security_finding` | Scanner-specific finding with severity, state, and source location | SARIF, dependency alerts, or bounded scanner report |
| `sandbox_evidence` | Versioned result, exit semantics, redaction policy, and evidence digest | `SANDBOXED_*_RESULT` plus scrubbed bounded log/artifact |
| `sbom_snapshot` | Revision-bound software inventory artifact and digest | SPDX/CycloneDX artifact and attestation metadata |

## 8. Invariants

1. PR evidence cannot exist without a named source revision. A non-PR scheduled
   run may omit source/base relations only with an explicit `not_applicable`
   reason and a protected workflow revision.
2. `review_evidence.qualifying_human_flag` is false for authors, automated identities, dismissed reviews, comment-only records, and reviews not bound to the required current head.
3. A merge decision references the current `pull_request_snapshot`,
   `source_revision`, `base_revision`, required evidence inventory, and writer
   lease. A successful integration creates a distinct `merge_revision`.
4. `operational_acceptance` belongs to `merge_revision`, names the protected
   commit and concrete scenario, and cannot be attached directly to a PR
   `source_revision`; a source-branch run is insufficient.
5. A `secret_requirement` names one purpose and consumer job; wildcard purpose is invalid.
6. A writer lease covers one repository/ref/expected-head tuple, never the whole organization by implication.
7. A `remediation_candidate` records a materially distinct feasible/rejected remedy; stale evidence, invented authority, gate weakening, or another writer race cannot be selected as a valid remedy.
8. A `continuation_handoff` is valid only for genuine practical run/tool-budget exhaustion and must carry exact deferred identities plus next executable work. Prompt updates, documentation work, inventory, review requests, CI dispatch, Draft/Ready changes, auto-merge enablement, commits, merges, or one completed slice cannot create run-complete evidence.
9. Handoff records always name a continuation action unless every work lane is freshly proven non-actionable.
10. `documentation_artifact.maturity_state` maps to the controlled vocabulary in `DOCUMENTATION_AUDIT.md`; `active_pr` or `accepted_architecture` must never be emitted as `implemented_on_protected_main` without protected-main evidence.
11. A `traceability_record` preserves distinct requirement/decision, implementation, verification, and operational-closure locators; absence of one cannot be inferred from another authority class.
12. Credential values and unrestricted raw logs are never data-model attributes.
13. A ruleset snapshot always has an observation time and digest; stale snapshots cannot authorize a current mutation.
14. One invocation idempotency key has at most one completed claim; retries link rather than overwrite their predecessor.
15. Checks, statuses, reviews, model results, scheduler decisions, security findings, threads, sandbox results, and SBOMs retain their distinct issuer and authority class.
16. An organization-wide invocation is one `orchestration_run` with repository-scoped `automation_run` children. A standalone automation_run created by one GitHub workflow, manual recovery, or external bounded action may have no orchestration parent. Atomic evidence and mutations remain bound to one `repository_target`; a fleet parent does not imply a cross-repository writer lease.

## 9. Future persistence decision gate

Materialization is justified only if GitHub-native evidence cannot meet query latency, cross-repository history, retention, or audit requirements. Before implementation, measure those gaps and decide tenancy, access control, purpose limitation, legal retention, encryption, deletion, schema migration, disaster recovery, and reconciliation with GitHub as source of truth.