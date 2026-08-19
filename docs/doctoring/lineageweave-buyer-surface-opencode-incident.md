# LineageWeave buyer-surface OpenCode incident

검토 기준일: **2026-08-20**

## Scope

The affected LineageWeave buyer surface is the stacked dependency chain
**#258 → #260 → #261 → #262 → #263 → #264**. A trusted
`@opencode-agent` request on #258 produced neither a visible receipt nor a
formal exact-head review.

## First causal boundaries

The central default-branch mention workflow used a concurrency property that is
not part of the GitHub Actions workflow schema. Because sibling repository
comments are discovered by the scheduled organization sweep, that invalid
workflow prevented the sweep from being treated as operational.

A second failure happened after dispatch. The router attempted a cosmetic
reaction before publishing the durable acknowledgement. A target-repository
permission failure therefore terminated the source run even though dispatch had
already succeeded. The exact invocation ledger blocked duplicate dispatch, but
the previous early return also blocked a later sweep from recreating the missing
receipt.

## Repair contract

The central repair must:

- use valid non-cancelling workflow concurrency;
- bound repository discovery while preserving deterministic output and
  repository-local failure isolation;
- publish the acknowledgement even when the cosmetic reaction is forbidden;
- recreate a missing acknowledgement for an existing exact invocation without
  dispatching again;
- keep acknowledgement publication failure visible for later recovery; and
- retain exact repository, pull request, head, base, actor, source comment, and
  review-only behavior binding.

The dedicated LineageWeave hourly caller complements the mention path. It gives
all current heads in the stack a bounded repair heartbeat while keeping the
shared scheduler product-neutral.

## Stack order

A descendant is reviewed against its declared parent head. When a parent moves,
its child is stale until the base is updated and exact-head checks and formal
reviews are regenerated. Evidence from an ancestor, predecessor head, or sibling
cannot satisfy a descendant gate.

## Operational acceptance

Source tests do not close this incident. After the central repair and the
LineageWeave caller reach protected `main`:

1. post one fresh trusted mention on the current head of #258;
2. observe the sibling-repository sweep discover it;
3. observe the exact-head acknowledgement receipt;
4. observe no duplicate dispatch on the next sweep;
5. observe a formal OpenCode review or explicit fail-visible evidence; and
6. process #260 through #264 in dependency order after every parent-head change.

Independent approval, required checks, and resolution of valid review findings
remain merge requirements.

## APA 7th references

GitHub, Inc. (n.d.). *Events that trigger workflows*. GitHub Docs. Retrieved
August 20, 2026, from
https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows

GitHub, Inc. (n.d.). *Workflow syntax for GitHub Actions*. GitHub Docs.
Retrieved August 20, 2026, from
https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax
