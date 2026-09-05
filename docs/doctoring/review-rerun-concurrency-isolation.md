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

Read-only follow-up also exposed a second cancellation risk in the existing
same-head coalescer: REST PR associations can move to a newer head while the
run retains its original `head_sha`. The shared identity matcher now requires
that recorded revision to match the live PR before considering associations.
See the [live samples and regression evidence](current-head-run-coalescing.md#refreshed-association-correction-2026-09-05).

## Checks

`tests/test_review_rerun_concurrency.py` evaluates the actual group expressions
with a restricted stdlib AST interpreter, without `eval`, workflow execution,
or a new dependency. Before the workflow edits, 17 assertions failed and five
passed. The tests cover numeric/string attempts, distinct retries, first-push
coalescing, repository/PR isolation, non-PR fallback, and native/dispatch parity.
Existing Noema and central dispatch cleanup tests also exercise retry metadata;
they prove selection and API requests, not GitHub terminal cancellation.
The coalescer's separate three-file suite passes 57 tests with 100% statement
and branch coverage (252 statements, 118 branches). Six new tests failed on the
old source before the shared guard; an older positive fixture was corrected
because it conflated runtime `GITHUB_SHA` with REST run `head_sha`.

Run the focused suite:

```sh
uv run pytest -q tests/test_review_rerun_concurrency.py tests/test_required_workflow_queue_contract.py tests/test_noema_orchestrator_workflow_contract.py tests/test_opencode_required_rerun_capacity.py tests/test_opencode_required_verdict_regression.py tests/test_strix_rerun_job_selection.py tests/test_current_head_run_coalescer.py tests/test_current_head_run_coalescer_review_regressions.py tests/test_current_head_coalescer_self_cancellation.py tests/test_opencode_live_draft_state_regression.py tests/test_noema_review_gate.py tests/test_pr_review_merge_scheduler.py tests/test_pr1669_cancel_stale_opencode_runs.py tests/test_opencode_workflow_shell_syntax.py
```

Local actionlint 1.7.12 hung writing large shell input before starting its child
process. A diagnostic stack matched upstream `process.go`; this failed run is
not passing evidence. The additional `-shellcheck= -pyflakes=` invocation
passed workflow syntax/expression validation only, not external lint.

An isolated build of official actionlint commit
`011a6d15e749bb3f2d771eed9c7aa0e7e3e10ee7` avoids that tool deadlock without a
system installation or project dependency change. Full lint then reported the
same 29 ShellCheck diagnostics on head and base; neither was a passing run.
The dispatch workflow now removes a redundant case pattern, combines repeated
append redirects, and uses Bash filename discovery without changing shell
options. Literal child-shell/jq/GraphQL programs and Markdown backticks carry
command-scoped SC2016 annotations, not a blanket suppression. Full lint with
ShellCheck enabled now exits zero without output on all four changed workflows.

Review caught an intermediate annotation inserted inside a continued `printf`,
which lint alone missed. A new test executes that existing body-building
function: it first failed with `## Findings: command not found`, then passed
after removal of the misplaced annotation. The defective intermediate edit
was not committed. No hosted gate was changed or disabled.

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
- rhysd. (n.d.). [Pinned upstream process runner](https://github.com/rhysd/actionlint/blob/011a6d15e749bb3f2d771eed9c7aa0e7e3e10ee7/process.go).

Retrieved 2026-09-05. These platform/tool sources ground a configuration bug;
no research-paper PDF is needed for this bounded repair.
