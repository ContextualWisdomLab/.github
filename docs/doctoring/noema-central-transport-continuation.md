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
A consumer continuation requires the existing `PR_REVIEW_MERGE_TOKEN` to read the
product PR and create a central repository dispatch; absence or insufficient
permission fails explicitly. This change does not assert that every consumer has
that credential. Native trusted-main runner restrictions, independent review,
publication fencing and the existing post-failure retry bound remain unchanged.
No model inference deadline is added.

## Evidence

The shell regression fails on the baseline because the dispatch endpoint is the
consumer repository. It executes the actual workflow step against a fake API,
checks the central endpoint and preserved payload, permits central-origin retry,
rejects unrelated origin and fork or changed-base evidence, and proves a rejected
POST cannot report successful continuation. The unchanged reviewer contracts
are run alongside this regression. Live provider recovery and approval still
require successful current-head hosted execution.
