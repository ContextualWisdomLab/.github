# Review-repair quality workflow identity RCA

## 2026-09-04 consolidation

The standalone compatibility workflow has now been retired. Its contract suite
and path ownership moved into
`.github/workflows/agent-review-runtime-quality-ci.yml`, where the existing
affected-suite selector runs it only for review-repair changes. This removes one
independent checkout, Python setup, and dependency-install job per matching PR
without changing the repair worker, scheduler, permissions, or model routing.
The consolidated PR workflow keeps the required
`agent-review-runtime-quality-${{ github.repository }}-${{ github.event.pull_request.number }}`
group with `cancel-in-progress: true`.

## Status

Recorded 2026-09-01 against protected `ContextualWisdomLab/.github` `main@b4f7b082536d2be8dceab0a40a484161b50e5acd` and repair PR #1573.

## Incident

The central workflow at `.github/workflows/hourly-nvidia-nim-review-repair.yml` was named **Hourly NVIDIA NIM Review Repair**, but the executable source contradicted both halves of that identity:

- it had no `schedule` trigger and therefore did not own an hourly writer cadence;
- it had read-only `contents: read` permission and executed only repository contract tests, coverage, docstring checks, `compileall`, and `git diff --check`;
- it did not invoke OpenCode or any model provider;
- the write-capable repair boundary already lived in `.github/workflows/pr-review-autofix.yml` and routed OpenCode through the vendored contextual-orchestrator sidecar with the virtual model `contextual-orchestrator/orchestrator/free`.

The stale identity survived the earlier direct-NIM-to-gateway migration because executable worker routing and the focused quality gate evolved independently. Draft PR #1527 corrected prose only and explicitly left workflow behavior and identity unchanged, so it could not close this control-plane naming/responsibility gap.

## Root cause

The repository conflated three separate responsibilities under one historical label:

1. **Cadence ownership** — thin product-specific `*-hourly-review-repair.yml` callers own schedules.
2. **Repair execution** — `pr-review-fix-scheduler.yml` selects bounded work and `pr-review-autofix.yml` owns the write-capable exact-head repair worker.
3. **Contract verification** — `.github/workflows/hourly-nvidia-nim-review-repair.yml` is a PR/push-only read-only quality gate.

When direct NVIDIA NIM execution was retired in favor of ADR-0003's contextual-orchestrator gateway, responsibility (2) was migrated but responsibility (3)'s display identity and explanatory contract were not. The result was executable metadata that suggested a scheduled direct-provider writer where none existed.

A second lifecycle defect became visible during repair. GitHub retains workflow registry identities after YAML paths disappear; this repository already tracks that control-plane fact in #1026. Creating a replacement workflow path and deleting the historical path would therefore create a new workflow ID while risking an orphaned old ID. That is not a safe rename.

## Repair

PR #1573 keeps the historical path `.github/workflows/hourly-nvidia-nim-review-repair.yml` as a **registry-identity compatibility boundary** while changing the workflow itself to the truthful display name **Contextual Orchestrator Review Repair Quality CI**. The workflow remains PR/push-only and `contents: read`; no hourly schedule or second writer is added.

The path is deliberately not customer or architecture terminology. The display name, comments, job name, tests, and doctoring carry the current responsibility. No replacement `.github/workflows/contextual-orchestrator-review-repair-quality.yml` remains in the final tree.

The underlying writer remains unchanged:

```text
hourly product caller
  -> pr-review-fix-scheduler.yml
  -> repository_dispatch: pr-review-autofix
  -> pr-review-autofix.yml
  -> contextual-orchestrator sidecar
  -> contextual-orchestrator/orchestrator/free
```

The sidecar continues to register the existing five provider credentials (`BYTEZ_API_KEY`, `NVIDIA_NIM_API_KEY`, `NVIDIA_NIM_API_KEY_SUB`, `OPENROUTER_API_KEY`, `OPENAI_API_KEY`) into its process-local provider registry. Provider keys are not promoted to workflow identity and no direct-provider fallback is introduced.

## TDD and hosted evidence

The first PR commit, `6279b0c8fe7f41f2ec61be728da41d9c2c599e84`, changed `tests/test_hourly_scheduler_runtime_budget.py` before implementation and rejected the old display identity. Its initial hypothesis also required a new path. That source-level RED correctly exposed the identity defect, but the later workflow-lifecycle inspection showed that deleting the old path would violate the repository's own orphan-workflow governance boundary. The test was refined rather than preserving an unsafe implementation hypothesis: it now requires the stable historical path, forbids a replacement path, and requires the contextual-orchestrator display/worker contract.

An intermediate replacement-path implementation produced hosted run `33491072818`. The workflow itself materialized and executed 2,253 passing tests with 100% reported production coverage, but one existing fake-dispatch fixture failed with bash exit 141/SIGPIPE because the fake `gh` process did not drain `--input -`. That is independent of the workflow identity repair. PR #1573 incorporates the exact one-line fixture root repair from closed #1561 (`cat >/dev/null`) while leaving production dispatch behavior unchanged.

All intermediate replacement-path runs are predecessor evidence only. Final acceptance requires exact-current-head execution through the preserved workflow registry identity and terminal success; queued, pending, skipped, cancelled, or predecessor evidence is non-passing.

## 2026-09-02 merged-PR stale-run follow-up

Protected `main@6f70174e338013fec9a000311bc72312f5d4dbf9` still exposed a lifecycle gap even though the workflow already used a PR-stable concurrency group with `cancel-in-progress: true`. Run `33577763081` belonged to merged PR #1651 at exact head `9481922748e2c51f36c86400e60d99533189e4be`. The run was created at 01:02:17Z, PR #1651 merged at 01:08:37Z, but no later same-group event existed to supersede the queued run. GitHub finally assigned a runner at 08:47:34Z; the obsolete quality job then spent about six minutes installing tooling and executing contract tests before failing at 08:53:40Z. The observed multi-hour duration was therefore queue residence, not one continuously occupied runner, but the merged PR still consumed scarce runner capacity after its evidence ceased to be authoritative.

The causal defect is that `pull_request` used its default activity types, which exclude `closed`. PR-stable concurrency can cancel an older run only when a newer run in the same group exists; merging/closing the PR produced no workflow run, so there was no scheduler-side cancellation event. A runner-backed cleanup job would recreate the prior no-op cleanup anti-pattern, so the repair instead adds `closed` to the workflow trigger while preserving the default `opened`, `synchronize`, and `reopened` types. The ordinary contract job is guarded to skip on `closed`. This gives GitHub a same-PR concurrency event that can retire queued/in-progress predecessor work while the close run itself has no runner-backed job.

The regression was committed first in `tests/test_hourly_scheduler_runtime_budget.py`: it requires the explicit close trigger, the PR-stable group, `cancel-in-progress: true`, and the closed-event job guard. The implementation then changed only the workflow admission lifecycle. It does not cancel another PR, does not execute untrusted head code with write credentials, does not grant `actions: write`, and does not weaken any test/review/security gate. Push-triggered quality CI remains unchanged.

## Security and governance boundary

- No secret, reviewer identity, merge authority, branch-protection rule, or status is changed.
- No direct NVIDIA NIM HTTP endpoint or hard-coded provider model is introduced.
- The quality workflow remains `contents: read` only.
- The write-capable worker remains exact-head-bound and governed by its existing sealed path, revalidation, credential stripping, and protected push contracts.
- The stable workflow path avoids manufacturing an untracked orphan Actions identity.
- Queued, pending, skipped, cancelled, predecessor-head, or stale evidence is not treated as passing.
- Closed-event retirement relies on workflow-level PR-stable concurrency; the skipped close job requires no write credential and executes no untrusted PR source.

## Rollback

Rollback is a normal revert of the display/contract correction only after proving that doing so does not reintroduce misleading provider/cadence ownership. Do not delete/recreate the workflow path merely to rename it, restore a direct-NIM execution path, add a duplicate hourly schedule, or weaken the contextual-orchestrator fail-closed contract. Do not remove close-event retirement unless an equivalent trusted scheduler-side retirement mechanism is already deployed and regression-covered.

## References

ContextualWisdomLab. (2026). *ADR-0003: Contextual-orchestrator vendored free/ZDR review routing*. `docs/adr/0003-contextual-orchestrator-vendored-free-zdr.md`.

ContextualWisdomLab. (2026). *Inventory orphaned workflow identities* (Issue/PR #1026). GitHub repository governance evidence.

GitHub. (n.d.). *Workflow syntax for GitHub Actions*. GitHub Docs. https://docs.github.com/actions/using-workflows/workflow-syntax-for-github-actions

GitHub. (n.d.). *Events that trigger workflows*. GitHub Docs. https://docs.github.com/actions/using-workflows/events-that-trigger-workflows
