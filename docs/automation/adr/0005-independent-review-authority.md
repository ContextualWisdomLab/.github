# ADR-0005: Preserve counted independent human review and stale-head semantics

Status: Accepted
Date: 2026-08-09
Decision owners: CWL governance maintainers

## Context

OpenCode, Noema, Strix, CodeRabbit, checks, statuses, and comments provide valuable automated evidence. GitHub branch policy separately requires formal reviews and may require a non-author approval, approval after the last push, thread resolution, and code-owner review. Conflating those authorities can let automation merge ahead of governance, especially if a routine token later gains bypass capability.

## Decision drivers

- Preserve human accountability and repository policy.
- Prevent author-self, bot, comment, status, dismissed, or predecessor reviews from satisfying human approval.
- Keep useful automated analysis without pretending it has another identity.
- Make approval capacity a governance prerequisite, not a reason to weaken source.

## Alternatives considered

1. **Count any `APPROVED`-looking output.** Rejected because provenance and authority differ.
2. **Let one automated reviewer replace human review.** Rejected because it violates repository policy and separation of duties.
3. **Require GitHub's aggregate policy plus an eligible formal exact-head human approval and separate automated gates.** Selected.

## Decision

Merge scheduling requires the live GitHub review decision and, where configured, at least one formal current-head `APPROVED` review from an eligible non-author human identity. Automated identities, PR author identities, dismissed reviews, comments/reactions, statuses, check conclusions, model text, synthetic approvals, and predecessor-head submissions do not qualify.

Automated OpenCode/Noema/Strix/CodeRabbit evidence remains independently required where policy specifies. Last-push and unresolved-thread requirements remain GitHub-authoritative. No agent may self-approve, impersonate, use an alternate author credential, or reduce gates to unblock itself.

## Consequences

Positive: auditable separation of duties and defense against reviewer spoofing. Negative: merge latency can depend on eligible reviewer capacity; automated clean evidence cannot finish a protected merge alone.

## Failure and recovery

If qualifying approval is absent, mark only that PR as external-governance wait, retain expected-head-safe merge intent when supported, and rotate to other work. If a review is stale or dismissed, request a new review on the current head; never rewrite source solely to retrigger a provider unless the source repair has independent value.

## Security and governance impact

The decision reduces privilege escalation and repudiation risk. Branch protection and rulesets remain final; source logic is a defense-in-depth precondition, not a bypass.

## Tests and acceptance

- author, bot, OpenCode-only, comment, status, dismissed, stale, and wrong-commit negative fixtures;
- eligible non-author current-head positive fixture;
- live aggregate `reviewDecision` and last-push/thread requirements;
- routine token with hypothetical bypass still refuses unauthorized merge; and
- current ruleset audit.

## Migration and rollback

Update positive scheduler fixtures to include real policy-authorized state. Existing automated reviewer identities and credential names remain stable. Rollback may disable automated merge while preserving human review; it may not restore automated approval substitution.

## Supersession conditions

Supersede only if organization governance formally changes the independent-review requirement through an audited ruleset decision and an equivalent separation-of-duties control is documented.
