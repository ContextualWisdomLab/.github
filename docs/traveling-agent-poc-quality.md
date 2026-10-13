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
  group: poc-quality-${{ github.repository }}-${{ github.event.pull_request.number || format('{0}-{1}', github.event_name, github.ref) }}
  cancel-in-progress: true
jobs:
  offline-contracts:
    uses: ContextualWisdomLab/.github/.github/workflows/traveling-agent-poc-quality.yml@<CENTRAL_PROTECTED_MAIN_SHA>
```

The placeholder is intentionally unpublishable: the workflow does not exist at the inspected central base `4e32b99ec79b6565800d1081f60acfea368adecd`. Replace it only after reviewed supplier publication. No caller inputs or inherited secrets are needed. Supplier concurrency has a distinct literal namespace from `poc-quality-`; caller and called workflow must not cancel one another. Supplier PR keys omit the head SHA; non-PR fallback separates push from dispatch while retaining per-ref coalescing.

Validation is source/runtime-local only: the focused Python contract executes admission against synthetic events and the actual whitespace shell against disposable real Git repositories; `actionlint` validates workflow syntax. Runner access, clean-per-job capacity, GitHub exact-head execution, and formal approval remain external gates.

## Committed whitespace policy

Checkout requests full history (`fetch-depth: 0`); the final check refuses a shallow repository, malformed or absent commit objects, and a checkout that differs from the expected head. Missing event-range objects (including a force-push predecessor no longer fetched) fail closed rather than silently checking only the last commit. There is no authenticated follow-up fetch or caller-supplied shell input.

- PR: compare the exact event base SHA directly to the exact PR head SHA (`git diff --check BASE HEAD --`), not the working tree or a synthetic merge checkout.
- Push: compare event `before` to event `after`, requiring `after` to match the checked-out head. An all-zero `before` (initial branch push) compares the entire head tree against the empty tree; missing/nonzero invalid predecessors are rejected.
- Manual dispatch on main: check only the dispatched commit against its first parent (including merge commits). A root commit is checked against the empty tree. This is a latest-commit recheck, not a whole-history audit.

All event values enter the check through `env`, are validated as exact hexadecimal SHA values before Git use, and are passed as subprocess arguments rather than interpolated into shell commands. Caller PR cancellation uses repository and PR number, without a head SHA; push and manual dispatch retain separate repository/event/ref keys. The supplier keeps its distinct `traveling-agent-poc-quality-` namespace.
