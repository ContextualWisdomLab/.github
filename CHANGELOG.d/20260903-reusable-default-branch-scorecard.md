## Reusable default-branch Scorecard owner

- Centralize OSSF Scorecard execution, SARIF filtering, and code-scanning upload in
  `.github/workflows/scorecard-analysis.yml` while preserving the canonical owner's
  default-branch push and weekly schedule and exposing a `workflow_call` contract.
- Keep the ref-scoped, `cancel-in-progress: false` concurrency group `.github#1768`
  already established (queue rather than cancel a burst of same-ref pushes, so an
  in-flight scan's SARIF evidence for its own commit is never discarded).
- Keep consumer rollout incomplete until each repository replaces copied logic with
  a thin caller pinned to the central merge commit SHA, declares the required caller
  token permissions, preserves its actual default-branch and schedule triggers,
  repairs documentation, and proves caller-context SARIF behavior with a governed
  canary. `wardnet#160` and `semantic-data-portal#93` remain open repair branches
  until that successor evidence exists.
