# CWL Automation Control Plane — Product Requirements

Status: active_pr

## Purpose

The ContextualWisdomLab organization automation control plane continuously moves repositories toward safe integration and commercial readiness without turning blocked PRs, queued checks, reviewer latency, or status narration into repository-wide idle time.

## Stakeholders

- Repository maintainers who need review → repair → exact-head verification → merge continuity.
- Product owners who need development to continue when one integration lane is blocked.
- Security and governance reviewers who require evidence separation, least privilege, auditable automation, and fail-closed behavior.
- Operators who need actionable incident state rather than repeated blocker reports.

## Product modes

### PR maintenance

1. Refetch live PR head and independently resolved live base tip.
2. Collect human and automated review evidence, checks, statuses, rulesets, and security gates.
3. Perform RCA for every non-passing or surprising gate.
4. Enumerate materially distinct remedies and verify real-world feasibility.
5. Execute the smallest safe root-cause-changing remedy test-first.
6. Revalidate the unchanged exact head.
7. Merge only when actual repository policy is satisfied.
8. Rotate immediately to another safe lane while any affected item waits.

### Product development

When integration work cannot consume the available execution budget, select a bounded high-value repository or control-plane gap, implement it test-first, document it, publish it for review, and return to the integration queue.

## Non-goals

- Manufacturing approvals or weakening branch protection.
- Treating model verdicts, statuses, or predecessor evidence as independent human approval.
- Racing a repository's dedicated writer.
- Using status reports as completion.
- Copying central implementation into every product repository.
- Claiming protected-main operational closure from a source PR alone.

## Acceptance criteria

- Waiting is scoped to the exact affected PR/action.
- Every actionable failure follows RCA → distinct remedies → feasibility → action → proof.
- Source-head, live-base, workflow, check, status, review, model, merge, release, and protected-main runtime evidence remain distinct authorities.
- Writer leases are explicit and branch-local where possible.
- Model credentials are materialized only on model-backed paths; autonomous development uses `NVIDIA_NIM_API_KEY`, not `COPILOT_GITHUB_TOKEN`.
- Routine runs do not stop after one commit, review request, merge, documentation update, or blocker.
- Before termination, a fresh whole-queue sweep proves no safe executable work remains or the practical invocation budget is exhausted.
- Canonical PRD/TRD/Architecture/ADR/UML/domain-model/security/operability/traceability documentation is code-current and machine-checked.

## Degraded behavior

Provider outages, rate limits, queued checks, missing external approval, and read-only dependencies defer only the affected lane. Deterministic work, other PRs, documentation repair, operational acceptance, and bounded product work continue when safe.

## Implementation status vocabulary

Canonical documents use only: `implemented_on_protected_main`, `active_pr`, `accepted_architecture`, `planned`, `research_only`, `superseded`, and `out_of_scope`.
