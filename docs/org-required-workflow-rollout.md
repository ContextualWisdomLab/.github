# ContextualWisdomLab central required workflow rollout

Updated: 2026-09-01 KST

## Purpose

This document is the operator-facing current-state contract for organization-wide pull-request admission. Historical rollout experiments, exact transient PR heads, runner IDs, and superseded review-count policies remain available in Git history and the linked governance issues; they are intentionally not repeated here because stale operational snapshots can recreate a closed governance defect.

## Canonical organization ruleset

Use the organization ruleset rather than copying central review/security workflow files into each product repository.

- Ruleset: `CWL Central required workflows`
- Ruleset ID: `18156473`
- Enforcement target: active branch rules on each non-excluded repository's default branch only.
- Repository selector: all organization repositories except `.github`, `IRT-bibliography-set`, and `noema`.
- Ref selector: `ref_name.include=["~DEFAULT_BRANCH"]`, `ref_name.exclude=[]`.
- Required workflow source: `ContextualWisdomLab/.github` repository ID `1274066402` at `refs/heads/main`.
- Required workflow paths:
  - `.github/workflows/close-empty-pr.yml`
  - `.github/workflows/noema-review.yml`
  - `.github/workflows/opencode-review.yml`
  - `.github/workflows/pr-review-merge-scheduler.yml`
  - `.github/workflows/security-scan.yml`
  - `.github/workflows/strix.yml`
  - `.github/workflows/sast-semgrep.yml`
- The workflows rule must set `do_not_enforce_on_create=true`; proposal-branch creation must remain possible.
- The central ruleset must contain only the declared `workflows`, `pull_request`, `deletion`, and `non_fast_forward` rule types. An added `creation` or other undeclared rule is governance drift because it can defeat the proposal-branch transition or add an unreviewed protected-branch constraint.

The scheduled audit reads the inherited organization ruleset through a consumer repository, enumerates repository inheritance, reads the owner `.github` repository ruleset, and reads the stacked OpenCode ruleset. Once a payload is fetched successfully, drift in one payload must not suppress the remaining available audits; all fetched drift reasons are emitted before the job fails. API/read failures still fail immediately because the missing payload cannot be audited.

## Solo-maintainer review policy

ContextualWisdomLab currently has one human maintainer. A generic positive human-approval count is therefore structurally unsatisfiable for a maintainer-authored PR when self-approval is prohibited. Model and service identities provide deterministic/advisory evidence; they are not independent human reviewers and must not be counted as such.

The current protected-PR policy is:

- `required_approving_review_count = 0`;
- `require_last_push_approval = false`;
- `required_reviewers = []` unless governance later identifies a genuinely independent human authority;
- `dismiss_stale_reviews_on_push = true`;
- `required_review_thread_resolution = true`;
- only merge and squash are allowed merge methods;
- deletion and non-fast-forward protection remain enabled; and
- routine bypass actors are forbidden.

No bot approval, service account, broadened token, self-approval, or `OrganizationAdmin/always` bypass may be used to simulate human independence. Emergency control-plane repair belongs to the separately governed, time-bounded, auditable break-glass process.

Issue `#772` is the policy decision, issue `#1351` tracks declared-versus-live drift, issue `#1340` owns routine administrator-bypass removal, and PR `#1176` is the canonical audit/test writer. Consumer repositories must not add local shims to work around this central policy.

## Current live drift

As of the 2026-09-01 live reads used by PR `#1176`, organization ruleset `18156473` still requires one approving review and still exposes `OrganizationAdmin/always` bypass. The owner `.github` repository ruleset `17921150` already reports zero approving reviews and no last-push requirement but still permits `rebase` and retains routine administrator bypass. These are live settings defects, not permission to weaken the audit.

Do not claim the rulesets are reconciled until an authorized settings mutation is followed by a fresh full-payload read. A passing source-level auditor only proves the declared contract, not the live GitHub configuration.

## Model-review gates

### OpenCode

`.github/workflows/opencode-review.yml` is a required deterministic review workflow. Its trusted `pull_request_target` surface is metadata-only; PR-controlled source is reviewed as data through the protected dispatch workflow and must not be executed with privileged credentials. Current-head evidence, model output, coverage/source inspection, review publication, and exact repository/base/head binding remain fail-closed. Draft PR handling and model-exhaustion behavior must follow the current central implementation; old approval bodies or predecessor heads never transfer.

OpenCode review evidence is a model/control-plane gate, not a human approval for `required_approving_review_count`.

### Noema

`.github/workflows/noema-review.yml` is a separate required deterministic review workflow backed by the organization-owned Noema review identity and centrally versioned judgement path. It provides independent model evidence and may publish a PR review, but that App-authored review is not represented as a second human maintainer. Missing credentials, missing exact-head evidence, or a failed judgement remain visible failures rather than skipped success.

The standalone `ContextualWisdomLab/noema` judgement plane remains outside the privileged workflow import boundary unless a separately reviewed integration transfers that responsibility.

## Security and dependency review

The required `security-scan.yml` and `sast-semgrep.yml` workflows remain base-ref agnostic so they also observe stacked PRs even though protected-ref rules are a separate control.

Dependency Review is authoritative only when the exact `BASE_SHA...HEAD_SHA` comparison succeeds with transport success and HTTP `200`, after which the pinned `actions/dependency-review-action` actually executes. HTTP 403/404, malformed/empty status, transport failure, timeout, or missing authoritative comparison evidence fail closed. OSV, Trivy, Scorecard, CodeQL, SAST, or secret-scanning evidence are useful sibling controls but are not semantic substitutes for Dependency Review. Current public-repository HTTP 403 availability is tracked by issue `#810`; product repositories must not add a local fail-open shim.

## Scheduler and merge boundary

`.github/workflows/pr-review-merge-scheduler.yml` owns mechanical merge/update orchestration after policy evidence exists. For each candidate PR it must re-fetch the exact current head, base, reviews, unresolved threads, required checks, security evidence, and merge state. Stale, predecessor, queued, pending, skipped-required, cancelled, neutral, model-only, or absent evidence is non-passing.

The scheduler may directly or automatically merge only through ordinary branch protection when all then-current deterministic requirements are satisfied. Fork/external heads stay reviewable but are excluded from unattended branch mutation. A `DIRTY`/conflicting PR requires source repair; queued auto-merge is not a conflict resolver.

The organization queue sweep is a heartbeat, not an evidence substitute. It may retry eligible current-head work, but it cannot manufacture approval, downgrade a failed check, transfer evidence between heads, or use a repository-local workaround for a central defect.

## Stacked PR ruleset

Ruleset `21732164`, `CWL Stacked OpenCode required workflow`, remains `evaluate`-mode evidence over non-default branches with `ref_name.include=["~ALL"]` and `ref_name.exclude=["~DEFAULT_BRANCH"]`, requiring only the central OpenCode workflow and exempting branch creation. Active enforcement across every non-default ref is prohibited because GitHub can evaluate the ref update before a new exact-head required-workflow run can exist, deadlocking both branch creation and later stack fixes.

Stacked PRs therefore use exact-head OpenCode evidence and ordinary PR procedure while the organization develops a target-ref-scoped enforcement design. Additional rule types in the stacked ruleset are drift.

## Owner repository ruleset

Repository ruleset `17921150`, `Lock default branch`, protects `ContextualWisdomLab/.github` itself. The declared contract is default-branch-only scope, zero generic approvals, no last-push requirement, no required reviewers, stale-review dismissal, thread resolution, merge/squash only, deletion protection, non-fast-forward protection, and no bypass actors. Any extra rule type is rejected unless governance first documents and tests an explicit allowed extension.

## Validation procedure

For every policy change:

1. Re-read live organization and repository rulesets before changing source or settings.
2. Add a failing regression for the exact drift class before changing auditor/workflow behavior.
3. Run the permanent ruleset suites on the exact writer head. A temporary branch-only proof workflow may be used when ordinary hosted execution does not exercise the new path, but it must use least privilege and immutable dependencies.
4. Do not call a queued, cancelled, skipped, neutral, stale, predecessor, or missing run GREEN.
5. Remove temporary proof workflows only after terminal-success evidence exists for the then-current exact head and their durable regressions no longer depend on the temporary file.
6. Apply the authorized live settings change without routine bypass, synthetic reviewers, self-approval, force push, or direct protected-branch write.
7. Re-read the complete live payload after mutation and compare it with the executable audit contract.
8. Re-use an unchanged deterministic-GREEN consumer PR as a canary. Orgmetra PR `#88` is suitable while it remains unchanged and otherwise clean.
9. Merge only through ordinary protection after all current-head deterministic evidence and review-thread requirements are terminal successful.

## Traceability

- `.github#772` — solo-maintainer protected-PR policy decision.
- `.github#1351` — declared-versus-live central review-policy drift.
- `.github#1340` — routine administrator bypass / break-glass boundary.
- `.github#1200` — default-branch scope and branch-create transition.
- `.github#810` — Dependency Review fail-closed contract and current availability incident.
- `.github#624` — OpenCode control-plane work.
- `.github#1327` — Strix control-plane work.
- `.github#1399` — shared Noema sidecar/control-plane work.
- `.github` PR `#1176` — canonical executable ruleset audit/test writer.

This guide is intentionally current-state oriented. Historical rollout tables, old approval counts, transient exact heads, and superseded experiments are preserved by Git history and the linked issues/PRs rather than being presented as present operator instructions.