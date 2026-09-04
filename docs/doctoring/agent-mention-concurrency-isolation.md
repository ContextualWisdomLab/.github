# Review-agent mention routing reliability

Review date: **2026-08-22**

## Incident

Trusted `@opencode-agent` comments could remain unacknowledged and fail to start the existing OpenCode review path. Two independent control-plane defects produced the same operator-visible symptom before model execution.

1. The OpenCode `repository_dispatch.client_payload` exceeded GitHub's ten-property limit, so GitHub rejected the request with HTTP 422 before the trusted wrapper started.
2. Interactive `issue_comment` routing and the five-minute organization sweep shared one workflow-level concurrency group. Under the default single-pending contract, a newly queued sweep could replace a pending interactive mention before exact-head resolution, durable claim creation, dispatch, or acknowledgement.
3. The organization sweep submitted pull-list requests to four workers but consumed their futures in repository-list order. A slow earlier repository could therefore hide a completed later repository until the sweep approached its 15-minute job limit or its bounded dispatch frontier.
4. The OpenCode wrapper omitted `trigger_reviews` from its second-hop payload. The scheduler evaluated the missing repository-dispatch field as false, so a successfully routed and durably claimed mention entered queue maintenance without dispatching the requested review.

None of these defects is evidence that the requesting maintainer, model, repository allowlist, or final review result is invalid.

## Test-first repair

The permanent regression contracts were committed before their corresponding production changes.

- `tests/test_agent_mention_dispatch_payload_limit.py` requires both dispatch hops to stay at or below ten top-level payload properties and requires the router to reject an oversized payload before GitHub does.
- `tests/test_agent_mention_queue_isolation.py` requires the interactive route and scheduled sweep to use different job-level concurrency groups, with `queue: max` on the interactive route and no cancellation of in-progress interactive work.
- `tests/test_agent_mention_timeout_bounds.py` requires a completed later repository to yield before a deliberately blocked earlier repository, while retaining the fixed four-worker ceiling and bounded generator shutdown.

## Decision

### Bounded dispatch envelope

The router-to-wrapper OpenCode payload carries nine identity and provenance fields. Review-only behavior remains bound into the canonical invocation hash and is reconstructed by the trusted wrapper:

```text
trigger_reviews=true
review_dispatch_limit=1
enable_auto_merge=false
update_branches=false
merge_mode=disabled
```

The wrapper-to-scheduler payload carries exactly ten fields, including the three values that override unsafe scheduler defaults and explicit `trigger_reviews=true`. Source-comment identity remains bound in the validated invocation hash and immutable ledger claim but is not duplicated into the scheduler payload because the scheduler does not consume it. The wrapper therefore dispatches the requested review while remaining unable to merge or update a branch.

### Isolated concurrency queues

Concurrency is scoped to each job rather than the whole workflow:

```yaml
route-local-agent-mention:
  concurrency:
    group: review-agent-mention-router-local-${{ github.repository }}
    queue: max

sweep-organization-agent-mentions:
  concurrency:
    group: review-agent-mention-router-sweep-${{ github.repository }}
    cancel-in-progress: false
```

GitHub documents that `queue: max` permits up to 100 pending jobs or workflow runs in one concurrency group and cannot be combined with `cancel-in-progress: true`. The interactive queue therefore retains bounded pending requests instead of replacing the previous pending request. Scheduled sweeps retain coalescing behavior in a separate group and cannot displace interactive work.

Concurrency is not the idempotency authority. Duplicate forwarding remains governed by the complete canonical invocation key, exact-key downstream concurrency, and the immutable exact-name Actions artifact ledger.

### Fair repository completion

The sweep now consumes the existing four-worker repository futures through
`concurrent.futures.as_completed`. Repository rotation still changes the
starting position every five minutes, and the four-worker ceiling remains in
place. The only changed ordering is the local observation order: a repository
whose pull-list request completes first can expose its recent PR comments
before a slower sibling. Dispatch remains sequential through the existing
ledger and exact-head validation boundaries.

## Preserved boundaries

- No model provider, reviewer identity, repository allowlist, token name, credential scope, or branch-protection rule changes.
- `COPILOT_GITHUB_TOKEN` remains unused.
- Workflow-default permissions remain read-only; existing bounded jobs keep only their required writes.
- Only trusted non-bot `OWNER`, `MEMBER`, or `COLLABORATOR` comments on open pull requests are eligible.
- Pull request number, exact head and base SHAs, base branch, source comment, requested agent, and requesting actor remain bound to the invocation key.
- Mention routing remains unable to approve, merge, update branches, publish, or release.

## Operational acceptance

After protected integration:

1. submit a fresh trusted `@opencode-agent` comment on an open pull request;
2. require the hidden receipt marker, acknowledgement comment, or durable exact-name artifact for the source comment;
3. require the trusted OpenCode wrapper and review-only scheduler dispatch to start for the same repository, pull request, and exact head, with scheduler `TRIGGER_REVIEWS=true` and an actual review dispatch;
4. verify that a scheduled sweep cannot cancel or replace the interactive route;
5. distinguish downstream provider or review failure from routing failure rather than treating every missing verdict as the same incident.
6. verify the slow-first/fast-later repository regression remains green so a
   delayed repository cannot starve a completed sibling's comment inventory.

A receipt proves routing and durable claim processing. It is not an approval and never substitutes for exact-head checks or branch protection.

## Rollback prohibition

Do not restore either defective boundary:

- do not increase the first- or second-hop payload beyond GitHub's limit;
- do not move local and scheduled work back into one workflow-level concurrency group;
- do not replace `queue: max` with the default single-pending interactive queue unless another independently reviewed durable queue preserves every eligible request.
- do not remove the four-worker ceiling or replace completion-order observation
  with repository-list-order waiting without a new bounded fairness contract.

A safe emergency degradation may suspend the scheduled sweep while retaining the isolated interactive route.

## References

GitHub. (n.d.). *Control the concurrency of workflows and jobs*. GitHub Docs. Retrieved August 19, 2026, from https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency

GitHub. (n.d.). *REST API endpoints for repositories: Create a repository dispatch event*. GitHub Docs. Retrieved August 19, 2026, from https://docs.github.com/en/rest/repos/repos#create-a-repository-dispatch-event

GitHub. (n.d.). *Store and share data with workflow artifacts*. GitHub Docs. Retrieved August 19, 2026, from https://docs.github.com/en/actions/tutorials/store-and-share-data

Python Software Foundation. (n.d.). *concurrent.futures — Launching parallel tasks*. Python documentation. Retrieved August 20, 2026, from https://docs.python.org/3/library/concurrent.futures.html#concurrent.futures.as_completed
