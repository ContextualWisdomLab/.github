# CodeQL rerun recovery after pre-runner cancellation

## Problem and exact evidence

The required `CodeQL PR` workflow used `github.run_attempt != 1` as if it proved that an earlier attempt had successfully dispatched the native CodeQL scan. That inference is false when an earlier attempt is cancelled before runner assignment.

`ContextualWisdomLab/accounting-information-platform` PR #49 provides the concrete reproduction on exact head `065f9ab7038bf35db4ef129827de6ab8ee6a1038`, workflow run `33890965185`.

- Attempt 1 `Detect CodeQL languages` job `101082241642` ended `cancelled` with `runner_id=0` and `steps=[]`; its downstream compatibility job was also cancelled without execution.
- Attempt 2 `Detect CodeQL languages` job `101128192785` ended the same way: `cancelled`, `runner_id=0`, `steps=[]`; the downstream compatibility job again never executed.
- Attempt 3 finally obtained runners. The `actions` shard job `101220582725` and `python` shard job `101220582747` reached `Request current-head CodeQL scan dispatch`, found no authenticated `codeql-dispatch/<language>` terminal status, then failed solely because `RUN_ATTEMPT=3`.
- The target exact head had no `codeql-dispatch/actions` or `codeql-dispatch/python` commit status. Thus the attempt number did not identify a prior dispatch receipt or a terminal scan verdict.

This leaves an unchanged PR head permanently unable to obtain the required CodeQL result even after runner capacity recovers.

## Chosen repair

Keep the existing trust sequence:

1. re-read the live pull request and reject closed or moved heads;
2. read only `codeql-dispatch/<language>` statuses created by the expected `opencode-agent` identity;
3. if an authenticated terminal status exists, reflect it without dispatching;
4. otherwise validate the exact required run/job identity, obtain the OIDC-bound app token, and dispatch the exact repository/PR/head/language shard.

Remove the `RUN_ATTEMPT != 1` veto. A rerun attempt number is execution metadata, not evidence that the dispatch step ever ran. The native handler already serializes the same target-repository / pull-request / language tuple and re-validates live PR and wake identity before publishing a verdict or rerunning the exact required job.

This does not convert a missing CodeQL verdict to success. The required shard still fails with `verdict=pending` after dispatch and becomes successful only when the trusted handler publishes an authenticated terminal `success` status and reruns the exact job. A forged status, stale head, failed/error verdict, unavailable OIDC/app token, malformed run/job identity, or absent dispatch receipt remains fail closed.

## Executable regression

`tests/test_codeql_pr_rerun_recovery_contract.py` executes the production `Request current-head CodeQL scan dispatch` Bash block with:

- `RUN_ATTEMPT=3`;
- the same live target head;
- no authenticated CodeQL status;
- mocked OIDC and app-token exchange boundaries; and
- an exact run/job/language wake identity matching the accounting-platform reproduction.

The test requires the step to publish `verdict=pending` and to emit a `codeql-scan` repository-dispatch payload bound to `ContextualWisdomLab/accounting-information-platform`, PR #49, the exact head, run `33890965185`, job `101220582747`, and `python`.

Before the production change, the real shell block exits at the attempt-number guard before OIDC or dispatch, so this regression is RED for the observed reason. After the guard is removed, the same shell block reaches the bounded dispatch path.

## Risks, rollback, and acceptance

A manually requested rerun while a prior native dispatch is still queued but has not yet published a terminal status may replace work in the existing central target/PR/language concurrency lane. This is bounded to the same exact logical shard and does not broaden repository, head, language, credential, or merge authority. If live evidence shows harmful restart churn, the successor design should add an authenticated dispatch-receipt/pending state rather than restoring attempt-number inference.

Rollback is not `RUN_ATTEMPT != 1`; that recreates the proven dead end. A valid replacement must distinguish “prior dispatch accepted” from “prior attempt never executed” using authenticated evidence and retain exact-head fail-closed semantics.

GREEN requires all of the following on one unchanged successor head:

- the focused rerun-recovery regression passes;
- the existing `test_codeql_pr_workflow_contract.py` suite remains green;
- the complete central test, 100% coverage, docstring, workflow syntax, security and review gates pass;
- after protected integration, the unchanged accounting-platform PR #49 head is rerun and obtains a real authenticated terminal CodeQL verdict without provider/model or leaf-repository workaround.

## References

GitHub. (2026). *Re-running workflows and jobs*. GitHub Docs. https://docs.github.com/en/actions/how-tos/manage-workflow-runs/re-run-workflows-and-jobs

GitHub. (2026). *REST API endpoints for workflow runs*. GitHub Docs. https://docs.github.com/en/rest/actions/workflow-runs
