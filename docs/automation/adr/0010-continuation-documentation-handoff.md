# ADR-0010 — Conversation, prompt, and documentation changes must hand off to executable work

Status: active_pr

## Context

The control plane already adopted work-conserving execution in ADR-0003, but an observed failure mode remained: an invocation could correctly identify a blocked PR, update a prompt, assess documentation, or produce a user-visible status and then stop even though another safe repository action remained. The design also allowed durable decisions to remain scattered across conversation history, automation prompts, PR bodies, incident comments, and downloadable planning packs instead of being reconciled into the canonical GitHub documentation graph.

This is not merely a reporting-style problem. Premature termination consumes scarce scheduled execution capacity, starves independent lanes, delays integration, and makes the declared work-conserving policy false in operation. Split documentation authority similarly creates contradictory product and security contracts.

## Alternatives

1. Treat user-visible status, prompt updates, or documentation assessments as valid end states and rely on the next hourly run.
2. Continue execution, but keep chat/prompt/PR-body decisions as equal specification authorities.
3. Require same-invocation continuation after every intermediate control/documentation action and require durable decisions to be reconciled into one canonical repository documentation authority.

## Decision

Use option 3.

A prompt update, documentation audit, ADR/PRD/TRD/UML/ERD edit, review request, merge, RCA, defer decision, queued check, approval wait, rate limit, or user-visible status is an intermediate event while another safe executable lane exists. The finite invocation must immediately refetch enough state to choose and execute the next lane.

Before any terminal response, the invocation performs a double exit sweep. If the first fresh sweep finds an execute-now item, it executes the highest-value safe item and resumes continuation. A second fresh sweep after the final substantive action must also find no execute-now item unless the practical invocation/tool budget is exhausted.

Durable decisions from conversation, automation prompts, planning artifacts, PR bodies, and incident records are evidence inputs. They become specification only after live implementation is refetched, the canonical owner is resolved, the existing documentation line is extended rather than duplicated, and the decision is assigned the controlled maturity state. Shared control-plane decisions belong in the `.github` canonical graph; product behavior remains in the owning product repository.

## Consequences

### Positive

- Scheduled execution capacity is consumed by repository progress rather than repeated narration.
- A blocked lane cannot implicitly block unrelated safe work.
- Prompt repair itself becomes testable control-plane work with a required repository handoff.
- Conversation-derived decisions become discoverable, reviewable, versioned, and traceable.
- Central and leaf repositories retain clear specification ownership.

### Negative

- Invocations perform more live-state reads and require stronger exact-identity/defer bookkeeping.
- Documentation changes can no longer be considered complete in isolation; the loop must return to the executable queue.
- Repository-by-repository conversation reconciliation is incremental and cannot be honestly declared complete without live leaf audits.

## Failure and recovery

A premature-termination incident exists when a run emits a terminal/status response while a fresh queue view proves another safe action was executable under the current writer lease and authority.

Recovery:

1. refetch the queue and identify the highest-value missed lane;
2. identify which prompt/control condition incorrectly treated the preceding event as terminal;
3. amend the authoritative automation prompt/configuration without weakening safety gates;
4. continue into the missed lane or next safe lane in the same invocation when possible;
5. update the canonical documentation/test contract if the failure exposed a missing durable invariant;
6. perform the double exit sweep before termination.

If documentation authority is split, freeze only the conflicting documentation lane, identify the canonical owner from live repository state and accepted ADRs, migrate or supersede duplicate claims without erasing audit history, and restore one indexed authority.

## Security and governance impact

Continuation never authorizes bypassing branch protection, counted review, writer leases, security gates, secret boundaries, dependency order, or exact-head/live-base validation. A lane that is unsafe becomes deferred; work conservation selects a different safe lane.

Conversation and prompt text are untrusted as implementation evidence. They cannot grant credentials, reviewer eligibility, write authority, merge authority, or `implemented_on_protected_main` status. External scheduler state can grant a writer lease only according to the accepted control-plane configuration; it does not become GitHub check/review/source evidence.

## Acceptance evidence

- The authoritative scheduled `.github` writer prompt explicitly states that prompt updates and user-visible output are non-terminal while safe work exists.
- PRD and TRD require same-invocation continuation and a double exit sweep.
- Architecture distinguishes the external orchestration, GitHub execution/evidence, and canonical documentation planes.
- The conceptual data model includes `execution_lane`, `deferred_item`, `continuation_handoff`, external automation control records, and documentation fitness.
- UML includes continuation and conversation-to-repository reconciliation flows.
- A documentation fitness audit records the previously missing boundaries and leaf-repository non-claims.
- The dependency-free documentation test requires these artifacts and invariants.
- Future runtime evidence demonstrates that a blocked PR causes lane rotation rather than a status-only termination.

## Migration and rollback

No GitHub runtime workflow, reviewer identity, credential, branch protection rule, or merge authority is changed by adopting this documentation decision. The external scheduled writer prompt is updated independently and can be rolled back to the prior configuration if continuation logic causes unsafe lane selection; writer leases and GitHub gates remain the safety boundary during rollback.

If a future scheduler provides an equivalent formally verified queue/continuation mechanism, this ADR may be superseded together with ADR-0003. Supersession must preserve single documentation authority, same-invocation work conservation, explicit termination proof, and evidence-channel separation.

## Supersession

Supersede only with an accepted decision that proves an equal or stronger no-early-stop continuation contract and a versioned single-authority conversation-to-repository reconciliation mechanism.
