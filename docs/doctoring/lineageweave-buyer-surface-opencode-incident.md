# LineageWeave buyer-surface OpenCode incident

검토 기준일: **2026-08-20**

## Scope

The affected LineageWeave buyer surface is the stacked dependency chain
**#258 → #260 → #261 → #262 → #263 → #264**. A trusted
`@opencode-agent` request on #258 produced neither a visible receipt nor a
formal exact-head review.

## First causal boundaries

The durable repository dispatch had already succeeded. The router then tried to
add a cosmetic `eyes` reaction before publishing the acknowledgement comment.
The target repository returned HTTP 403 for that reaction, which terminated the
source run before the receipt was written. The exact invocation ledger correctly
prevented duplicate dispatch, but the previous all-agents-existing early return
also prevented a later organization sweep from healing the missing receipt.

The scheduled sweep had a separate availability weakness: `gh api` subprocesses
had no finite timeout, so an already-running repository query could make
executor shutdown wait indefinitely after the dispatch frontier was reached.
That weakness did not explain the already-created invocation without a receipt,
but it could prevent later LineageWeave requests from being discovered and
recovered predictably.

`concurrency.queue: max` is not an invalid workflow property. GitHub introduced
larger concurrency queues on May 7, 2026; `queue: max` preserves up to 100
pending runs and is compatible with an omitted or false `cancel-in-progress`.
The shared local-mention queue therefore retains `queue: max`, while exact-key
downstream wrappers keep their invocation-scoped concurrency contract.

## Repair contract

The central repair must:

- retain the valid `queue: max` local concurrency contract;
- bind every `gh api` subprocess to a finite timeout;
- bound repository discovery while preserving deterministic output, fair
  rotation, and repository-local failure isolation;
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

GitHub, Inc. (2026, May 7). *GitHub Actions concurrency groups now allow larger
queues*. GitHub Changelog.
https://github.blog/changelog/2026-05-07-github-actions-concurrency-groups-now-allow-larger-queues/

GitHub, Inc. (n.d.-a). *Events that trigger workflows*. GitHub Docs. Retrieved
August 20, 2026, from
https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows

GitHub, Inc. (n.d.-b). *Workflow syntax for GitHub Actions*. GitHub Docs.
Retrieved August 20, 2026, from
https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax
