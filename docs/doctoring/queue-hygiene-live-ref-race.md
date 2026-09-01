# Queue hygiene live-reference race

## Incident

On 2026-08-26, LineageWeave PR #667 received a new same-repository head
`37cc9ab1163f213105d420618e2e8ee69ec6673d`. Its new pull-request workflows
started, but the organization queue sweep cancelled them while GitHub's open-PR
payload still exposed the preceding head. The runs were current for the branch
ref and stale only in the pull-request listing used by the cancellation map.

This was a control-plane defect, not a test failure. Re-running jobs without
repairing cancellation authority would leave the same race available to every
repository in the organization.

## Root cause

The sweep used mutable pull-request listing data as if it were the final branch
authority, then performed cancellation as a separate later mutation. Resolving
the branch ref during classification narrows the race but does not close it: a
push can land after that lookup and before the cancellation POST.

A second regression appeared while closing that window. Treating every event
without a current PR/default-branch identity as untrusted made the helper
preserve old queued `workflow_dispatch`, `workflow_run`, `repository_dispatch`,
and similar orphaned runs forever, defeating the established aged-orphan queue
cleanup contract.

## Decision

Queue hygiene now has two explicit phases.

1. **Classification.** Open pull requests provide only head repository/ref
   identities. The sweep resolves every branch through GitHub's `Get a
   reference` endpoint, bounded by `ORG_QUEUE_HYGIENE_MAX_REF_LOOKUPS`. Missing,
   malformed, inaccessible, or over-budget evidence disables destructive queue
   cleanup for that repository.
2. **Mutation-time revalidation.** Every candidate is handed to the trusted
   `scripts/ci/revalidate_queue_cancellation.sh` helper. Immediately before the
   cancellation POST the helper re-fetches the workflow run plus the live PR and
   Git ref, or the protected default branch where applicable. If identity moved,
   lookup failed, evidence is malformed, or the run is current-head authority,
   it preserves the run.

The helper receives an explicit mode:

- `superseded` permits queued or in-progress predecessor runs only after final
  current-authority revalidation;
- `aged-orphan` permits only still-queued runs that the trusted classification
  snapshot already proved are not current PR/default-branch authority. If such a
  run has started, it is preserved.

No PR-selected code is executed with the `actions: write` cancellation token.
The workflow and helper are materialized from the trusted central workflow
revision. There is no grace-period heuristic and no synthetic current-head
status: a branch ref is the commit authority for PR evidence, and the final
lookup is repeated immediately before the destructive mutation.

## Regression contract

`tests/test_queue_cancellation_revalidation.py` executes the production helper
against deterministic GitHub CLI doubles and proves:

- a head that moves after classification is preserved;
- PR/ref lookup failures fail closed;
- the sole current-head run is preserved;
- a proven predecessor is cancelled;
- queued aged-orphan manual/workflow-chain events remain cancellable; and
- an aged orphan that has started running is preserved.

`tests/test_queue_hygiene_live_ref_workflow_contract.py` pins the trusted
workflow wiring: live ref lookup, bounded lookup count, final helper invocation
for both cancellation modes, absence of direct cancellation in queue hygiene,
and preservation of the current hourly sweep / Ubuntu 24.04 / review-event
pressure controls.

The historical one-use `repair-pr1348-final-revalidation.yml` workflow and its
trigger marker were removed from the stale predecessor branch. The current-main
successor carries only the production workflow, trusted helper, executable
regressions, and this doctoring record.

## Verification

Required verification for an unchanged exact head is:

- focused executable helper tests;
- workflow contract tests;
- full repository pytest suite with 100% required statement/branch coverage;
- 100% script docstring coverage;
- `actionlint .github/workflows/pr-review-merge-scheduler.yml`; and
- `git diff --check`.

Queue saturation is an operability defect, not evidence of correctness. A
queue-saturation bypass is permissible only after the exact head is mechanically
mergeable, has no substantive current-head review/security failure, and the
remaining admission evidence is blocked solely by the saturated Actions fleet.

## Reference

GitHub. (n.d.). *REST API endpoints for Git references*. GitHub Docs. Retrieved
August 26, 2026, from https://docs.github.com/en/rest/git/refs

GitHub. (n.d.). *REST API endpoints for workflow runs*. GitHub Docs. Retrieved
September 2, 2026, from https://docs.github.com/en/rest/actions/workflow-runs
