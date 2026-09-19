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

## Fixture runtime closure RCA (2026-09-20)

Agent Review Runtime Quality run `35445211402`, job `105902856459`, checked out
`.github#2272@cd3b41b8`; run `35448837045`, job `105912348418`, later reproduced
the same failure on `.github#2109@db84349c`. In both logs the first causal
message is `ERROR: Strix evidence binder is missing`. The shell self-test copied
`strix_quick_gate.sh` and `strix_model_utils.sh` into isolated repositories but
not the binder the gate executes, so ordinary success, retry, provider-failure,
scope, and remediation fixtures collapsed into hundreds of exit-code and output
assertions.

The first attempted repair was not valid evidence. Commit `857e7882` cut
`tests/test_strix_evidence_binding.py` at the token `exce`; `89cee557` replaced
the 13,138-line shell contract with 675 lines; and `1eb03c7a` deleted 4,176
lines from CHANGELOG and the product-gap authority. The claimed `37 passed`
could not be reproduced from that exact tree because the Python file did not
compile. Those commits remain in ancestry for auditability and are restored
ordinary-forward after adopting protected `main`; no force update or destructive
rebase is used.

The corrected RED is `tests/test_strix_fixture_runtime_closure.py`: the broken
head had zero of the 25 model-helper fixture copies and failed `0 == 25`; after
restoring the complete harness it proved the precise residual defect, 25 model
helpers versus zero binders. GREEN adds the binder alongside each model helper,
leaving production gate behavior unchanged. Hosted acceptance and downstream
adoption remain separate current-head gates.

## References

- ContextualWisdomLab/.github#2159
- ContextualWisdomLab/.github#2168
- ContextualWisdomLab/.github#2272
