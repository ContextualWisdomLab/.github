# ADR-0001: Central review for stacked pull requests

- Status: Accepted
- Date: 2026-08-20
- Owners: ContextualWisdomLab platform maintainers
- Figma File ID: N/A — this is a workflow and governance contract with no UI

## Decision

The organization ruleset `CWL Central required workflows` (`18156473`) applies
exactly to each inherited repository's default branch
(`ref_name.include=["~DEFAULT_BRANCH"]`, `ref_name.exclude=[]`). Its workflows
use `do_not_enforce_on_create=true`. Central OpenCode, Noema, security, and
scheduler workflows stay owned by `ContextualWisdomLab/.github` at
`refs/heads/main`.

## Context

Stacked PRs target another feature branch, so the default-branch ruleset does
not materialize required-workflow entrypoints for that intermediate PR. The
central scheduler supplies exact-head review-only evidence for the stacked
phase. Applying the combined workflow, pull-request, deletion, and
non-fast-forward rules to every ref was rejected after live 409/422 canaries
proved that it made normal proposal-branch creation and updates impossible.

## Consequences

- Every stacked PR receives current-head central review-only dispatch.
- The scheduler does not update or merge non-default-base PRs; the final
  default-branch integration PR receives the full required-workflow gate.
- Proposal refs can be created and updated without a circular requirement for
  checks that cannot exist before the ref exists.
- Branch-scope drift is detected by
  `scripts/ci/audit_central_required_workflows.py` and its regression tests.
- No workflow is copied into a product repository, preserving the MSA control
  boundary.

## Verification

The exact live ruleset was read before and after the change. TEPP pull requests
`#158` and `#159` were re-read at their current heads before review-only
dispatch. Hosted Checks remain authoritative for merge decisions.
