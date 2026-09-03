## Reusable default-branch Scorecard owner

- Centralize OSSF Scorecard execution, SARIF filtering, and code-scanning upload in
  `.github/workflows/scorecard-analysis.yml` while preserving the canonical owner's
  default-branch push and weekly schedule and exposing a `workflow_call` contract.
- Restrict duplicate cancellation to the same caller repository, ref, and exact
  source SHA so a delayed old event cannot cancel a newer authoritative scan.
- Keep consumer rollout incomplete until each repository replaces copied logic with
  a thin caller pinned to the central merge commit SHA, declares the required caller
  token permissions, preserves its actual default-branch and schedule triggers,
  repairs documentation, and proves caller-context SARIF behavior with a governed
  canary. `wardnet#160` and `semantic-data-portal#93` remain open repair branches
  until that successor evidence exists.
