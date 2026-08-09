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

No evidence type silently substitutes for another.

## Gate taxonomy

`success` is exact-current evidence only. `queued`, `pending`, `cancelled`, `skipped-required`, `neutral-required`, `absent`, `failed`, stale-head, predecessor-head, synthetic-only, and infrastructure-only evidence are not success.

## RCA contract

For each non-passing gate capture the first failing boundary, trigger, rendered inputs, permissions, credential boundary, immediate cause, technical root cause, systemic/control cause when material, correction owner, and a falsifiable hypothesis.

Generate materially distinct remedies. Before mutation verify current API/tool support, authority, credential scope, reviewer eligibility, rulesets, workflow semantics, dependency order, writer lease, rate/runtime constraints, blast radius, rollback, security/privacy impact, and exact acceptance evidence.

## Writer lease

A repository with an enabled dedicated writer loop is read-only to other writer loops. Before every write, refetch exact target head/base/blob/ref and relevant review state. Source/ref/blob movement or another active writer targeting the same branch invalidates the write lease for that branch. Review/check completion alone is not a writer conflict.

## Concurrency and retries

- Pending external evidence is deferred by exact identity; unchanged deferred items are not repeatedly polled.
- Transient transport/bootstrap failures may receive bounded classified retries.
- Integrity, authentication, TLS, ref mismatch, stale-head, permission, and policy failures remain fail-closed.
- A retry must be capable of changing the diagnosed causal boundary.

## Secrets and model paths

Deterministic gates execute before model-secret materialization whenever possible. Reusable workflows declare minimal explicit secret contracts. Blanket inheritance is avoided unless independently justified. Development/model-backed automation uses `NVIDIA_NIM_API_KEY`; `COPILOT_GITHUB_TOKEN` is not a development-model credential.

## Approval authority

Automated reviewer/model evidence is advisory unless live repository policy explicitly says otherwise. COMMENTED reviews, statuses, checks, reactions, author evidence, dismissed reviews, textual approval, and predecessor-head reviews never become qualifying independent approval by inference.

## Operational closure

A merged source repair is not operational closure. For control-plane incidents, closure requires protected-main scheduled/manual consumer evidence on the integrated implementation, with the expected failure mode absent and the intended bounded behavior observed.

## Documentation fitness

Canonical documentation must distinguish implementation maturity and map requirements/ADRs to workflows, scripts, tests, incidents, and acceptance evidence. Documentation tests should validate links, state names, secret contracts, diagram integrity, ADR index consistency, and stale terminology where practical.
