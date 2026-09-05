# Review rerun concurrency isolation

## Cause and scope

G-02/G-03 follow-up, inspected on 2026-09-05 against central main
`6d7fbebec8aec31d88a30a36e71ca5b3925d241d`. This is a proposed repair, not
protected-main or hosted-runtime evidence. Procedure documentation is tracked
separately in #1885.

GitHub reruns retain their run ID and increment `github.run_attempt`. A rerun
of an older PR event therefore re-enters the same cancellable PR group unless
the expression distinguishes attempts. It can cancel current evidence before
the stale-head guard executes. Required OpenCode's receipt wakeup intentionally
uses `rerun-failed-jobs`, so disabling reruns would break its existing flow.

The five cancellable groups in Strix, Noema, Required OpenCode, Strix cleanup,
and OpenCode dispatch now use `rerun-<run_id>` for attempts greater than one.
First attempts retain the workflow/repository/PR key and cancellation policy.
No jobs, dependencies, permissions, provider routes, or gate exceptions are
added. Live-head admission and publication checks remain mandatory.

## Checks

`tests/test_review_rerun_concurrency.py` evaluates the actual group expressions
with a restricted stdlib AST interpreter, without `eval`, workflow execution,
or a new dependency. Before the workflow edits, 17 assertions failed and five
passed. The tests cover numeric/string attempts, distinct retries, first-push
coalescing, repository/PR isolation, non-PR fallback, and native/dispatch parity.
Existing Noema and central dispatch cleanup tests also exercise retry metadata;
they prove selection and API requests, not GitHub terminal cancellation.

Run the focused suite:

```sh
uv run pytest -q tests/test_review_rerun_concurrency.py tests/test_required_workflow_queue_contract.py tests/test_noema_orchestrator_workflow_contract.py tests/test_opencode_required_rerun_capacity.py tests/test_opencode_required_verdict_regression.py tests/test_strix_rerun_job_selection.py tests/test_current_head_run_coalescer.py tests/test_opencode_live_draft_state_regression.py tests/test_noema_review_gate.py tests/test_pr_review_merge_scheduler.py tests/test_pr1669_cancel_stale_opencode_runs.py
```

Local actionlint 1.7.12 hung writing large shell input before starting its child
process. A diagnostic stack matched upstream `process.go`; this failed run is
not passing evidence. The additional `-shellcheck= -pyflakes=` invocation
passed workflow syntax/expression validation only, not external lint. No hosted
gate was changed or disabled.

## Remaining limits and acceptance

- A new first attempt cannot natively cancel an isolated historical retry.
  Existing Strix/Required OpenCode cleanup jobs and Noema's in-job cleanup
  require a runner. Adding another cleanup job would not guarantee service
  under runner saturation.
- Central OpenCode dispatch retries are considered by the existing scheduler's
  `dispatch_opencode_review` cleanup, not Required OpenCode's local cleanup.
  This requires the scheduler to reach that branch; Strix waits, credential
  waits, and earlier returns can leave a retry active. Immediate recovery of
  every old retry is not claimed.
- Delayed *first* attempts still share a cancellable key; this repair does not
  establish chronological scheduling or solve that separate arrival-order race.
- Older runs reuse their original workflow revision. After protected merge,
  create fresh run evidence under the new revision and verify that rerunning
  its older PR event preserves the newer run. Observe any cleanup candidate
  reach `completed/cancelled`; an accepted cancel request is insufficient.
- Hosted lint/security checks, independent exact-head approval, protected merge,
  and the live probe remain required. The 41-item objective completion count
  does not increase from these local checks alone.

## Sources

- GitHub. (n.d.). [Contexts reference](https://docs.github.com/en/actions/reference/workflows-and-actions/contexts).
- GitHub. (n.d.). [Control workflow concurrency](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency).
- GitHub. (n.d.). [Re-running workflows and jobs](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/re-run-workflows-and-jobs).
- rhysd. (n.d.). [actionlint v1.7.12 process runner](https://github.com/rhysd/actionlint/blob/v1.7.12/process.go#L23-L41).

Retrieved 2026-09-05. These platform/tool sources ground a configuration bug;
no research-paper PDF is needed for this bounded repair.
