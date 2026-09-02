# Dependency Review fail-closed authority and caller permission envelope

## Incident boundary

Protected `ContextualWisdomLab/.github` main introduced the central reusable Dependency Review workflow through #1724. Two migration defects were then observed independently and are repaired together in #1725 because both belong to the canonical reusable-workflow contract.

### Defect A — ambiguous HTTP status normalized to success

The initial reusable preflight treated Dependency Graph compare HTTP 403/404 as proof that the feature was unavailable, wrote `available=false`, and let the pull-request gate finish successfully. That inference is unsafe: an authorization/policy denial can present the same status shape. The repair keeps the exact base/head compare request but authorizes the action only on HTTP 200; every other pull-request response is blocking and reports its status.

Test-first evidence:

- RED `cb07b8bb28ef9d3a147cc966a0c70654d132da1d` makes 403/404-as-unavailable, the fallback note, and any non-explicit fail-closed response illegal.
- Production `31f60e532e135008cabd09fcddd46a53062b0ea0` removes the 403/404 success branch and fallback note, preserving the pinned action, inputs, and non-`pull_request` skip boundary.

### Defect B — thin callers lost required `GITHUB_TOKEN` permissions

The original repository-local workflows carried read permission envelopes, but the migration examples/thin callers did not preserve them uniformly. GitHub reusable workflows cannot elevate the caller token. Consequently the called workflow's own `permissions: contents: read, pull-requests: read` declaration is only a ceiling; it cannot grant `pull-requests: read` when the caller omitted it.

Live immutable-pin evidence isolates this from mutable-ref resolution:

| Consumer | Exact head | Run | Result before caller repair |
| --- | --- | --- | --- |
| `ContextualWisdomLab/newsdom-api#784` | `1623977e6c37c78cb1a94a7a48c48f6d02cac86c` | `33622976911` | `startup_failure`, zero jobs; referenced workflow resolved to `.github@0bcd22d8bb07650aafb0a8f116e4c2bbb8744f03` |
| `ContextualWisdomLab/mightyETL#330` | `65efdf7b4064df5b9811c0403defb707e6efbc02` | `33623035969` | `startup_failure`, zero jobs |

The consumer-side repair explicitly restores:

```yaml
permissions:
  contents: read
  pull-requests: read
```

Fresh heads then materialized Dependency Review runs instead of failing before job creation:

- newsdom-api `9a798d5ac7b9b295a1accb2327fc76611352290f`, run `33623818000`;
- mightyETL `4576f863ede9fca0673d6cce5ae8a4093246f5ab`, run `33623854807`;
- scopeweave `db8b8ed6d36a6dc6cc1d07255a7a9a86bc88bf4f`, run `33623761776`;
- Argos #557 `ee4c5dd326977407435b0f2425fdecebc34a810f`, run `33623867278`.

Central test-first repair for this second defect:

- RED `ee0f1ce544965772775b590050e40476df4ea8f6` adds `test_example_caller_preserves_required_permission_envelope()` without changing production/example workflow text. Against its parent it fails because the canonical caller example has no `permissions:` block.
- GREEN production `ca3bdbd210de988ccd31f7fb96d3a97adfdb9bff` adds the least-privilege caller envelope, explains the reusable-workflow permission ceiling, and replaces the mutable `@main` example with `<protected-main-commit-sha>`.

## Security invariants

1. Pull-request Dependency Review executes only after an exact base/head compare returns HTTP 200.
2. No HTTP 403/404 or other non-200 response is translated into a successful "unavailable" state.
3. OSV-Scanner, Scorecard, and the separate Security Scan path remain independent controls; they do not satisfy a failed Dependency Review gate.
4. The called workflow and each caller use only `contents: read` and `pull-requests: read` for this path. No write permission is introduced.
5. Product callers pin the central workflow to an immutable protected-main commit after merge. `@main`, PR heads, and branch URLs are not production authority.
6. A non-`pull_request` event may skip because it lacks the PR base/head identity required for the comparison.

## Verification and merge boundary

The focused contract is:

```bash
PYTHONPATH=. pytest -q tests/test_dependency_review_reusable_workflow_contract.py
```

The repository's normal exact-current-head required Checks, full coverage evidence, security scans, and independent reviews remain authoritative. #1725 stays Proposed/Draft while those gates are non-terminal or any substantive finding is unresolved. Queue saturation does not authorize bypass of a startup, permission, provenance, review, or security defect.

After #1725 reaches protected main through ordinary protection, each consumer must bump its immutable reusable-workflow pin to that protected-main SHA and regenerate exact-head Dependency Review evidence. No consumer should return to `@main`.

## References

GitHub. (n.d.-a). *Reusing workflow configurations*. GitHub Docs. https://docs.github.com/actions/using-workflows/reusing-workflows

GitHub. (n.d.-b). *Use GITHUB_TOKEN for authentication in workflows*. GitHub Docs. https://docs.github.com/actions/security-guides/automatic-token-authentication

GitHub. (n.d.-c). *REST API endpoints for the dependency graph*. GitHub Docs. https://docs.github.com/rest/dependency-graph
