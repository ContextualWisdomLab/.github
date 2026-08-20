# ADR-0001: Central review for stacked pull requests

- Status: Accepted
- Date: 2026-08-20
- Owners: ContextualWisdomLab platform maintainers
- Figma File ID: N/A — this is a workflow and governance contract with no UI

## Decision

The organization ruleset `CWL Central required workflows` (`18156473`) applies
to every branch reference (`ref_name.include=["~ALL"]`) in inherited
repositories. Central OpenCode, Noema, security, and scheduler workflows stay
owned by `ContextualWisdomLab/.github` at `refs/heads/main`.

## Context

Stacked PRs target another feature branch, so a default-branch-only ruleset did
not materialize the central required workflow entrypoints. This left buyer-
visible changes with local checks but without the same independent review and
security evidence used for main-targeting PRs.

## Consequences

- Every stacked PR receives the same current-head governance entrypoints.
- The scheduler may dispatch review-only work for non-default base branches;
  merge automation remains guarded by the PR's actual policy and checks.
- Branch-scope drift is detected by
  `scripts/ci/audit_central_required_workflows.py` and its regression tests.
- No workflow is copied into a product repository, preserving the MSA control
  boundary.

## Verification

The exact live ruleset was read before and after the change. TEPP pull requests
`#158` and `#159` were re-read at their current heads before review-only
dispatch. Hosted Checks remain authoritative for merge decisions.
