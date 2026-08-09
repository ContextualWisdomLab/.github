# ADR-0005: Independent review governance

Status: Accepted
Date: 2026-08-09
Owner: CWL governance maintainers

## Context

OpenCode, Noema, Strix, checks, and schedulers produce valuable evidence, but a
GitHub ruleset may require a counted approval from an eligible non-author. A
model verdict, bot comment, status, or check is not the same object and may be
self-authored, stale, or ineligible. Letting automation reinterpret its own
output as independent approval would erase separation of duties and could
bypass governance. Today, `ContextualWisdomLab/.github#772` tracks the missing
organization-level path for reliable counted independent review.

## Decision drivers

- Preserve ruleset semantics and separation of duties.
- Distinguish advice, evidence, formal review, and transaction authority.
- Prevent authors/bots from manufacturing approval for their own changes.
- Keep safe non-governed work moving while an eligible reviewer is pending.
- Give operators an explicit escalation and handoff path.

## Considered alternatives

1. Treat a successful automated check or approval phrase as approval. GitHub
   does not count it as an eligible review and the authority is wrong.
2. Let the authoring automation approve with another token. The nominal
   identity changes but independence does not.
3. Remove the review requirement for automation PRs. This weakens protected
   governance at the highest-impact repository.
4. Keep automated output advisory and require the exact eligible GitHub formal
   review object when the ruleset demands it. This is selected.

## Decision

Check evidence, status evidence, workflow evidence, model/reviewer content,
formal GitHub review evidence, merge authority, and release authority are
separate types. An automated system may analyze and publish advice under an
auditable identity, but it satisfies a counted independent-approval gate only
when GitHub records a current, non-dismissed formal review from an actor who is
eligible under the ruleset and genuinely independent of the author/change
producer.

The guarded scheduler may merge only after GitHub and repository policy confirm
all gates. It cannot self-approve, dismiss valid findings for convenience, or
use merge authority to manufacture review authority. A missing independent
review defers that exact PR/head while unrelated safe work continues.

## Consequences

Some otherwise clean PRs will wait for a legitimate reviewer. That delay is a
governance dependency, not a CI defect. Automation can prepare precise evidence
and reduce reviewer effort but cannot eliminate the independent decision. The
organization needs a sustainable reviewer pool and clear ownership.

## Failure and recovery

If approval is absent, stale, dismissed, self-authored, bot-authored without
eligibility, or superseded by a new head, report the exact reason and hand off
to an eligible reviewer. Do not rerun unchanged checks or post repeated
comments. After a new formal review or head change, refetch every gate. A
mistaken merge triggers the incident runbook and reviewed revert path.

## Security and governance

Reviewer credentials and merge credentials are separate and auditable. Token
substitution does not create independence. Thread resolution occurs only for
actually addressed findings and does not erase the review record. Exceptions
cannot silently waive protected branch rules.

## Verification

Tests cover author, co-author/change-producer, eligible independent human/App,
ineligible bot, dismissed review, stale head, new change request, unresolved
thread, similar check/status names, and final ruleset denial. Live acceptance
confirms GitHub counts the intended review object.

## Migration and rollback

Maintain current rulesets while establishing the reviewer path tracked by
`.github#772`. Add eligibility telemetry and reviewer handoff without changing
gate semantics. Rollback removes faulty automation integration but retains the
GitHub approval requirement; disabling the requirement is not an operational
rollback.

## Supersession

This ADR is current. A successor may describe an organization-approved
independent App or reviewer service only if its ownership, identity,
eligibility, separation, revocation, audit, and protected-main acceptance are
proven.
