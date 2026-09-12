# Scheduler central run read authority

## Problem

The stale-review cancellation path introduced by `ContextualWisdomLab/.github#1669` revalidates an active workflow run immediately before force-cancellation. Direct pull-request runs live in the target repository, but organization-wide OpenCode and Strix `repository_dispatch` runs live in the configured central workflow repository. Reading both through the target-repository credential is therefore not a valid authority boundary: a target-only credential can be unable to read the central Actions run, causing fail-closed preservation of a genuinely stale central run and preventing a replacement current-head review from dispatching.

## Constraint and decision

The protected scheduler already separates target-repository reads (`gh_api_json`) from central-repository Actions reads (`gh_api_json_via_dispatch_token`, backed by `SCHEDULER_DISPATCH_TOKEN`). `_fresh_active_run_for_cancellation()` therefore selects the central reader only when `run_repo` exactly equals the validated configured `SCHEDULER_REQUIRED_WORKFLOW_REPOSITORY`; all other repositories retain the target reader. When no central repository is configured, the helper does not invent elevated authority and continues through the target reader. Existing fail-closed handling remains unchanged: malformed, inaccessible, or non-active evidence preserves the candidate instead of authorizing cancellation.

## Failure scenarios and evidence

1. A stale central `repository_dispatch` run belongs to `ContextualWisdomLab/.github` while the inspected PR belongs to `ContextualWisdomLab/fast-mlsirm`. Revalidation must use central dispatch authority, otherwise a target-only token can strand the stale run and block replacement review dispatch.
2. A direct Actions run belongs to the target repository. Revalidation must continue to use target read authority; central dispatch credentials are not widened to target evidence.
3. Central ownership is absent or malformed. The scheduler does not guess a central repository or silently broaden credentials.

`tests/test_scheduler_central_run_read_authority.py` binds these cases to the production helper. The repair is control-plane credential routing only: it does not change model selection, review semantics, cancellation criteria, merge authority, required checks, or leaf repository source.

## Rollback and follow-up

Rollback is the single helper-level reader selection plus this regression contract. After protected-main integration, re-evaluate affected leaf PRs for fresh current-head OpenCode/Strix evidence and confirm stale central runs no longer block replacement dispatch. Do not transfer predecessor review/check evidence.
