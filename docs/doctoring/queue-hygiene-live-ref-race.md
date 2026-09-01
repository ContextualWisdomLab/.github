# Queue-hygiene live-ref race doctoring

## Incident

The organization queue sweep classified queued/in-progress Actions runs against a pull-request list snapshot and later cancelled the selected run IDs. A PR head can advance after that snapshot but before the destructive cancellation. GitHub's run and PR payloads may also lag the branch ref. Trusting either predecessor snapshot as final authority can therefore cancel the sole current-head review/check evidence and amplify Actions-capacity saturation.

## Owner and boundary

`ContextualWisdomLab/.github` owns this defect because the destructive organization queue hygiene and required review/merge scheduler are central control-plane behavior. Leaf repositories must not duplicate cancellation policy. The scheduler may use cheap PR payloads to classify candidates, but every destructive cancellation must revalidate the live run and its authoritative current ref immediately before the mutation.

## Contract

The repaired scheduler keeps a bounded initial snapshot and delegates every selected cancellation to `scripts/ci/revalidate_queue_cancellation.sh`. The helper fails closed when run/PR/ref evidence cannot be read or is malformed. For an attached PR it re-fetches the PR and resolves the head branch through the Git ref endpoint. For an Actions PR run whose `pull_requests` association is still empty, it re-fetches open PRs only to discover a matching head repository/ref and then resolves that branch ref; the payload SHA is explicitly non-authoritative. If the live ref equals the run head, the run is preserved. Default-branch push/schedule candidates are similarly revalidated against the live protected-branch head.

The final design intentionally removes the earlier serial live-ref lookup for every open PR and its repository-wide lookup ceiling. Live-ref traffic is proportional to destructive candidates, so a large open-PR queue cannot disable all cleanup merely by exceeding a fanout cap.

## Reconciliation and one-shot retirement

PR #1348 diverged while protected `main` advanced. The reconciliation tree is based on the live protected-main tree and preserves the later scheduler fixes: hourly organization sweep cadence, explicit Ubuntu 24.04 queue-draining runners, and review-event dispatch after thread updates. The obsolete `_temp_pr1348_final_revalidation_repair.yml` source-fix workflow is not carried forward. The production helper is executable in the Git tree and is covered by focused executable regressions, including the stale-PR-payload/live-ref race.

## Evidence

`tests/test_queue_cancellation_revalidation.py` covers post-classification head movement, current-head preservation, fail-closed API/ref failures, predecessor cancellation, and aged-orphan behavior. `tests/test_queue_cancellation_open_pr_revalidation.py` specifically proves that a stale open-PR payload SHA cannot authorize cancellation when the authoritative live branch ref still points at the queued run. `tests/test_queue_cancellation_scheduler_contract.py` proves the scheduler routes both cancellation modes through the helper, removes serial upfront ref fanout and the lookup ceiling, preserves current-main scheduler fixes, keeps the helper executable, and retires the temporary writer workflow.

Hosted exact-head CI, security, coverage and review evidence remain authoritative before merge; this doctoring note does not substitute for those gates.
