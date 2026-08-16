# Scheduler independent exact-head approval gate

## Decision record

The organization merge scheduler must fail closed unless GitHub's current pull-request review policy is satisfied **and** an independent reviewer has submitted a formal `APPROVED` review bound to the exact live pull-request head. Exact-head OpenCode approval remains necessary where configured, but it is not sufficient merge authority.

This control repairs the governance defect tracked in #771: an automation credential that can merge or enable auto-merge must not infer separation of duties from an advisory model review, a predecessor-head approval, the pull-request author's own identity, a status context, or absent review metadata.

## Threat and failure model

A repository or organization ruleset can permit selected users, roles, teams, or GitHub Apps to bypass rules. Consequently, relying on GitHub to reject an unsafe scheduler mutation is insufficient when the scheduler credential could ever be granted bypass capability. The scheduler therefore applies an application-level gate before either direct merge or native auto-merge entrypoints.

The fail-closed decision requires all of the following review evidence on the current live pull request:

1. `reviewDecision` is exactly `APPROVED`;
2. the authoritative pull-request evidence includes a non-empty author login;
3. an independent review has state `APPROVED`;
4. that formal review is bound to the exact current head SHA under the scheduler's existing review/head-evidence rules;
5. the reviewer identity is non-empty, differs from the pull-request author, and is not the OpenCode automated reviewer; and
6. every pre-existing scheduler gate for current-head OpenCode evidence, Strix/security evidence, unresolved threads, checks, mergeability, head freshness, branch update safety, and expected-head merge semantics remains in force.

`REVIEW_REQUIRED`, missing review state, stale/dismissed/comment-only reviews, unknown author identity, author self-review, OpenCode-only review, predecessor-head approval, status-only evidence, and synthetic merge evidence never satisfy this gate.

## Implementation boundary

`scripts/ci/pr_review_merge_scheduler.py` is the auditable approval-policy facade. The mature scheduler engine remains in `scripts/ci/_pr_review_merge_scheduler_core.py`; the facade adds the smallest merge-authorization boundary without duplicating or weakening the established check, cleanup, branch-update, review-dispatch, conflict, and expected-head machinery.

The authoritative GraphQL pull-request envelope is extended with `author { login }`. The REST fallback records the same author identity from GitHub's pull-request user field. If that identity is absent, independence cannot be established and the result is `WAIT`.

When the independent-approval gate is unsatisfied, the facade invokes the existing scheduler engine with merge entrypoints mechanically disabled. This preserves productive non-merge maintenance while preventing `merge_pr` or auto-merge enablement. If native auto-merge is already configured on an otherwise clean PR that no longer satisfies the gate, the scheduler disables it rather than allowing stale approval state to remain armed.

The split is permanent source structure, not a one-shot repair workflow or branch writer. The focused quality workflow tracks and compiles both the policy facade and the core module so edits to either surface regenerate exact-head evidence.

## Test-first evidence

The permanent regression suite covers the following cases:

- GitHub `REVIEW_REQUIRED` blocks despite exact-head OpenCode and independent approvals;
- GitHub `APPROVED` without an exact-head independent approval blocks;
- predecessor-head independent approval blocks;
- pull-request-author self-approval blocks;
- missing pull-request author identity blocks;
- missing reviewer identity blocks;
- non-`APPROVED` independent review blocks;
- exact-head OpenCode plus exact-head non-author independent approval plus GitHub `APPROVED` preserves the normal merge path; and
- the permanent quality workflow tracks the scheduler core as well as the facade.

The focused exact-head workflow also verifies literal pull-request-head checkout with persisted credentials disabled, hash-verified test dependencies, Python compilation, and a clean worktree. Broader repository, security, supply-chain, automated-review, independent-review, and branch-protection evidence remains independently required before readiness or merge.

## Relationship to GitHub rules

GitHub documents that protected branches and rulesets can require approving reviews and passing status checks. GitHub also documents that pull-request authors cannot approve their own pull requests; that stale approvals can be dismissed after code changes; and that rulesets can require approval from someone other than the most recent pusher. Rulesets may additionally define bypass actors. The scheduler's application-level gate intentionally complements these server-side controls rather than replacing or weakening them.

A GitHub `APPROVED` aggregate decision is therefore treated as necessary repository-policy evidence, while the exact-head independent-review check supplies an explicit automation-level separation-of-duties invariant. Neither condition substitutes for required checks, security gates, conversation resolution, or the repository's actual branch/ruleset evaluation.

## Operations and rollback

Before every scheduler mutation, refetch the live pull-request head/base and the relevant target state. If the head or base changes, discard predecessor evidence and re-evaluate. Merge remains expected-head guarded.

If this repair causes an operational regression, rollback means reverting the reviewed scheduler change and restoring the last protected-main implementation while keeping merges disabled until an equivalent independent-approval control is available. Rollback must never be implemented by lowering required-review counts, granting routine bypass, synthesizing review state, accepting stale approvals, or re-enabling direct merge without an equivalent fail-closed authorization check.

## Non-claims

This control does not prove that an approving reviewer is organizationally independent merely because GitHub identities differ. Repository permission, team membership, last-pusher rules, CODEOWNERS requirements, and organization policy remain authoritative. It also does not make an automated review a substitute for a human approval when repository policy requires a counted human reviewer.

## References (APA 7th)

GitHub. (n.d.). *About protected branches*. GitHub Docs. Retrieved August 8, 2026, from https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches

GitHub. (n.d.). *Approving a pull request with required reviews*. GitHub Docs. Retrieved August 8, 2026, from https://docs.github.com/en/pull-requests/how-tos/review-pull-requests/approving-a-pull-request-with-required-reviews

GitHub. (n.d.). *Available rules for rulesets*. GitHub Docs. Retrieved August 8, 2026, from https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets

GitHub. (n.d.). *About rulesets*. GitHub Docs. Retrieved August 8, 2026, from https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets
