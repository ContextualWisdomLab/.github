# CWL Automation Control Plane — Technical Requirements

Status: active_pr

## Evidence identity

A decision must bind separately to:

- `source_revision`: exact PR head commit.
- `base_revision`: independently resolved current tip of the target base ref.
- `workflow_evidence`: workflow/run/job identity and the commit actually checked out.
- `check_evidence`: check name, state, conclusion, and checked revision.
- `review_evidence`: reviewer identity, formal state, reviewed revision where known, and thread state.
- `status_evidence`: commit-status context, creator, state, and revision.
- `operational_acceptance`: protected-main scheduled/manual consumer execution after integration.
- `automation_control_record`: external scheduler/orchestrator configuration and enabled state when it grants or withholds a writer lease.
- `continuation_handoff`: the proof that an intermediate action was followed by the next selected executable lane, or by a valid double-exit conclusion.

No evidence type silently substitutes for another.

## Gate taxonomy

`success` is exact-current evidence only. `queued`, `pending`, `cancelled`, `skipped-required`, `neutral-required`, `absent`, `failed`, stale-head, predecessor-head, synthetic-only, and infrastructure-only evidence are not success.

## RCA contract

For each non-passing gate capture the first failing boundary, trigger, rendered inputs, permissions, credential boundary, immediate cause, technical root cause, systemic/control cause when material, correction owner, and a falsifiable hypothesis.

Generate materially distinct remedies. Before mutation verify current API/tool support, authority, credential scope, reviewer eligibility, rulesets, workflow semantics, dependency order, writer lease, rate/runtime constraints, blast radius, rollback, security/privacy impact, and exact acceptance evidence.

## Writer lease

A repository with an enabled dedicated writer loop is read-only to other writer loops. Before every write, refetch exact target head/base/blob/ref and relevant review state. Source/ref/blob movement or another active writer targeting the same branch invalidates the write lease for that branch. Review/check completion alone is not a writer conflict.

External automation state is a real lease input but is not GitHub source evidence. A scheduled agent/orchestrator can own a repository write lease while GitHub Actions, reviews, and checks provide execution or validation evidence. The control plane records those authorities separately and revalidates both before mutation.

## Concurrency and retries

- Pending external evidence is deferred by exact identity; unchanged deferred items are not repeatedly polled.
- Transient transport/bootstrap failures may receive bounded classified retries.
- Integrity, authentication, TLS, ref mismatch, stale-head, permission, and policy failures remain fail-closed.
- A retry must be capable of changing the diagnosed causal boundary.
- A blocked execution lane never consumes the entire run while another independent safe lane is executable.

## Continuation and termination contract

Every finite invocation maintains a live executable queue. After each mutation, merge, review request, RCA, documentation change, prompt change, defer decision, or operational proof, the scheduler selects the next executable lane before considering termination.

A `continuation_handoff` records at least the completed lane identity, the newly observed state that caused defer or completion, and the next selected lane or termination reason. User-visible output is not itself a valid termination reason.

Termination requires a double exit sweep:

1. the first fresh queue-wide sweep must find no execute-now item; if it finds one, execute the highest-value safe item and restart continuation selection;
2. a second fresh queue-wide sweep after the final substantive action must also find no execute-now item, unless the practical invocation/tool budget is exhausted.

The double exit sweep covers source repairs, merges, addressed review-thread resolution, duplicate closure, Draft/issue advancement, protected-main acceptance, canonical documentation repair, tests/security/reliability work, release preparation, and bounded product/control-plane development.

## Conversation-to-repository reconciliation

Conversation history, uploaded planning packs, automation prompts, PR bodies, and incident comments are evidence inputs. They do not become durable specification until reconciled into the canonical GitHub documentation line. Reconciliation must:

- refetch protected-main implementation and relevant active PRs first;
- update the existing canonical documentation branch rather than create a parallel authority;
- assign the controlled maturity state to every material decision;
- preserve disagreement or supersession instead of silently combining incompatible claims; and
- update machine-checkable documentation contracts when a new required authority, document, or invariant is introduced.

## Secrets and model paths

Deterministic gates execute before model-secret materialization whenever possible. Reusable workflows declare minimal explicit secret contracts. Blanket inheritance is avoided unless independently justified. Development/model-backed automation uses `NVIDIA_NIM_API_KEY`; `COPILOT_GITHUB_TOKEN` is not a development-model credential.

## Approval authority

Automated reviewer/model evidence is advisory unless live repository policy explicitly says otherwise. COMMENTED reviews, statuses, checks, reactions, author evidence, dismissed reviews, textual approval, and predecessor-head reviews never become qualifying independent approval by inference.

## Operational closure

A merged source repair is not operational closure. For control-plane incidents, closure requires protected-main scheduled/manual consumer evidence on the integrated implementation, with the expected failure mode absent and the intended bounded behavior observed.

## Documentation fitness

Canonical documentation must distinguish implementation maturity and map requirements/ADRs to workflows, scripts, tests, incidents, external automation boundaries, and acceptance evidence. Documentation tests should validate links, state names, secret contracts, continuation terms, diagram integrity, ADR index consistency, documentation-audit presence, and stale terminology where practical.
