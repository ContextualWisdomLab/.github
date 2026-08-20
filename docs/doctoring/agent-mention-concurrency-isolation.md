# Review-agent mention routing reliability

Review date: **2026-08-19**

## Incident

Trusted `@opencode-agent` comments could remain unacknowledged and fail to start the existing OpenCode review path. Two independent control-plane defects produced the same operator-visible symptom before model execution.

1. The OpenCode `repository_dispatch.client_payload` exceeded GitHub's ten-property limit, so GitHub rejected the request with HTTP 422 before the trusted wrapper started.
2. Interactive `issue_comment` routing and the five-minute organization sweep shared one workflow-level concurrency group. Under the default single-pending contract, a newly queued sweep could replace a pending interactive mention before exact-head resolution, durable claim creation, dispatch, or acknowledgement.

Neither defect is evidence that the requesting maintainer, model, repository allowlist, or final review result is invalid.

## Test-first repair

The permanent regression contracts were committed before their corresponding production changes.

- `tests/test_agent_mention_dispatch_payload_limit.py` requires both dispatch hops to stay at or below ten top-level payload properties and requires the router to reject an oversized payload before GitHub does.
- `tests/test_agent_mention_queue_isolation.py` requires the interactive route to have no replacing concurrency group while the scheduled sweep remains independently single-flight.

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

The wrapper-to-scheduler payload carries exactly ten fields, including the three values that override unsafe scheduler defaults. The wrapper therefore remains review-only and cannot merge or update a branch.

### Non-replacing interactive routing

The event-driven local route has no concurrency group, so each eligible
`issue_comment` event receives its own run. The scheduled sweep remains
single-flight and cannot cancel an interactive run:

```yaml
route-local-agent-mention:
  runs-on: ubuntu-24.04

sweep-organization-agent-mentions:
  concurrency:
    group: review-agent-mention-router-sweep-${{ github.repository }}
    cancel-in-progress: false
```

GitHub's supported concurrency contract permits at most one running and one
pending member per group, and a newly queued member replaces an older pending
member. The unsupported `queue: max` key cannot provide durability. Omitting a
local concurrency group is therefore the smallest supported boundary that does
not discard a trusted mention before its durable invocation claim exists.
Scheduled sweeps still coalesce in their separate group and cannot displace
interactive work.

Concurrency is not the idempotency authority. Duplicate forwarding remains governed by the complete canonical invocation key, exact-key downstream concurrency, and the immutable exact-name Actions artifact ledger.

## Preserved boundaries

- No model provider, reviewer identity, repository allowlist, token name, credential scope, or branch-protection rule changes.
- `COPILOT_GITHUB_TOKEN` remains unused.
- Workflow-default permissions remain read-only; the local router has read-only Actions access and keeps only the content/comment writes required for dispatch and acknowledgement.
- Only trusted non-bot `OWNER`, `MEMBER`, or `COLLABORATOR` comments on open pull requests are eligible.
- Pull request number, exact head and base SHAs, base branch, source comment, requested agent, and requesting actor remain bound to the invocation key.
- Mention routing remains unable to approve, merge, update branches, publish, or release.

## Operational acceptance

After protected integration:

1. submit a fresh trusted `@opencode-agent` comment on an open pull request;
2. require the hidden receipt marker, acknowledgement comment, or durable exact-name artifact for the source comment;
3. require the trusted OpenCode wrapper and review-only scheduler dispatch to start for the same repository, pull request, and exact head;
4. verify that a scheduled sweep cannot cancel or replace the interactive route;
5. distinguish downstream provider or review failure from routing failure rather than treating every missing verdict as the same incident.

A receipt proves routing and durable claim processing. It is not an approval and never substitutes for exact-head checks or branch protection.

## Rollback prohibition

Do not restore either defective boundary:

- do not increase the first- or second-hop payload beyond GitHub's limit;
- do not move local and scheduled work back into one workflow-level concurrency group;
- do not add a local concurrency group whose default single-pending contract can replace an eligible interactive request before the durable claim exists.

A safe emergency degradation may suspend the scheduled sweep while retaining the isolated interactive route.

## References

GitHub. (n.d.). *Control the concurrency of workflows and jobs*. GitHub Docs. Retrieved August 19, 2026, from https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency

GitHub. (n.d.). *REST API endpoints for repositories: Create a repository dispatch event*. GitHub Docs. Retrieved August 19, 2026, from https://docs.github.com/en/rest/repos/repos#create-a-repository-dispatch-event

GitHub. (n.d.). *Store and share data with workflow artifacts*. GitHub Docs. Retrieved August 19, 2026, from https://docs.github.com/en/actions/tutorials/store-and-share-data
