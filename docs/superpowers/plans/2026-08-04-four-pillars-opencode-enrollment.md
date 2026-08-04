# Four Pillars OpenCode Enrollment Implementation Plan

**Goal:** Enroll `ContextualWisdomLab/four-pillars` in the central privileged OpenCode review dispatcher without weakening the exact-repository allowlist or changing the review/merge trust boundary.

**Architecture:** Keep the organization variable `OPENCODE_REPOSITORY_DISPATCH_TARGETS` as the primary configurable allowlist and append the Four Pillars repository as one explicit exact target at expression-evaluation time. Preserve live PR metadata binding, actor/sender verification, exact string comparison, current-head review publication, independent Noema approval, and guarded merge behavior.

**Tech stack:** GitHub Actions, Bash, Python contract tests, pytest, organization required workflows.

## Constraints

- No wildcard or organization-wide target authorization.
- No pull-request code execution with privileged review credentials.
- No new repository or organization secret.
- The existing configurable allowlist remains active.
- The target repository is compared by exact `owner/name` equality after whitespace normalization.
- Central workflow, documentation, and contract tests must agree.

## Task 1: Lock the failing enrollment contract

- Add a focused test requiring the dispatcher to preserve `vars.OPENCODE_REPOSITORY_DISPATCH_TARGETS` and explicitly include `ContextualWisdomLab/four-pillars`.
- Require the existing exact-match loop and rejection path.
- Verify the test fails on the unmodified workflow because the repository is not yet enrolled.

## Task 2: Apply the least-privilege workflow change

- Change only the `ALLOWED_DISPATCH_TARGETS` environment expression so it evaluates to the current organization-variable list plus the explicit Four Pillars repository.
- Do not change the actor gate, metadata gate, target regex, exact equality comparison, token exchange, review publication, or merge scheduler.
- Update the rollout documentation with the explicit enrollment and operational reason.

## Task 3: Verify and merge

- Run all central tests, shell/YAML contract checks, public docstring checks, and coverage gates.
- Review the complete diff and resolve every current-head finding.
- Merge only after all required reviews and checks pass.
- Confirm the next scheduler pass dispatches the actual OpenCode reviewer for Four Pillars PR #18, followed by independent Noema review and guarded exact-head merge.