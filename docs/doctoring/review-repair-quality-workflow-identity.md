# Review-repair quality workflow identity RCA

## Status

Recorded 2026-09-01 against protected `ContextualWisdomLab/.github` `main@b4f7b082536d2be8dceab0a40a484161b50e5acd` and repair PR #1573.

## Incident

The central workflow `.github/workflows/hourly-nvidia-nim-review-repair.yml` was named **Hourly NVIDIA NIM Review Repair**, but the executable source contradicted both halves of that identity:

- it had no `schedule` trigger and therefore did not own an hourly writer cadence;
- it had read-only `contents: read` permission and executed only repository contract tests, coverage, docstring checks, `compileall`, and `git diff --check`;
- it did not invoke OpenCode or any model provider;
- the write-capable repair boundary already lived in `.github/workflows/pr-review-autofix.yml` and routed OpenCode through the vendored contextual-orchestrator sidecar with the virtual model `contextual-orchestrator/orchestrator/free`.

The stale identity survived the earlier direct-NIM-to-gateway migration because executable worker routing and the focused quality gate evolved independently. Draft PR #1527 corrected prose only and explicitly left workflow behavior and identity unchanged, so it could not close this control-plane naming/responsibility gap.

## Root cause

The repository conflated three separate responsibilities under one historical label:

1. **Cadence ownership** — thin product-specific `*-hourly-review-repair.yml` callers own schedules.
2. **Repair execution** — `pr-review-fix-scheduler.yml` selects bounded work and `pr-review-autofix.yml` owns the write-capable exact-head repair worker.
3. **Contract verification** — the former `hourly-nvidia-nim-review-repair.yml` is a PR/push-only read-only quality gate.

When direct NVIDIA NIM execution was retired in favor of ADR-0003's contextual-orchestrator gateway, responsibility (2) was migrated but responsibility (3)'s filename, display name, job name, and dependent test paths were not. The result was executable metadata that suggested a scheduled direct-provider writer where none existed.

## Repair

PR #1573 renames the quality gate to `.github/workflows/contextual-orchestrator-review-repair-quality.yml` with display name **Contextual Orchestrator Review Repair Quality CI**. It remains PR/push-only and read-only. No second scheduler is added.

All executable test references move to the new path. The underlying writer remains unchanged:

```text
hourly product caller
  -> pr-review-fix-scheduler.yml
  -> repository_dispatch: pr-review-autofix
  -> pr-review-autofix.yml
  -> contextual-orchestrator sidecar
  -> contextual-orchestrator/orchestrator/free
```

The sidecar continues to register the existing five provider credentials (`BYTEZ_API_KEY`, `NVIDIA_NIM_API_KEY`, `NVIDIA_NIM_API_KEY_SUB`, `OPENROUTER_API_KEY`, `OPENAI_API_KEY`) into its process-local provider registry. Provider keys are not promoted to workflow identity and no direct-provider fallback is introduced.

## TDD evidence

The first PR commit, `6279b0c8fe7f41f2ec61be728da41d9c2c599e84`, changed `tests/test_hourly_scheduler_runtime_budget.py` before the implementation. It required the new quality-workflow path and rejected the legacy path/name. On that exact tree the required new file did not exist, so the contract was deterministically RED; GitHub materialized predecessor run `33489785044` from the legacy workflow while the fleet was queued.

The GREEN implementation then created the new workflow, deleted the legacy workflow, and migrated every executable `QUALITY_WORKFLOW`/contract reference. Exact-head hosted run `33490614440` materialized under the new workflow name, proving GitHub recognizes the replacement workflow identity. Terminal test evidence remains authoritative only after the unchanged exact head finishes.

## Security and governance boundary

- No secret, reviewer identity, merge authority, branch-protection rule, or status is changed.
- No direct NVIDIA NIM HTTP endpoint or hard-coded provider model is introduced.
- The quality workflow remains `contents: read` only.
- The write-capable worker remains exact-head-bound and governed by its existing sealed path, revalidation, credential stripping, and protected push contracts.
- Queued, pending, skipped, cancelled, predecessor-head, or stale evidence is not treated as passing.

## Rollback

Rollback is a normal revert of the workflow rename and dependent path references only after proving that doing so does not reintroduce misleading provider/cadence ownership. Do not restore a direct-NIM execution path, add a duplicate hourly schedule, or weaken the contextual-orchestrator fail-closed contract as part of rollback.

## References

ContextualWisdomLab. (2026). *ADR-0003: Contextual-orchestrator vendored free/ZDR review routing*. `docs/adr/0003-contextual-orchestrator-vendored-free-zdr.md`.

GitHub. (n.d.). *Workflow syntax for GitHub Actions*. GitHub Docs. https://docs.github.com/actions/using-workflows/workflow-syntax-for-github-actions

GitHub. (n.d.). *Events that trigger workflows*. GitHub Docs. https://docs.github.com/actions/using-workflows/events-that-trigger-workflows
