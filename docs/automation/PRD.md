# Product requirements: CWL automation control plane

Status: approved product contract; implementation states are tracked in
[DOCUMENTATION_COVERAGE.md](DOCUMENTATION_COVERAGE.md).

## Product statement

The `ContextualWisdomLab/.github` repository is the organization control plane
that turns repository evidence into safe review, repair, merge, security, and
operational decisions without forcing every product repository to copy
privileged automation. It must keep each product independently operable while
providing a consistent, auditable organization-wide governance layer.

## Users and stakeholders

- **Repository maintainer:** needs actionable review and a safe path from an
  open PR to a protected merge.
- **Contributor:** needs deterministic gates, useful diagnostics, and no
  mutation of a head that was not reviewed.
- **Independent reviewer:** needs exact revision evidence and a clear boundary
  between advisory model output and counted approval.
- **Security and compliance operator:** needs least privilege, provenance,
  incident evidence, and controls compatible with SOC 2 and CSAP preparation.
- **Product owner and buyer:** needs reliable fleet governance that reduces
  integration risk without coupling products to a single runtime.
- **Automation agent:** needs a work-conserving queue, explicit authority, and a
  durable handoff instead of reconstructing decisions from conversation.

## Problems

1. PR evidence becomes stale when the source head or live base moves.
2. Checks, statuses, model verdicts, formal reviews, merge authority, and
   release authority can be mistaken for one another.
3. Privileged workflows copied into leaf repositories drift and widen the
   attack surface.
4. Long model reviews, provider outages, approvals, and CI queues tempt an
   automation loop to idle or report instead of doing other safe work.
5. Incident closure is often declared at source merge even though a real
   protected-main consumer path has not been exercised.
6. Durable decisions were scattered across large audit files, PR bodies, and
   conversations, leaving no complete ADR/PRD/TRD/UML/ERD spine.

## Product modes

### PR maintenance mode

The loop consumes open PRs in dependency order: refetch exact state, review all
current feedback, reproduce valid defects, apply the narrowest safe repair,
verify the new exact head, resolve only addressed threads, and merge only when
repository policy is satisfied. A queued check, provider cooldown, or approval
wait defers only that PR/head.

### Product development mode

When no existing PR or issue can safely advance, the loop selects one bounded
buyer-visible or operator-visible control-plane gap from the live protected
main, implements it test-first, documents its durable contracts, opens one
reviewable PR, and returns to the PR drain. Product development must not create
a competing writer for an active branch.

The hourly schedule is continuation capacity, not permission to stop after one
action. External task scheduling is an orchestration concern; repository truth
is expressed through issues, branches, PRs, tests, and protected-main evidence.

## Functional requirements

| ID | Requirement |
|---|---|
| PRD-001 | Bind every decision to target repository, PR number, exact source head, source ref, base branch, and independently observed current live-base state. |
| PRD-002 | Keep central privileged implementations in `.github`; leaf repositories use required workflows or thin explicit callers. |
| PRD-003 | Separate check evidence, status evidence, workflow evidence, formal review evidence, merge authority, release authority, and deployment authority. |
| PRD-004 | Fail closed on malformed identity, untrusted workflow provenance, missing required evidence, credential ambiguity, and stale review evidence. |
| PRD-005 | Permit bounded retries only for classified transient failures; integrity, authentication, authorization, TLS, ref, and policy failures do not receive blind retries. |
| PRD-006 | Enforce a single writer lease per repository branch and a separate read-only fleet-audit role. |
| PRD-007 | Preserve independent counted non-author approval where rulesets require it; automated reviews remain advisory unless GitHub records an eligible formal review. |
| PRD-008 | Treat CI/review waiting as a local deferred state and continue a different safe queue lane. |
| PRD-009 | Require protected-main and real consumer evidence before operational incident closure. |
| PRD-010 | Use explicit minimal secret contracts, short-lived OIDC/App credentials where supported, and `NVIDIA_NIM_API_KEY` only at the actual model-call boundary. |
| PRD-011 | Preserve useful failure and timeout diagnostics while redacting credential-shaped evidence before it reaches logs or summaries. |
| PRD-012 | Maintain 100% owned production statement, branch, and public-docstring coverage with realistic security, concurrency, rollback, and consumer tests. |
| PRD-013 | Keep the canonical documentation graph code-current and machine-checkable. |

## Buyer and operator outcomes

- A buyer can identify which component has authority for review, mutation,
  merge, release, and incident closure without reading implementation code.
- A maintainer sees the first failing boundary and a concrete rerun or repair
  path instead of a URL-only failure.
- A compromised or stale PR head cannot reuse predecessor evidence.
- A provider outage reduces review capacity but does not stop unrelated safe
  work or silently relax governance.
- A central repair is not called deployed until at least one enrolled consumer
  proves the protected-main path.

## Acceptance and closure criteria

1. Every mutation uses a freshly revalidated target identity and a head guard.
2. Required evidence on the unchanged exact head is present, complete, and
   authoritative for its own gate; queued, skipped, neutral-required,
   cancelled, absent, predecessor, or synthetic-only evidence is non-passing.
3. Zero valid unresolved review or security findings remain.
4. Ruleset-required independent approval is a counted eligible formal review.
5. Source tests, security gates, provenance/SBOM gates, and documentation
   contracts pass on the exact head.
6. Operational fixes have protected-main consumer evidence with run/job and
   target revision identity.
7. Rollback and incident-reopen conditions are documented before closure.

## Degraded behavior

- Missing model credentials or provider exhaustion produces no synthetic
  approval. Deterministic gates continue; model-dependent work is deferred.
- Missing cross-repository authority prevents only the cross-repository action.
  Same-repository and read-only work continue.
- GitHub API transient failures use bounded retry/fallback paths. Permanent
  permission, identity, integrity, TLS, and ref failures surface immediately.
- Queue saturation never converts pending work into success and never justifies
  a meaningless commit to retrigger review.
- A logging redactor that cannot safely transform evidence fails closed at the
  publication boundary; it does not change the command that was executed.

## Non-goals

- Replacing GitHub branch protection, rulesets, release environments, or the
  formal review model.
- Giving an LLM merge, release, or deployment authority by virtue of its
  textual verdict.
- Maintaining thick, synchronized copies of central workflows in every product.
- Masking all PII indiscriminately. Access control, purpose limitation,
  retention, auditability, and bounded disclosure are preferred controls where
  masking would make the work unusable.
- Treating documentation, a check mark, or a source merge as operational proof
  by itself.
