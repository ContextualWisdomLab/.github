# Preserve runner routing observations

## Source defect

The queue-health normalizer discarded optional REST job `labels`,
`runner_group_id` and `runner_group_name`. The SLO action also described every
runner-assignment incident as GitHub-hosted, including self-hosted work.

The repair preserves these fields in collected snapshots and JSON report rows.
Missing/null data stays unknown; explicit empty labels and zero group ID remain
explicit. Malformed values fail validation. Existing assignment, exact-head
identity, queue age, conclusion and blocker decisions are unchanged. The HTML
table is unchanged; routing details are available in the JSON report.

## Interpretation boundary

Labels are routing metadata, not isolation attestation. Assigned group metadata
is not the requested workflow group. A null assigned group does not prove that
a requested group is absent, offline, unauthorized or full. No capacity,
repository access, physical-host separation or isolation verdict is inferred.

The patch is diagnostic preservation only. It neither activates runner capacity
nor completes a hosted-to-self-hosted migration. Existing operational owners
must still establish actual disposable isolation and capacity before activation.
It adds no registration, credential creation, access, network or workflow change.

## Local verification

The new regressions failed 11 times on unchanged production source because
routing fields were missing or malformed routing was not rejected. A setup-time
missing pytest error and an initial test import error were not counted as RED.
After repair and a collector-to-JSON regression, all 98 queue-health tests passed
normally and all 98 passed with `GITHUB_ACTIONS=true`, using Python 3.12.

This is scoped local verification, not the full repository suite, actual runner
execution, required Checks, formal approval or protected integration. No existing
PR branch was modified. Source publication must remain separate from operational
readiness and the original migration request remains incomplete.
