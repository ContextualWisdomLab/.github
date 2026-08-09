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

### Continuation and conversation handoff

The control plane treats a prompt update, documentation update, blocked PR, or user-visible status as an intermediate event rather than a completion signal. If another safe executable lane exists, the same invocation continues into that lane. A status response that merely restates one blocked item while other executable work exists is a premature-termination defect in the control plane.

Durable decisions established in the CWL project conversation are evidence inputs, not the canonical specification. Material decisions that affect automation behavior, evidence authority, writer leases, product boundaries, security, operations, or acceptance criteria must be reconciled into the existing canonical GitHub documentation line with an explicit implementation-status classification. Conversation history and downloadable planning artifacts must never be silently promoted to `implemented_on_protected_main`.

## Non-goals

- Manufacturing approvals or weakening branch protection.
- Treating model verdicts, statuses, or predecessor evidence as independent human approval.
- Racing a repository's dedicated writer.
- Using status reports as completion.
- Copying central implementation into every product repository.
- Claiming protected-main operational closure from a source PR alone.
- Creating a parallel documentation authority when a canonical documentation branch already owns the topic.

## Acceptance criteria

- Waiting is scoped to the exact affected PR/action.
- Every actionable failure follows RCA → distinct remedies → feasibility → action → proof.
- Source-head, live-base, workflow, check, status, review, model, merge, release, and protected-main runtime evidence remain distinct authorities.
- Writer leases are explicit and branch-local where possible.
- Model credentials are materialized only on model-backed paths; autonomous development uses `NVIDIA_NIM_API_KEY`, not `COPILOT_GITHUB_TOKEN`.
- Routine runs do not stop after one commit, review request, merge, documentation update, prompt update, user-visible status, or blocker.
- Prompt repair and documentation fitness work hand off to the next safe GitHub action in the same invocation when one exists.
- Before termination, a first fresh whole-queue sweep finds no safe executable work; after any action triggered by that sweep, a second fresh sweep must also find no execute-now item, unless the practical invocation budget is exhausted.
- Canonical PRD/TRD/Architecture/ADR/UML/domain-model/security/operability/traceability/documentation-audit material is code-current and machine-checked.
- External scheduled agent/orchestrator state and GitHub-native workflow execution/evidence are modeled as distinct control-plane boundaries.

## Degraded behavior

Provider outages, rate limits, queued checks, missing external approval, and read-only dependencies defer only the affected lane. Deterministic work, other PRs, documentation repair, operational acceptance, and bounded product work continue when safe.

## Implementation status vocabulary

Canonical documents use only: `implemented_on_protected_main`, `active_pr`, `accepted_architecture`, `planned`, `research_only`, `superseded`, and `out_of_scope`.
