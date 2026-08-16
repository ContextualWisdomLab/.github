# OpenCode coverage artifact rerun contract

## Decision

The central OpenCode review workflow binds every materialized pull-request merge tree to one workflow-run attempt and one immutable GitHub Actions artifact identifier. The credential-free `coverage-evidence` job may consume only that exact artifact identifier. It never searches by a mutable artifact name and never falls back to an artifact produced by another run or attempt.

The producer also exports a step-recorded literal workflow attempt. Before download, the consumer verifies that this attempt equals its current `github.run_attempt` and that the immutable artifact ID is a positive decimal identifier. Artifact immutability selects one upload; attempt attestation proves that the producer executed in the current attempt.

The source artifact retains the existing one-day retention period. A failed-jobs-only rerun that does not rerun the successful producer is therefore expected to fail closed once that producer artifact expires. The operator response is a **full rerun or a fresh repository dispatch**, both of which rerun `coverage-source-tree` and create current-attempt evidence. Increasing retention or reusing prior-attempt source evidence is not an accepted repair.

## Incident

On August 7, 2026, failed-jobs-only rerun attempt 2 of OpenCode workflow run `31022108085` retried `coverage-evidence` for `ContextualWisdomLab/pg-llm-batch#53` without retrying the successful `coverage-source-tree` producer. The attempt-1 artifact `opencode-coverage-source` had a one-day retention period and was already expired. `actions/download-artifact` therefore returned `Artifact not found` before any current-head tests or docstring checks could run.

The product pull request was not the source of this failure. The failing boundary was the central producer/consumer lifecycle: a static name did not prove that the consumer received evidence uploaded by the current attempt.

## Contract

```mermaid
sequenceDiagram
    participant D as Repository dispatch
    participant V as validate-pr-metadata
    participant P as coverage-source-tree
    participant A as Immutable Actions artifact
    participant C as coverage-evidence

    D->>V: Exact repository, PR, base SHA, head SHA
    V->>P: Validated current-head metadata
    P->>P: Materialize exact merge tree
    P->>A: Upload attempt-scoped name
    A-->>P: artifact-id
    P-->>C: Immutable artifact-id job output
    C->>A: Download exact artifact-id
    alt Artifact belongs to current producer attempt
        A-->>C: Merge-tree archive
        C->>C: Validate archive, sandbox tests, coverage, docstrings
    else Producer was omitted or evidence expired
        A-->>C: Download failure
        C-->>D: Fail closed; require full rerun or fresh dispatch
    end
```

The implementation must preserve all of the following properties:

- `coverage-source-tree` remains the only job with repository-read and OIDC credentials for target-repository materialization.
- `coverage-evidence` remains limited to `actions: read`; it receives no repository-content token, OIDC credential, model secret, or review-write credential.
- The upload name includes `github.run_attempt` for operator diagnostics and collision resistance.
- The upload step exports the immutable `artifact-id`; the consumer validates that it is a positive decimal identifier and passes only the validated step output to `download-artifact`.
- The producer exports its step-recorded run attempt; the consumer rejects empty or prior-attempt provenance before download.
- Retention remains one day to minimize retention of private source evidence.
- Missing current-attempt evidence produces a bounded diagnostic containing the run attempt and the required recovery action.
- Exact-head metadata validation, same-repository validation, merge-tree construction, archive-member validation, isolated execution, coverage, docstring, security, and approval gates remain unchanged.

## Rerun operations

| Operator action | Producer behavior | Consumer behavior | Accepted outcome |
|---|---|---|---|
| Fresh repository dispatch | Producer runs and uploads a new attempt-scoped artifact | Downloads the producer's immutable artifact ID | Accepted |
| Full workflow rerun | Producer reruns and uploads a new attempt-scoped artifact | Downloads the new immutable artifact ID | Accepted |
| Failed-jobs-only rerun while producer is omitted | Producer attempt marker or artifact ID is missing or belongs to an earlier attempt | Rejects identity before download | Expected failure |
| Attempt to reuse an earlier artifact by name | Current-attempt identity is not proven | Rejected by contract | Rejected |
| Increase retention to hide missing producer execution | Stale source remains available longer | Does not repair attempt identity | Rejected |

## Security and privacy rationale

Artifact immutability prevents later jobs from mutating a successfully uploaded archive, but immutability alone does not identify which workflow attempt produced the archive. The producer's exact `artifact-id` closes upload-selection ambiguity, while its step-recorded attempt closes execution-attempt ambiguity. The consumer validates both before download; attempt-qualified names remain diagnostic only.

The one-day retention period is intentionally short because the archive can contain proprietary or otherwise sensitive source code. Recovery must create fresh, exact-head evidence rather than preserve source archives for a longer period. No product test executes in the credentialed producer. No trusted follow-up consumes command files after untrusted coverage execution begins.

## Rollback

Rollback consists of reverting the attempt-scoped producer output and exact-ID consumer selection together. Reverting only one side leaves the workflow unable to exchange evidence. A rollback must preserve one-day retention, credential separation, and fail-closed behavior; it must not restore mutable-name fallback across attempts.

## Verification

The permanent regression suite must verify:

1. attempt-scoped artifact naming and immutable `artifact-id` producer output;
2. producer-attested attempt output and pre-download current-attempt equality;
3. positive-decimal artifact-ID validation and exact-ID download;
4. actionable failure for missing, malformed, or prior-attempt evidence;
5. one-day retention; and
6. absence of repository, OIDC, secret, and review-write credentials from `coverage-evidence`.

The complete repository test suite, Python compilation, production statement and branch coverage, public docstring gate, security and supply-chain checks, current-head review, independent approval, and protected merge remain required.

## References (APA 7th)

GitHub. (2026a). *Downloading workflow artifacts*. GitHub Actions documentation. https://docs.github.com/en/actions/how-tos/manage-workflow-runs/download-workflow-artifacts

GitHub. (2026b). *Re-running workflows and jobs*. GitHub Actions documentation. https://docs.github.com/en/actions/how-tos/manage-workflow-runs/re-run-workflows-and-jobs

GitHub. (2026c). *actions/download-artifact* [Computer software]. GitHub. https://github.com/actions/download-artifact

GitHub. (2026d). *actions/upload-artifact* [Computer software]. GitHub. https://github.com/actions/upload-artifact
