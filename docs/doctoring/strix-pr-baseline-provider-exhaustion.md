# Strix PR baseline/provider-exhaustion incident

## Observed failure

LineageWeave PR 392 run `32530198775` reported a critical secret in the
nonexistent `frontend/src/config.ts`. The trusted changed-file mapper correctly
classified that report as unchanged, but later fallback attempts ended in
provider HTTP 410 retirement brownouts. The gate retained the earlier severity
rank and returned the same exit code used for changed-file findings, so the
outer workflow could not distinguish the cleared baseline report from a real
pull-request vulnerability.

A later central PR run reported zero vulnerabilities and then failed before
scanning when Strix's local Caido process did not accept connections on
`127.0.0.1:48080`; the outer workflow did not yet recognize that exact scanner
bootstrap outage as infrastructure.

## Root cause and repair

The quick gate already owns the exact PR-head changed-file mapping decision.
After it has classified every report as `allow_baseline`, provider exhaustion
now returns the dedicated status 3, including a deployment with no distinct
fallback configured. The trusted reusable workflow maps only that status to a
neutral infrastructure warning. Changed, unmapped, or manifest findings still
return the blocking status, and configuration or unexpected statuses still
fail closed.

The outer workflow also recognizes only the observed `loginAsGuest` retry
exhaustion with curl exit 7 against Strix's fixed local Caido port. It is neutral
only when no positive vulnerability or severity signal exists; every other
runtime failure remains blocking.

## Verification

- A three-attempt regression reproduces an unchanged critical report followed
  by two provider failures and requires status 3.
- A primary-only regression requires the same trusted baseline outcome without
  treating the absent fallback as a pull-request finding.
- Existing source tests require changed findings to remain blocking and clean
  unchanged findings to remain admissible.
- A workflow regression requires the exact Caido bootstrap outage to be neutral
  with zero findings and blocking when any vulnerability is reported.
- The central Python suite, native workflow validation, Bash syntax checks, and
  the complete Strix shell regression suite run on the final tree.
