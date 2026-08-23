# ScopeWeave PR #506 merge-triggered calendar stack audit

Status: proposed organization control-plane automation.

Cross-repository targets:

- prerequisite: `ContextualWisdomLab/scopeweave#506`;
- calendar credential domain: `ContextualWisdomLab/scopeweave#539`;
- calendar SQLite persistence: `ContextualWisdomLab/scopeweave#541`.

## Purpose

The two calendar-subscription pull requests are stacked on the access-grant
prerequisite rather than directly on protected `develop`. A calendar review
must not be promoted from stale pull-request prose, predecessor checks, or the
mere closing of the prerequisite. The audit therefore observes exactly one
state transition: GitHub reports `pull_request_target.closed` for ScopeWeave
PR #506 and the event's `pull_request.merged` value is the boolean `true`.

The workflow-level condition is only the first gate. The trusted central
script re-fetches PR #506 through the GitHub API and requires the live object
to remain closed and merged with a valid merge commit. It then re-fetches
protected `develop` and proves that the live merge commit is an ancestor of
that protected head. A stale, forged, manually dispatched, closed-unmerged, or
branch-propagation-incomplete event cannot establish prerequisite authority.

## Trusted execution boundary

The entrypoint remains the organization required workflow
`.github/workflows/opencode-review.yml`. The job:

1. matches the exact repository, event name, action, PR number, and merged
   boolean;
2. resolves the immutable required-workflow SHA and rejects an unexpected
   workflow source;
3. checks out only `ContextualWisdomLab/.github` at that SHA;
4. never checks out or executes ScopeWeave pull-request content;
5. grants only `contents: read`, `checks: read`, `pull-requests: read`, and
   `issues: write`; and
6. uses `issues: write` solely to create or update marker-scoped PR comments.

The script accepts API paths only under
`/repos/ContextualWisdomLab/scopeweave` plus the fixed GraphQL endpoint used to
page review threads. REST and GraphQL responses, the event file, request
payloads, report size, page count, and request timeout are bounded. API and
transport failures fail the job rather than being represented as passing
evidence.

## Live evidence collected

After the prerequisite proof, the script re-reads rather than infers:

- protected `develop` head and its required status contexts;
- #539 and #541 current head/base refs and SHAs;
- open/closed, merged, Draft, mergeability, and mergeability-state fields;
- all exact-head Check Runs and legacy commit statuses, with latest-record
  deduplication and literal `success` required for each protected context;
- all formal reviews, bound to the current head SHA;
- independent current-head approvals separately from author or bot approvals;
- current-head change requests and stale reviewer evidence; and
- every review thread through paginated GraphQL, including its resolved state.

Pull-request bodies are deliberately excluded from authority because they can
contain superseded SHAs, old workflow run identifiers, or prior review claims.

## Restack classification

The audit evaluates four live comparisons:

1. #506 merge commit → protected `develop`;
2. #506 head → #539 head;
3. protected `develop` → #539 head; and
4. #539 head → #541 head.

For #539:

- `restack` means its head does not contain the live protected head and its
  bounded semantic diff must be reconciled onto `develop`;
- `retarget` means it already contains protected `develop`, but its PR base
  still points to the prerequisite branch; and
- `none` means both ancestry and base are current.

For #541:

- `restack-now` means the child no longer targets or contains #539's exact
  current head;
- `restack-after-539` means the child is correctly stacked now, but #539 must
  first move; and
- `none` means the child remains exact after the parent assessment.

The review-ready order is always #539, then #541. Each PR must obtain fresh
exact-head checks and a qualifying independent current-head review after its
final reconciliation. Draft removal is a maintainer decision after those
conditions are satisfied; this audit does not remove Draft status.

## Publication and mutation boundary

The same combined live report is published to #539 and #541 with target-bound
markers:

```text
<!-- scopeweave-pr506-calendar-stack:v1 target=539 -->
<!-- scopeweave-pr506-calendar-stack:v1 target=541 -->
```

Only a comment authored by `github-actions[bot]` whose body starts with the
exact target marker may be updated. Human comments and the sibling PR's marker
are never modified. Duplicate bot-owned markers fail closed. Repeated delivery
is idempotent: an unchanged report causes no API mutation.

The automation does not push, rebase, merge, retarget, change Draft state,
submit or dismiss reviews, resolve threads, rerun checks, or enable auto-merge.
It reports the live prerequisite, evidence, reconciliation need, and ordered
next action so the normal guarded maintainer path can continue.

## Verification

The focused contract suite covers the merged-only event gate, live merge
revalidation, protected-branch ancestry, restack classification, exact-head
check/review/thread summaries, marker ownership and idempotency, bounded REST
and GraphQL clients, and CLI event binding. The module is held to 100% statement
and branch coverage and complete module/class/function docstrings under the
organization control-plane quality policy.
