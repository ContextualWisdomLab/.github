# Traveling Agent PoC quality workflow

This checkout contains the central reusable workflow candidate for the Traveling Agent PoC quality contract:

- `.github/workflows/traveling-agent-poc-quality.yml`
- callable only through `workflow_call`, with `contents: read`
- workflow-scope, trigger-aware concurrency: pull requests coalesce by repository and PR number; push/dispatch use repository, event, and ref fallback without head-SHA grouping
- rejects fork pull requests and non-`main` push/dispatch runs before runner admission; the shell admission repeats the same repository, event, base, and exact-head checks
- preserves the original 10-minute timeout, Python unittest discovery, Node syntax/renderer checks, whitespace check, and pinned checkout action
- checks out the PR head SHA (or event SHA for main push/dispatch) with `persist-credentials: false`
- requests only `CWL CI isolated` plus `self-hosted/Linux/X64/cwlab-ci-isolated`

The original caller's `pull_request`, `push` on `main`, and `workflow_dispatch` events, security permissions, and concurrency intent are represented by the dedicated contract tests. This source-only integration checkout does not alter runner-group settings, publish the supplier, or execute hosted Actions.

The leaf owner must retain caller workflow-scope cancellation before runner admission. Do not copy the earlier report-only caller that omitted concurrency. The intended caller is:

```yaml
name: PoC quality
on:
  pull_request:
  push:
    branches: [main]
  workflow_dispatch:
permissions:
  contents: read
concurrency:
  group: poc-quality-${{ github.ref }}
  cancel-in-progress: true
jobs:
  offline-contracts:
    uses: ContextualWisdomLab/.github/.github/workflows/traveling-agent-poc-quality.yml@<CENTRAL_PROTECTED_MAIN_SHA>
```

The placeholder is intentionally unpublishable: the workflow does not exist at the inspected central base `4e32b99ec79b6565800d1081f60acfea368adecd`. Replace it only after reviewed supplier publication. No caller inputs or inherited secrets are needed. Supplier concurrency has a distinct literal namespace from `poc-quality-`; caller and called workflow must not cancel one another. Supplier PR keys omit the head SHA; non-PR fallback separates push from dispatch while retaining per-ref coalescing.

Validation is source/runtime-local only: the focused Python contract executes the admission shell against synthetic events, while `actionlint` validates workflow syntax. Runner access, clean-per-job capacity, GitHub exact-head execution, and formal approval remain external gates.
