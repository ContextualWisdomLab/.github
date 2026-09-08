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
2. read only base-bound `codeql-dispatch/<language>/<base_sha>` receipts created by the expected `opencode-agent` identity; for the `.github` self-repository token fallback, require the exact protected dispatcher run, language job, conclusion, and preserved SARIF artifact instead of trusting `github-actions[bot]` or its URL alone;
3. if an authenticated terminal status exists, reflect it without dispatching;
4. otherwise collect the exact failed language-job map, obtain the OIDC-bound app token, and dispatch the pending matrix once for the exact repository/PR/head/base/run.

Remove the coordinator's `github.run_attempt == 1` veto. A rerun attempt number is execution metadata, not evidence that the coordinator dispatched. Every attempt first checks the complete authenticated receipt history; one with terminal receipts emits no dispatch, while an attempt whose predecessor never ran can recover.

This does not convert a missing CodeQL verdict to success. Required shards still fail with `verdict=pending`; the handler waits for all trusted terminal receipts, validates the exact run and failed-job map, and settles that run. A forged status, stale head/base, failed/error verdict, unavailable OIDC/app token, malformed run/job identity, extra failed job, or absent receipt remains fail closed.

## Follow-up review: complete status-history authority

Current-head review on `e72ae30e3e989396b8cfdd1d850f7db1f45c6a7e` found a second defect in the same evidence boundary. `GET /commits/{sha}/statuses` was read without pagination. Treating an empty default response page as proof that no authenticated terminal `codeql-dispatch/<language>` verdict exists is unsafe on a commit with enough status history to push an older trusted verdict to a later page. The recovery path could then redispatch even though terminal authority already existed.

The rejected alternatives are increasing an assumed first-page size without pagination, trusting the combined commit-status summary, or restoring `RUN_ATTEMPT` inference. None proves absence of the exact creator-bound language status across the complete history.

RED `acfa17e84f1ef6a0da5b93c642fcdf0d67d1d814` extends the focused contract to require a paginated, slurped status lookup and page-flattening before absence can authorize redispatch. Minimal repair `7628274f3e146e32fba124fe3e21e1fef8b107b3` changes only that read boundary: `gh api --paginate --slurp .../statuses?per_page=100` collects every page, and the existing trusted-context/creator filter runs across `.[][]`. Live PR/head validation, OIDC/app-token exchange, exact run/job/language binding, pending fail-closed behavior, handler validation and concurrency are unchanged.

The security effect is narrower than “more reliable pagination”: **absence is now established over the complete status population before dispatch authority is exercised**. An authenticated terminal status on any page therefore prevents a redundant redispatch. If GitHub changes the status API representation, the focused regression must fail rather than silently fall back to first-page semantics.

## Executable regression

`tests/test_codeql_pr_rerun_recovery_contract.py` executes the production `Dispatch current-head CodeQL scan` coordinator with:

- the same live target head;
- only an old-base authenticated CodeQL status;
- mocked OIDC and app-token exchange boundaries; and
- an exact current-run language/job map.

The test requires later attempts to remain admitted and emit one `codeql-scan` payload for pending languages. The companion status-history contract requires `--paginate --slurp`, an explicit `per_page=100`, and page flattening before the trusted verdict filter.

Before the production change, the original regression exits at the attempt-number guard before OIDC or dispatch. Before the pagination repair, the status-history contract fails because the production read asks only for the default first page. After both repairs, the same shell block reaches the bounded dispatch path only when the complete authenticated status history contains no terminal verdict.

## Risks, rollback, and acceptance

A later required-run attempt while a prior native dispatch is still queued and has no terminal receipt may replace work in the existing central target/PR concurrency lane. This is bounded to the same exact pull request and current head/base. If live evidence shows harmful restart churn, the successor should add an authenticated pending receipt rather than restoring attempt-number inference.

Pagination adds API reads proportional to commit-status history, bounded at 100 statuses per page. That cost is accepted because a false “verdict absent” decision authorizes external dispatch; status absence therefore requires complete evidence rather than a first-page heuristic.

Rollback is not `RUN_ATTEMPT != 1` and not a non-paginated status read; either recreates a proven dead end or an incomplete-authority check. A valid replacement must distinguish “prior dispatch accepted” from “prior attempt never executed” using authenticated complete-history evidence and retain exact-head fail-closed semantics.

GREEN requires all of the following on one unchanged successor head:

- the focused rerun-recovery and complete-status-history regressions pass;
- the existing `test_codeql_pr_workflow_contract.py` suite remains green;
- the complete central test, 100% coverage, docstring, workflow syntax, security and review gates pass;
- after protected integration, the unchanged accounting-platform PR #49 head is rerun and obtains a real authenticated terminal CodeQL verdict without provider/model or leaf-repository workaround.

## References

GitHub. (2026). *Re-running workflows and jobs*. GitHub Docs. https://docs.github.com/en/actions/how-tos/manage-workflow-runs/re-run-workflows-and-jobs

GitHub. (2026). *REST API endpoints for workflow runs*. GitHub Docs. https://docs.github.com/en/rest/actions/workflow-runs

GitHub. (2026). *REST API endpoints for commit statuses*. GitHub Docs. https://docs.github.com/en/rest/commits/statuses
