# Scheduler independent exact-head approval

## Decision

The organization merge scheduler fails closed unless both of these statements
are true:

1. GitHub reports the pull request's aggregate `reviewDecision` as `APPROVED`.
2. A formal `APPROVED` review from a non-author, non-OpenCode identity is bound
   to the exact live head SHA.

Exact-head OpenCode approval remains a review gate, not independent merge
authority. Missing identities, author self-review, generic GitHub Actions
reviews, comment-only reviews, predecessor-head approvals, and absent aggregate
state never satisfy this control.

## Root cause and repair

The prior scheduler could call direct merge or enable native auto-merge after an
exact-head OpenCode approval without first proving repository approval state or
an independent exact-head review. A credential with bypass capability could
therefore turn advisory automation evidence into merge authority.

The repair reuses the existing scheduler and review/head matcher:

- the existing GitHub query now includes the pull-request author;
- the REST fallback records the author but remains fail closed because it does
  not provide an authoritative aggregate review decision;
- one helper filters exact-head formal approvals by author and automation
  identity, considering only each reviewer's latest approval-affecting state so
  a later change request or dismissal revokes that reviewer's earlier approval;
- both direct/automatic merge paths share the same authorization reason; and
- an already armed auto-merge request is disabled when authorization is absent.

Checks, security evidence, unresolved conversations, mergeability, branch
freshness, and expected-head merge protection remain independent blockers.
GitHub's server-side last-pusher, CODEOWNERS, required-review, and ruleset checks
remain authoritative; the scheduler does not infer those identities.

## Verification and operations

Regression cases cover missing author/reviewer identity, self-review, generic
Actions review, OpenCode review, non-approval, stale head, a later same-head
change request, missing aggregate approval, disarming existing auto-merge, and
the complete authorized direct merge path. Before lifecycle action, refetch the
live base, head, reviews, threads, checks, and rules. A head change invalidates
all predecessor evidence.

Rollback means reverting the reviewed scheduler change while keeping scheduler
merge modes disabled until an equivalent fail-closed authorization control is
available. Never roll back by lowering required-review counts or granting a
bypass.

## References

GitHub. (n.d.). *About protected branches*. GitHub Docs. Retrieved August 24,
2026, from https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches

GitHub. (n.d.). *Available rules for rulesets*. GitHub Docs. Retrieved August
24, 2026, from https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets
