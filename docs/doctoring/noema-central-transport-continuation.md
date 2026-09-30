# Noema central transport continuation

## Failure

The 429-capacity continuation sent repository dispatch to the product repository.
Organization-required workflows do not supply a local repository-dispatch handler
there. A central review of another repository also failed its same-repository
origin guard, even though the review itself had admitted that target.

## Repair

Send the existing `noema-review` event to the central `.github` handler. Preserve
its target repository, PR, exact head and retry count. Permit only the central
origin or the target repository's own required workflow. Re-fetch an open PR and
require matching head, base, base repository and head repository before sending.
Fork, stale, closed and unrelated-origin continuations retire or fail closed.

The central handler can dispatch with its repository-scoped GitHub token.
A consumer required workflow cannot receive the central repository's
`PR_REVIEW_MERGE_TOKEN`; its `github.token` is scoped to the consumer and gets
HTTP 403 when it posts to `ContextualWisdomLab/.github/dispatches`. The consumer
continuation therefore exchanges the job OIDC token for the existing
organization GitHub App installation token and uses that token only for the
central dispatch POST. Missing OIDC or an empty exchange response fails closed
before any cross-repository POST. Native trusted-main runner restrictions,
independent review, publication fencing and the existing post-failure retry
bound remain unchanged. No model inference deadline is added.

## Evidence

The shell regression fails on the baseline because the dispatch endpoint is the
consumer repository. It executes the actual workflow step against a fake API,
checks the central endpoint and preserved payload, permits central-origin retry,
rejects unrelated origin and fork or changed-base evidence, and proves a rejected
POST cannot report successful continuation. The unchanged reviewer contracts
are run alongside this regression. Live provider recovery and approval still
require successful current-head hosted execution.

## 2026-09-30 production recurrence and owner repair

`ContextualWisdomLab/contextual-orchestrator#1349` reproduced the unresolved
consumer-token path at exact head
`832291c11da301e919d9dc20fda99f0847142dd8`. Required Noema Review job
`109737701886` exhausted the `orchestrator/free` gateway with HTTP 429 after
1,318.6 seconds and correctly emitted a bounded continuation delay. The
continuation job `109778469161` then waited 93 seconds and failed its POST with
`Resource not accessible by integration (HTTP 403)`. This separates the
upstream capacity outcome from the central-control defect: capacity is external,
but losing the authorized same-head retry is owned here.

Issue #2509 and PR #2510 are the canonical owner lane. The regression executes
both the Noema and Strix continuation shells in a consumer-repository context,
proves the dispatch uses the exchanged organization App token rather than the
consumer token, and proves an empty exchange produces no POST. The repair stays
Proposed until protected-main integration and a consumer hosted run demonstrate
an accepted central dispatch for the same live PR/head/base identity.
