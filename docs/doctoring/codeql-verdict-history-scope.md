# CodeQL verdict history scope

## Structure and gap

Required CodeQL shards consume an authenticated status or an exact completed dispatch bound to target repository, PR, head, base and required run ID. The fallback previously paginated the complete central dispatch history. On 2026-09-27 the public workflow API reported 10,311 runs; contextual-orchestrator#1031 Python verdict job 108609837545 was executing the lookup on cwlab-s1-05. This proves the lookup workload, not that it alone caused all queue delay.

## Repair and invariant

Read the canonical required run creation timestamp with Actions read permission. Fail closed if it is missing or malformed. Query repository_dispatch runs created at or after that timestamp, retaining pagination and exact identity and terminal gate checks. A producer bound to the required run cannot exist before the required run. No elapsed-time model verdict, synthetic approval, runner-group relaxation or security exemption is introduced.

The same live API query with created >= 2026-09-27T11:08:00Z returned 3 runs. This is query cardinality evidence, not deployed latency or completed CodeQL proof.

## Verification

Real extracted Bash verdict scripts retain successful completed-dispatch recovery, later-page recovery, stale base/run rejection, unknown-state rejection and no-dispatch pending behavior. Added invalid timestamp failure coverage. The focused contract suite passed 29 tests before the explicit Actions read grant. Final combined verification is recorded in the PR.

The original extended runner-image oracle expected three literal ubuntu-24.04 jobs while protected main routes trusted workflow jobs to the central control group. The exact oracle failed on unmodified base c3e86141c. It now requires all three jobs to compare the exact trusted main workflow ref, select the control group with self-hosted/linux/x64 labels, and retain the explicit ubuntu-24.04 fallback for other refs. The six runner-image tests pass locally; combined final receipt is recorded in the PR.

## Reference

GitHub. (n.d.). *REST API endpoints for workflow runs*. Retrieved September 27, 2026, from https://docs.github.com/en/rest/actions/workflow-runs#list-workflow-runs-for-a-workflow . The created filter uses date-time search syntax; per_page supports 100. Filtered searches return up to 1,000 runs; overflow cannot authorize a false success because exact receipt matching remains mandatory.
