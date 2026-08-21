# Contextual Orchestrator Hourly Review-Repair Caller

## Customer action

Keep `ContextualWisdomLab/contextual-orchestrator` on the protected `main`
branch, then confirm the central autofix gateway contract in
`ContextualWisdomLab/.github#1168` is merged before enabling this scheduled
caller. After the caller runs, inspect the target PR's exact-head review,
Checks, and independent approval; merge only through the protected normal path.

## Runtime boundary

The workflow runs at minute 17 of every hour and calls the central
`pr-review-fix-scheduler.yml` reusable workflow. It scans at most 50 open PRs,
dispatches one bounded repair, permits unresolved conflict repair, and waits
two hours before retrying the same head. Non-cancelling concurrency preserves a
long-running exact-head OpenCode, Noema, or security operation.

The caller grants read-only contents access and OIDC token exchange only. It
forwards the established `PR_REVIEW_MERGE_TOKEN` and
`OPENCODE_APPROVE_TOKEN` paths explicitly; it does not inherit all secrets and
does not receive `NVIDIA_NIM_API_KEY` or `COPILOT_GITHUB_TOKEN`. The central
target allowlist must include `ContextualWisdomLab/contextual-orchestrator` in
`OPENCODE_REPOSITORY_DISPATCH_TARGETS`.

## Gateway dependency and evidence

The reusable scheduler dispatches the default-branch central autofix workflow.
Merge `ContextualWisdomLab/.github#1168` first so that this caller's write path
uses the contextual-orchestrator gateway's automatic model discovery and
bounded OpenCode tool loop. The worker must keep provider credentials in the
gateway KV boundary and must fail closed when gateway configuration is absent.

Every dispatched repair is diagnostic until the target PR's live head is
revalidated. A changed head invalidates earlier review and Checks evidence.
Queued, cancelled, unavailable, or synthetic evidence never authorizes a
merge. A customer should open the target PR, resolve actionable review threads,
wait for terminal required Checks, obtain an independent review and non-author approval,
and then use the repository's protected merge control.

## Verification

Run the caller contract test and `actionlint` against the exact commit before
changing the target allowlist or credential bindings:

```text
python3 -m pytest -q tests/test_contextual_orchestrator_hourly_review_caller.py
actionlint .github/workflows/contextual-orchestrator-hourly-review-repair.yml
```

## APA 7th references

GitHub. (n.d.). *Events that trigger workflows*. Retrieved August 21, 2026,
from https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows

GitHub. (n.d.). *Reuse workflows*. Retrieved August 21, 2026, from
https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows

OpenCode. (n.d.). *Permissions*. Retrieved August 21, 2026, from
https://opencode.ai/docs/permissions
