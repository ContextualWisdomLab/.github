# Operator runbook — CWL automation control plane

Status: accepted executable baseline; placeholders must be resolved from live authority
Last reviewed: 2026-08-09

This is the command companion to [INCIDENT_RUNBOOK.md](INCIDENT_RUNBOOK.md). It never supplies an operator identity, approval, credential, retention period, rollback SHA, or escalation destination. Resolve every `<placeholder>` from live GitHub state, the incident record, repository policy, and the authorized organization roster. Do not paste secret values into a shell history, issue, comment, artifact, or receipt.

## 1. Safety contract

1. Start with read-only queries. A missing permission or `404` is not proof that a rule, private repository, or artifact does not exist.
2. Record the repository, PR, source head, live base, workflow source, run ID/attempt, event, and actor before any rerun or mutation.
3. Do not rerun a permanent integrity, authorization, TLS, ref, schema, policy, or product-test failure. Repair its cause first.
4. Do not disable a required workflow, ruleset, branch protection, security gate, or independent-review requirement as incident mitigation.
5. Rerun, disable, rollback, deletion, and credential rotation require the named authority in §3 and an incident receipt. These templates grant no authority by themselves.
6. Never force-push, rewrite shared history, delete a repository/ref, or run a broad recursive cleanup from this runbook.
7. Re-fetch live state immediately before every mutating command. If the head, base, writer, policy, or approved scope changed, stop and re-plan.

## 2. Read-only diagnosis

### 2.1 Resolve the target without inventing values

Set only non-secret identifiers. Keep the literal placeholders until the incident record or live API supplies each value.

```bash
CWL_TARGET_REPO='<owner/repository>'
CWL_PR_NUMBER='<pull-request-number>'
CWL_HEAD_SHA='<exact-source-head-sha>'
CWL_BASE_REF='<protected-base-ref>'
CWL_RUN_ID='<workflow-run-id>'
CWL_WORKFLOW_FILE='<workflow-file-name>'
CWL_CONTROL_REPO='ContextualWisdomLab/.github'
CWL_CONTROL_BASE_REF='<protected-control-base-ref>'
```

Confirm authentication and repository identity without printing a token:

```bash
gh auth status
gh repo view "$CWL_TARGET_REPO" \
  --json nameWithOwner,defaultBranchRef,visibility,url
```

### 2.2 Re-fetch PR, exact head, and live base

```bash
gh api --method GET \
  -H 'Accept: application/vnd.github+json' \
  "repos/${CWL_TARGET_REPO}/pulls/${CWL_PR_NUMBER}" \
  --jq '{number,state,draft,mergeable,mergeable_state,head:{repo:.head.repo.full_name,ref:.head.ref,sha:.head.sha},base:{repo:.base.repo.full_name,ref:.base.ref,snapshot_sha:.base.sha},updated_at}'

gh api --method GET \
  -H 'Accept: application/vnd.github+json' \
  "repos/${CWL_TARGET_REPO}/git/ref/heads/${CWL_BASE_REF}" \
  --jq '{ref,live_base_sha:.object.sha}'
```

Treat the PR's `.base.sha` as a snapshot and the ref lookup as the live base tip. Do not substitute one for the other.

### 2.3 Inspect checks, statuses, reviews, and threads

```bash
gh api --method GET \
  -H 'Accept: application/vnd.github+json' \
  "repos/${CWL_TARGET_REPO}/commits/${CWL_HEAD_SHA}/check-runs" \
  --jq '.check_runs[] | {name,status,conclusion,app:.app.slug,head_sha,started_at,completed_at,html_url}'

gh api --method GET \
  -H 'Accept: application/vnd.github+json' \
  "repos/${CWL_TARGET_REPO}/commits/${CWL_HEAD_SHA}/status" \
  --jq '{sha,state,statuses:[.statuses[] | {context,state,creator:.creator.login,created_at,target_url}]}'

gh api --method GET --paginate \
  -H 'Accept: application/vnd.github+json' \
  "repos/${CWL_TARGET_REPO}/pulls/${CWL_PR_NUMBER}/reviews" \
  --jq '.[] | {id,user:.user.login,state,commit_id,submitted_at,html_url}'
```

Review threads require GraphQL. Split the verified repository name only after `gh repo view` succeeds:

```bash
CWL_OWNER="${CWL_TARGET_REPO%%/*}"
CWL_REPOSITORY="${CWL_TARGET_REPO#*/}"

gh api graphql \
  -f owner="$CWL_OWNER" \
  -f name="$CWL_REPOSITORY" \
  -F number="$CWL_PR_NUMBER" \
  -f query='query($owner:String!,$name:String!,$number:Int!){repository(owner:$owner,name:$name){pullRequest(number:$number){reviewDecision,reviewThreads(first:100){nodes{isResolved,isOutdated,comments(first:20){nodes{author{login}path,createdAt,url}}}pageInfo{hasNextPage,endCursor}}}}}'
```

If `hasNextPage` is true, paginate before declaring zero unresolved threads.

```bash
CWL_THREAD_CURSOR='<end-cursor-from-the-previous-page>'

gh api graphql \
  -f owner="$CWL_OWNER" \
  -f name="$CWL_REPOSITORY" \
  -F number="$CWL_PR_NUMBER" \
  -f after="$CWL_THREAD_CURSOR" \
  -f query='query($owner:String!,$name:String!,$number:Int!,$after:String){repository(owner:$owner,name:$name){pullRequest(number:$number){reviewThreads(first:100,after:$after){nodes{isResolved,isOutdated,comments(first:20){nodes{author{login}path,createdAt,url}}}pageInfo{hasNextPage,endCursor}}}}}'
```

### 2.4 Inspect workflow and artifact identity

```bash
gh run view "$CWL_RUN_ID" \
  --repo "$CWL_TARGET_REPO" \
  --json databaseId,attempt,event,headBranch,headSha,status,conclusion,workflowName,createdAt,startedTime,updatedAt,url

gh api --method GET \
  -H 'Accept: application/vnd.github+json' \
  "repos/${CWL_TARGET_REPO}/actions/runs/${CWL_RUN_ID}" \
  --jq '{id,run_attempt,event,path,head_branch,head_sha,workflow_id,referenced_workflows,status,conclusion,created_at,updated_at,html_url}'

gh run list \
  --repo "$CWL_TARGET_REPO" \
  --commit "$CWL_HEAD_SHA" \
  --limit 100 \
  --json databaseId,attempt,event,headSha,status,conclusion,workflowName,createdAt,updatedAt,url

gh api --method GET \
  -H 'Accept: application/vnd.github+json' \
  "repos/${CWL_TARGET_REPO}/actions/runs/${CWL_RUN_ID}/artifacts" \
  --jq '.artifacts[] | {id,name,size_in_bytes,expired,created_at,expires_at,archive_download_url}'
```

`headSha` may identify a synthetic merge or merge-group revision for some events. Confirm the workflow's own source-receipt fields before treating it as source-head evidence. View failed logs only inside the approved evidence boundary; do not copy raw output into a public issue:

```bash
gh run view "$CWL_RUN_ID" --repo "$CWL_TARGET_REPO" --log-failed
```

### 2.5 Inspect live governance

```bash
gh api --method GET \
  -H 'Accept: application/vnd.github+json' \
  "repos/${CWL_TARGET_REPO}/rulesets?includes_parents=true" \
  --jq '.[] | {id,name,target,enforcement,source_type,source,conditions,rules}'

gh api --method GET \
  -H 'Accept: application/vnd.github+json' \
  "repos/${CWL_TARGET_REPO}/branches/${CWL_BASE_REF}/protection"

gh api --method GET \
  -H 'Accept: application/vnd.github+json' \
  "repos/${CWL_TARGET_REPO}/rules/branches/${CWL_BASE_REF}"
```

Inherited organization rules and repository-local branch protection are separate surfaces. Inspect both; a permission-limited empty response is an unresolved prerequisite, not a clean result.

## 3. Ownership and escalation record

Populate this table in the private incident record from the current authorized roster. Do not commit personal contact details to this public repository.

| Role | Required live value | Authority |
|---|---|---|
| Incident commander | `<INCIDENT_COMMANDER>` | Coordinates severity, scope, and closure; does not inherit technical bypass authority. |
| Control-plane owner | `<CONTROL_PLANE_OWNER>` | Owns central workflow/script diagnosis and reviewed rollback PR. |
| Security owner | `<SECURITY_OWNER>` | Authorizes evidence restriction, credential rotation, and security reopening/closure. |
| Organization governance owner | `<GOVERNANCE_OWNER>` | Owns rulesets, required workflows, Apps, and branch-protection changes. |
| Credential owner | `<CREDENTIAL_OWNER>` | Revokes/rotates only the affected credential through its provider. |
| Consumer owner | `<CONSUMER_OWNER>` | Approves and verifies the real product-repository canary. |
| Escalation destination | `<PRIVATE_CHANNEL_OR_CASE_URL>` | Receives sensitive coordination; never substitute a public PR comment for a security channel. |
| Decision deadline | `<TIMESTAMP_WITH_TIME_ZONE>` | Defines when to reassess, not when to weaken a gate. |

If a required owner or channel cannot be resolved, keep the affected mutation fail-closed, record the missing authority, and continue unrelated read-only or deterministic work.

## 4. Safe action templates

### 4.1 Rerun a classified transient failure

Before rerun, confirm all of the following in the incident record:

- the run belongs to the intended repository/workflow and its evidence receipt names the current source identity;
- the failure is a documented transient class, not authentication, authorization, integrity, TLS, ref, schema, policy, or test failure;
- no equivalent current-head run is queued or running;
- the retry count and total budget remain; and
- `<CONTROL_PLANE_OWNER>` authorized the rerun.

Read the run again immediately before mutation:

```bash
gh run view "$CWL_RUN_ID" \
  --repo "$CWL_TARGET_REPO" \
  --json databaseId,attempt,event,headSha,status,conclusion,workflowName,url
```

Then rerun only failed jobs, preserving the original run identity in the incident record:

```bash
gh run rerun "$CWL_RUN_ID" --repo "$CWL_TARGET_REPO" --failed
```

Do not loop this command. Re-fetch the new attempt once, record its result, and reclassify before any further action.

### 4.2 Disable only an optional affected workflow

Disabling is never an acceptable way to make a required gate disappear. Use this only when live ruleset inspection proves the workflow is optional, the governance owner approves the exact scope, the safer fallback is documented, and a re-enable condition exists.

```bash
gh workflow view "$CWL_WORKFLOW_FILE" --repo "$CWL_CONTROL_REPO" --yaml
```

After recording `<GOVERNANCE_OWNER>`, `<INCIDENT_ID>`, the current workflow state, and the re-enable condition, the authorized mutation is:

```bash
gh workflow disable "$CWL_WORKFLOW_FILE" --repo "$CWL_CONTROL_REPO"
```

Re-enable after the reviewed repair or rollback reaches protected main:

```bash
gh workflow enable "$CWL_WORKFLOW_FILE" --repo "$CWL_CONTROL_REPO"
```

If the path is required, deploy a narrow fail-closed guard through a protected pull request instead of disabling the workflow or changing the ruleset.

### 4.3 Roll back through a protected revert pull request

Resolve `<BAD_COMMIT_SHA>`, `<KNOWN_GOOD_SHA>`, and `<INCIDENT_ID>` from GitHub history and the incident decision. Prefer reverting the smallest causal commit. Do not use `reset`, a force-push, or a direct write to the protected branch.

Run the template only from a verified clone of `$CWL_CONTROL_REPO`. `git status --short` must be empty before creating the rollback branch; preserve and stop for any existing work rather than discarding it.

```bash
CWL_BAD_COMMIT_SHA='<causal-commit-sha>'
CWL_KNOWN_GOOD_SHA='<reviewed-known-good-sha>'
CWL_INCIDENT_ID='<incident-id>'
CWL_ROLLBACK_BRANCH="incident/${CWL_INCIDENT_ID}-rollback"

gh repo view "$CWL_CONTROL_REPO" --json nameWithOwner,defaultBranchRef,url
git remote get-url origin
git status --short
git check-ref-format --branch "$CWL_ROLLBACK_BRANCH"
git fetch origin "$CWL_CONTROL_BASE_REF"
git switch --create "$CWL_ROLLBACK_BRANCH" "origin/${CWL_CONTROL_BASE_REF}"
git show --stat --oneline "$CWL_BAD_COMMIT_SHA"
git show --stat --oneline "$CWL_KNOWN_GOOD_SHA"
git revert --no-commit "$CWL_BAD_COMMIT_SHA"
git diff --cached --check
```

Run the original reproduction, focused/full tests, security checks, and documentation contract before committing. Inspect the staged tree and then create a normal reviewed commit and PR:

```bash
git status --short
git diff --cached
git commit -m "revert: contain ${CWL_INCIDENT_ID}"
git push --set-upstream origin "$CWL_ROLLBACK_BRANCH"
gh pr create \
  --repo "$CWL_CONTROL_REPO" \
  --base "$CWL_CONTROL_BASE_REF" \
  --head "$CWL_ROLLBACK_BRANCH" \
  --title "revert: contain ${CWL_INCIDENT_ID}" \
  --body-file '<reviewed-rollback-pr-body-file>'
```

The PR body must name the causal commit, known-good comparison, security trade-off, test evidence, rollback-of-rollback plan, consumer canary, and reopen conditions. A known-vulnerable version is not a valid rollback target; disable only the affected optional path or add a narrow fail-closed guard instead.

## 5. Evidence retention and deletion

No retention duration is defined by this runbook. Resolve and record the applicable repository, organization, contractual, privacy, and incident policy values:

| Evidence class | Retention value to resolve | Minimum handling rule |
|---|---|---|
| Raw workflow logs and service output | `<RAW_LOG_RETENTION_FROM_POLICY>` | Restrict access; retain only as long as the incident and governing policy require; never treat a credential as evidence. |
| Workflow artifacts/source archives | `<ARTIFACT_RETENTION_FROM_POLICY>` | Verify run/name/digest/source before access; delete expired-purpose copies. |
| Review/check/status records | `<GITHUB_RECORD_RETENTION_FROM_POLICY>` | Preserve exact identity and decision history subject to platform and legal policy. |
| Minimal incident receipt | `<RECEIPT_RETENTION_FROM_POLICY>` | Retain hashes, IDs, classifications, decisions, owners, and bounded redacted excerpts rather than raw sensitive data. |
| Business PII | `<PII_RETENTION_AND_PURPOSE_POLICY>` | Purpose-limit access and deletion; involve the data owner before disclosure or removal. |

For suspected credential disclosure, rotate/revoke first. Then enumerate the exact artifacts before deletion:

```bash
gh api --method GET \
  -H 'Accept: application/vnd.github+json' \
  "repos/${CWL_TARGET_REPO}/actions/runs/${CWL_RUN_ID}/artifacts" \
  --jq '.artifacts[] | {id,name,size_in_bytes,expired,created_at,expires_at}'
```

Only after `<SECURITY_OWNER>` approves the exact artifact ID and a bounded redacted receipt exists:

```bash
CWL_ARTIFACT_ID='<approved-artifact-id>'

gh api --method GET \
  -H 'Accept: application/vnd.github+json' \
  "repos/${CWL_TARGET_REPO}/actions/artifacts/${CWL_ARTIFACT_ID}" \
  --jq '{id,name,size_in_bytes,expired,created_at,expires_at}'

gh api --method DELETE \
  -H 'Accept: application/vnd.github+json' \
  "repos/${CWL_TARGET_REPO}/actions/artifacts/${CWL_ARTIFACT_ID}"
```

Deleting run logs is separately destructive and removes diagnostic evidence. Use it only after rotation, approval, and receipt capture:

```bash
gh api --method DELETE \
  -H 'Accept: application/vnd.github+json' \
  "repos/${CWL_TARGET_REPO}/actions/runs/${CWL_RUN_ID}/logs"
```

Record who approved deletion, exact target IDs, reason, timestamp, what minimal receipt remains, and whether a legal/security hold prevented deletion. Never delete all artifacts, caches, runs, or comments with an unresolved glob or broad loop.

## 6. Protected-main and consumer canary receipt

Copy this template into the authorized incident/traceability record and replace every placeholder with observed evidence. `N/A` requires a reason; blanks do not prove acceptance.

```markdown
### Operational acceptance receipt — <INCIDENT_ID>

- Decision timestamp and time zone: <TIMESTAMP_WITH_TIME_ZONE>
- Incident commander: <INCIDENT_COMMANDER>
- Security/governance approver: <APPROVER>
- Central repository: <CONTROL_REPOSITORY>
- Integrated protected commit: <PROTECTED_COMMIT_SHA>
- Trusted workflow file and source SHA: <WORKFLOW_FILE>@<WORKFLOW_SOURCE_SHA>
- Protected-main run ID / attempt / URL: <RUN_ID> / <RUN_ATTEMPT> / <RUN_URL>
- Consumer repository and PR: <CONSUMER_REPOSITORY>#<PR_NUMBER>
- Consumer exact source head: <SOURCE_HEAD_SHA>
- Consumer live base ref and SHA at decision: <BASE_REF>@<LIVE_BASE_SHA>
- Required ruleset/check inventory source: <LIVE_RULESET_OR_API_RECEIPT>
- Positive scenario and expected result: <POSITIVE_SCENARIO> / <EXPECTED_RESULT>
- Positive observed result: <OBSERVED_RESULT_AND_EVIDENCE_URL>
- Negative control and expected rejection: <NEGATIVE_CONTROL> / <EXPECTED_REJECTION>
- Negative observed result: <OBSERVED_REJECTION_AND_EVIDENCE_URL>
- Credential/provider class used, never value: <CREDENTIAL_OR_PROVIDER_CLASS>
- Rollback target and rehearsal/result: <KNOWN_GOOD_SHA> / <ROLLBACK_EVIDENCE>
- Residual risks and owners: <RISK_OWNER_LIST>
- Retention/deletion policy applied: <POLICY_AND_TARGET_IDS>
- Reopen conditions: <CONCRETE_CONTRADICTORY_EVENTS>
- Final disposition: <ACCEPTED_OR_NOT_ACCEPTED>
```

Acceptance is scenario-specific. Reopen when a later protected-main/consumer run contradicts the receipt, the evidence identity was wrong, a new publication path appears, or policy/configuration drift changes the trust boundary.
