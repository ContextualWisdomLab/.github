# Strix PR baseline/provider-exhaustion incident

## Observed failure

LineageWeave PR 392 run `32530198775` reported a critical secret in the
nonexistent `frontend/src/config.ts`. The trusted changed-file mapper correctly
classified that report as unchanged, but later fallback attempts ended in
provider HTTP 410 retirement brownouts. The gate retained the earlier severity
rank and returned the same exit code used for changed-file findings, so the
outer workflow could not distinguish the cleared baseline report from a real
pull-request vulnerability.

## Root cause and repair

The quick gate already owns the exact PR-head changed-file mapping decision.
After it has classified every report as `allow_baseline`, a later provider
exhaustion now returns the dedicated status 3. The trusted reusable workflow
maps only that status to a neutral infrastructure warning. Changed, unmapped,
or manifest findings still return the blocking status, and configuration or
unexpected statuses still fail closed.

## Verification

- A three-attempt regression reproduces an unchanged critical report followed
  by two provider failures and requires status 3.
- Existing source tests require changed findings to remain blocking and clean
  unchanged findings to remain admissible.
- The central Python suite, native workflow validation, Bash syntax checks, and
  the complete Strix shell regression suite run on the final tree.
