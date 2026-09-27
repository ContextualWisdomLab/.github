# Required review control-runner admission

## Cause and scope

On 2026-09-27, CO #1222 at `048d90b3715f792bd6a779d0b013c665fdb01385` still had queued required review entrypoints although five organization self-hosted runners were online. Central #2385 and #2417 are merged. Their scanner and scheduler routing does not change the required OpenCode/Noema entrypoints: these still explicitly request hosted Ubuntu. Existing queued attempts retain their original workflow configuration.

## Constrained assignment

Let x_j be 1 when an eligible admission job uses the control pool and 0 when it uses hosted capacity. Minimize sum(1 - x_j) over the six jobs, subject to 0 <= x_j <= 1, trusted central-main workflow identity, no PR-source execution, and separation of model/scanner work from control. The unique admissible pool is `CWL central control`; its one registered worker permits at most one executing job at a time, which GitHub enforces natively. Setting all six x_j to 1 attains the lower bound zero hosted admission jobs. This is a direct linear assignment, not an estimated optimum for completion time: model durations and historical queue positions are not reliable cost coefficients. No solver dependency or learned-policy claim is introduced.

All six OpenCode entrypoint jobs read metadata, retain required context names, dispatch, or clean superseded runs. They never checkout PR code. Noema control admission is independently owned by #2420. This PR leaves its worker and transport continuation unchanged.

## Runner policy and rollout

Group 6 must preserve `visibility=all`, `allows_public_repositories=true`, and `restricted_to_workflows=true`, retaining all existing selected workflows and adding only this exact central-main path:

- `ContextualWisdomLab/.github/.github/workflows/opencode-review.yml@refs/heads/main`

Read the live group immediately before PATCH and include the complete policy so omitted fields cannot erase existing restrictions. Read it back after mutation. The permission remains limited to jobs defined by these trusted central workflows, rather than arbitrary consumer workflows.

Tests pin the six assignments and absence of PR checkout, and retain the docs-only and exact-head dispatch contracts. Run affected contracts both normally and with `GITHUB_ACTIONS=true`, then actionlint. The maintainer explicitly authorized bypass merge for this CI admission repair; missing hosted checks must remain recorded as missing evidence.

After merge, verify a new targeted review/scheduler attempt uses `cwlab-s1-05`. Old queued runs are not deployment proof. A new workflow event or trusted central dispatch is needed to adopt the new configuration. Rollback restores the runner selectors and removes only the added OpenCode group path after verifying no dependent jobs need them.

## References

GitHub. *Choosing the runner for a job*. https://docs.github.com/en/actions/how-tos/write-workflows/choose-where-workflows-run/choose-the-runner-for-a-job

GitHub. *Managing access to self-hosted runners using groups*. https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/manage-access
