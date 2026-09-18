# Strix evidence binding for PR-delta and remediation claims

Status: accepted 2026-09-17

## Incidents

### #2159 — PR-delta vs repository baseline

Required Strix review on `.github#2106` reported source findings against
`scripts/ci/pingora_edge_policy.py` and
`scripts/ci/contextual_orchestrator_review_policy.py` even though both blobs
were base-identical across the authenticated PR tuple. The PR review lane
treated those observations as if they were introduced by the PR.

### #2168 — false "already applied" remediation

LineageWeave Strix run `34746057545` completed SUCCESS with a valid Medium
finding, but the report claimed the fix was "already applied" and
"syntax-verified" after `apply_patch` failed with
`WorkspaceReadNotFoundError` / `ApplyPatchFileNotFoundError` against
`/workspace/backend/app/main.py` instead of the materialized scan workspace.

## Decision

1. `scripts/ci/strix_evidence_binding.py` classifies each finding against an
   authenticated changed-file inventory (including renames and hunk lines) as
   `pr_delta`, `repository_baseline`, `context_dependency`, or `unmapped`.
2. The Strix gate labels blocking PR intersections as `evidence_scope=pr_delta`
   and unchanged-path continuations as `evidence_scope=repository_baseline`.
3. After each attempt, the gate sanitizes report artifacts through the binder
   so an `apply_patch` miss cannot remain summarized as "already applied".
4. Remediation states distinguish `finding_confirmed`, `fix_proposed`,
   `fix_applied_in_scan_workspace`, `fix_validated`,
   `fix_committed_to_source`, and `remediation_failed`. A fix is never marked
   applied without workspace-byte proof or an exact source commit receipt.

## Evidence and rollback

Contract tests in `tests/test_strix_evidence_binding.py` cover changed-source,
base-identical, context-dependency, rename, stacked-base, stale-head, and
apply_patch-miss RED fixtures. Gate wiring is pinned by
`assert_strix_evidence_binding_contract` in
`scripts/ci/test_strix_quick_gate.sh`. Roll back only with an equivalent
fail-closed evidence binder; do not restore false PR-delta attribution or
false remediation claims.

## References

- ContextualWisdomLab/.github#2159
- ContextualWisdomLab/.github#2168
