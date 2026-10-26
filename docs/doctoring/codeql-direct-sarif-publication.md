# CodeQL dispatch direct SARIF publication

The central `codeql-scan-dispatch.yml` successor replaces its failed Actions
`CreateArtifact` storage dependency with GitHub's documented code-scanning SARIF
REST API. It does not declare artifact storage repaired. #2607 supplies precedent
for direct code-scanning, not proof that this central consumer has run.

## Acceptance order

1. Existing trusted default-branch dispatch and live target metadata admission.
2. Existing pinned CodeQL analysis with `upload: false` and unchanged Medium+
   gate. Only trusted pinned helpers execute with Python isolated imports.
3. One public REST `POST /repos/{target}/code-scanning/sarifs`, using `commit_sha`
   (not the action-internal `commit_oid`), `refs/pull/{number}/head`, gzip/base64,
   `tool_name: CodeQL`, local checkout URI and `validate: true`. Preserve category
   `/language:{language}` via SARIF `automationDetails.id = /language:{language}/`.
   Never impersonate the default-setup analysis key; API readback records the
   actual key. An existing different category fails before POST.
4. Poll the returned upload ID with bounded GETs. Require `complete`, no errors,
   exactly one associated analysis and a second exact analysis GET. Verify
   upload ID, head commit, PR ref, CodeQL tool/category, nonempty actual analysis
   key and no analysis error **or warning** (warnings may mean data truncation).
   The processed SARIF GET is a subset, not the original raw evidence.
5. Existing GHAS base/head configuration-identity continuity, unchanged. A new
   API category/key cannot stand in for another protected-base identity. Default
   setup was `not-configured` in the retained target receipt; never disable or
   change it here. Different target setup/identity remains a real admission gate.
6. Rehash custody and recheck the actual processed analysis in the established
   `Preserve CodeQL SARIF evidence` step before existing status publication.
7. Exact-run settlement reads the authenticated scan job's log receipt and
   independently rechecks that upload/analysis with a separate read credential.
   The required receiver keeps its established Medium/GHAS/preservation step
   names. No synthetic status, altered required-check definition or gate bypass.

## Evidence and retention

Each invocation creates an exclusive, mode0700 directory outside checkout and
`RUNNER_TEMP`:
`$(dirname "$RUNNER_WORKSPACE")/.cwl-codeql-sarif/{run}/{attempt}/{language}`.
It fsyncs exact original SARIF, normalized upload SARIF, processed SARIF subset,
analysis JSON and a stateful receipt. File modes are0600. Repeated custody roots
are refused before POST; there is no automatic POST replay, token fallback,
cleanup, deletion or retention sweep. Failure after request intent leaves
`incomplete-no-replay`, raw bytes and any returned upload ID for the custodian.

The bounded `CWL_CODEQL_SARIF_RECEIPT` job-log line and job summary contain only
identity, hashes and accepted upload/analysis references, not findings/tokens.
The log is authenticated by exact run/attempt/job selection. Settlement does not
trust that text alone: it GETs the upload/analysis again. A missing log, failed
processing, mismatch or lost receipt blocks settlement. GitHub logs follow the
repository's retention (observed90 days); self-hosted original-byte custody has
**minimum7-day retention, no deletion in this implementation**. The lifecycle
parent must admit this path to the existing durable host custody/backup policy
before operational use, particularly for ephemeral workers. Local fsync is not
an off-host backup or a guarantee that an operator will not delete the host.

## Permission boundary and rollout

Same-repository scans request job `security-events: write`; no credentials are
changed. Cross-repository scans request one separate token from the existing
owned Noema App, limited to one target and only `security-events: write`. Existing
analysis-read, status-write and Actions-write tokens remain separate. An
installation lacking the new write grant fails closed; its owner must explicitly
approve that capability and accept the installation update. This source does
not change App settings, copy a personal token or infer write authority from a
successful analyses read. ADR-0033's earlier no-code-scanning-write decision is
superseded **only for this separately reviewed direct-SARIF successor**, not as
an assertion that the grant already exists.

Publish normally only after independent exact-source review and current writer
reconciliation (notably #2657's live-base metadata fix). Then protected adoption,
owned permission/custody admission and one separately authorized fresh exact-head
run are distinct gates. This private implementation authorizes none of those
remote operations; historical four quota-failed jobs stay failed. Shared
self-hosted runner admission, Medium threshold and existing lifecycle parent are
unchanged. No new runner, scheduler or framework is introduced.

## Official contract

- https://docs.github.com/en/rest/code-scanning/code-scanning#upload-an-analysis-as-sarif-data
- https://docs.github.com/en/rest/code-scanning/code-scanning#get-information-about-a-sarif-upload
- https://docs.github.com/en/rest/code-scanning/code-scanning#get-a-code-scanning-analysis-for-a-repository
- https://docs.github.com/en/code-security/code-scanning/integrating-with-code-scanning/sarif-support-for-code-scanning
