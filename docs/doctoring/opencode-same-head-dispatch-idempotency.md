# OpenCode exact-head dispatch idempotency

## Incident

On 2026-09-30, `ContextualWisdomLab/.github#2545` remained on exact head
`9a4af5e438283a31dc05814d6bc2818caee782a3` while the required OpenCode wake
path requested review execution more than once. Central dispatch run
[`36776536447`](https://github.com/ContextualWisdomLab/.github/actions/runs/36776536447)
was already queued for that exact repository, PR, and head. A later same-head
request created run
[`36778773766`](https://github.com/ContextualWisdomLab/.github/actions/runs/36778773766),
and the receiver's PR-keyed `cancel-in-progress: true` concurrency retired the
older run. No PR head change or substantive review result justified losing its
queue position.

The required workflow correctly checked for an existing current-head formal
review, but, when that receipt was absent, posted `repository_dispatch`
unconditionally. The merge scheduler already deduplicated active same-head
OpenCode runs; this direct required-check path bypassed that guard.

## Repair contract

Before posting a new dispatch, the trusted required-check path now:

1. validates that the target PR is live, open, ready, and still on the event
   head;
2. evaluates the existing formal-review receipt predicate;
3. exchanges the existing repository-scoped OpenCode App token;
4. inventories `requested`, `waiting`, `pending`, `queued`, and `in_progress`
   runs of the canonical `opencode-review-dispatch.yml` receiver twice, so a
   state transition during the inventory remains observable;
5. validates each returned run's identity fields and matches its protected
   exact `repository#PR@head` title plus workflow path and trigger;
6. records an exact-head execution only after every accepted older-head
   cancellation reaches terminal `completed/cancelled`; and
7. re-fetches the PR immediately before dispatch, retiring the request if
   state, draft status, or head authority changed.

Run-list failures and malformed run records fail closed. The receiver has no
native concurrency group: GitHub replaces an older pending group member even
when `cancel-in-progress` is false, so native concurrency cannot preserve every
distinct callback payload. Producers deduplicate exact-head work from trusted
inventory. Before a current-head POST, the required workflow revalidates live
repository/PR/head authority and cancels only canonical older-head central
runs. A refused cancellation, failed status lookup, invalid state, terminal
non-cancelled conclusion, or accepted cancellation that remains active after
the bounded status reads fails closed without a new dispatch. Those reads do
not sleep inside the required job: the nonblocking capacity contract releases
the runner and lets a later trusted scheduler admission retry instead of
holding scarce capacity while GitHub converges. A final live-authority read
guards the POST.

The merge scheduler separately binds native concurrency to the exact PR head
and uses GitHub's bounded `queue: max` FIFO instead of lossy single-pending
replacement. `synchronize` and `closed` events run a metadata-only cleanup job
with `actions: write`; it inventories every active status, revalidates the live
PR/head immediately before each mutation, cancels only predecessor-head work
(or all final-head work on close), and accepts completion only after GitHub
reports `completed/cancelled`. Two complete status passes prevent a state
transition from escaping between filtered queries; every response reconciles
the collected row count with `total_count` and fails closed if GitHub's
filtered-search ceiling truncates the inventory. The inventory spans every
event for this workflow and then binds candidates through PR association and
head SHA; filtering the API to `pull_request_target` would strand predecessor
`pull_request_review` runs in their old exact-head group.

Producer observation and POST are not atomic, so the receiver first authorizes
the exact actor/sender pair, repository allowlist membership, and complete
payload shape before any OIDC exchange or central mutation. It then acquires a
central repository-owned lease after full live state/draft/base/head metadata
validation and before source
materialization, coverage, or model execution. The lease uses one file per
repository/PR on the dedicated `opencode-dispatch-leases` branch. GitHub's
Contents API compares the observed blob SHA during update: simultaneous cache
misses or terminal-owner takeovers can commit only one owner, while a loser
reloads the authoritative file and defers to the active exact-head run. A
different-head run may replace an owner only after a fresh live PR/head check
immediately before the compare-and-swap. Every recorded owner is validated
against its canonical workflow, event, title, and head; a rerun with the same
GitHub run ID retains its own lease. The lease file remains as auditable
bounded state and is updated, not multiplied, on later heads.

Lease ownership alone is not a durable completion receipt. Immediately after
acquiring or retaining the exact-PR lease, the receiver revalidates live
repository/PR/head authority and evaluates the formal exact-head review receipt
from the trusted default-branch helper. An existing receipt returns
`admitted=false` before source materialization, coverage, or model execution;
an unavailable or malformed receipt lookup fails closed.

The dedicated admission job alone holds `contents: write` for that lease
branch; later metadata validation and source materialization return to
`contents: read`.
The required target-repository job retains read-only Actions and contents
authority; central cancellation uses the existing repository-scoped App token.
After a formal receipt, the privileged publisher uses the repository-wide run
inventory and matches the intended PR number plus
`pull_requests[].head.sha`. It deliberately does not treat the run-level
`head_sha` as the PR head because `pull_request_target` executes trusted
default-branch workflow code. GitHub caps every filtered workflow-run search at
1,000 results, so the publisher recursively bisects the PR-lifetime `created`
range until each interval is within the API bound, then requires the sum of
every interval's `total_count` to equal the collected rows. An interval with
more than 1,000 runs in a single second fails closed. The publisher revalidates
live open/non-draft head authority immediately before every mutation and reruns
each matching failed Required OpenCode job. Therefore a duplicate
producer that lost the lease does not need its own callback payload or a
polling runner. Human review events do not enter or cancel the required
workflow. The repair does not weaken the required verdict, accept predecessor
evidence, or broaden model/provider permissions.

## Executable evidence

`tests/test_opencode_required_verdict_regression.py` executes the production
shell step. Its RED fixture proved that a queued exact-head run still produced
a second dispatch. The GREEN cases cover all five active admission states,
transition-safe two-pass inventory, malformed and unavailable inventory
fail-closure, current-head preservation, older-head non-suppression,
no-active-run dispatch, existing formal receipts, and a head movement between
initial validation and the mutation boundary. Queue-contract tests prohibit
lossy native receiver concurrency; execution fixtures prove exact older-head
cancellation, deduplication, asynchronous cancellation continuation, and
fail-closure when a cancellation is refused, remains active, returns an invalid
state, or terminates with a non-cancelled conclusion. Scheduler cleanup
fixtures also prove concurrent-head-movement preservation, transition-safe
two-pass discovery, review-event predecessor discovery,
inventory-completeness rejection, and bounded terminal cancellation
verification.
Receiver fixtures execute absent, active-owner, terminal-owner, self-rerun,
different-head takeover, and branch-initialization-race lease paths.
A two-process fixture starts simultaneous cache misses against an atomic fake
Contents API and proves exactly one `admitted=true` result. The independent
negative fixtures prove that unauthorized envelopes perform no OIDC or GitHub
API call and that closed, draft, or mismatched base/head metadata performs no
Contents mutation. Wake fixtures use a trusted-base run-level SHA distinct from
the PR head and cover multiple failures, another PR sharing the same commit,
authority movement between mutations, partial rerun failure, recursive
partitioning above 1,000 results, and detected pagination truncation. The
independent byte-for-byte reviewer pin was regenerated from the repaired
receiver as exact Git blob
`5c87c74863ef6872c1ef7136d5b330071920c09e`.

Local exact-tree verification on the stacked successor base
`86ddef63ed306d4c7d56d051d9a72570e7d358a5`:

- required-workflow, nonblocking capacity, queue, receiver, and integrity-pin
  contracts after independent-review repair: `233 passed`;
- complete Python 3.14 warnings-fatal suite: `5362 passed, 5 skipped, 40
  subtests passed`, with
  owned production `18767/18767` statements and `7648/7648` branches,
  Docstring `100%`, and zero warnings.

Protected merge still requires hosted exact-head security and quality Checks,
zero unresolved review threads, qualifying independent approval, and ordinary
branch protection.
