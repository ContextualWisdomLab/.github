# Strix workflow-version evidence boundary

## Finding

On 2026-08-12, central PR #937 head
`2c6f4323ac864587d767824464379678ebfe888a` had a green Strix job
`31555003423` / `93985504528`, but the job steps did not include
`Validate Strix report provenance`. Its artifact had no `evidence-binding.json`,
and the log contained provider 429/410 failures plus the old neutral-skip
message. The run was bound to the PR head SHA at the job level, but it executed
the protected-base workflow definition, as GitHub requires for
`pull_request_target`.

## Required control

Do not use that run as evidence that the PR changed workflow is safe. The
non-privileged `strix-workflow-contract` workflow reads the PR workflow as data
and rejects missing provenance or fail-open markers. Once the central
workflow is integrated, rerun the linked security scans from the active
protected workflow and require a current-head `evidence-binding.json`, a
non-empty structured report, no provider-failure markers, and a final exact-head
re-fetch before merge.

No provider credential is exposed to the contract job, and no PR-controlled
workflow or source is executed in the privileged `pull_request_target` context.
