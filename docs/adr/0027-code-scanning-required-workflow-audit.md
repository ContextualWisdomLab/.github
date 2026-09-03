# ADR-0027: Audit all organization-required code-scanning workflows

- **Status:** Proposed
- **Date:** 2026-09-02
- **Scope:** organization ruleset `18156473`, `scripts/ci/audit_central_required_workflows.py`, and its executable ruleset contracts

## Problem

Organization ruleset `18156473` was expanded on 2026-09-02 to require the central CodeQL, Scorecard, and OSV PR workflows in addition to the original seven required workflows. The protected-main audit source still enumerated only those original seven paths. As a result, the scheduled governance audit could report success even if one or all of the newly required code-scanning workflows disappeared from the live ruleset.

The defect is a control-plane single-writer mismatch: live policy changed but its canonical executable audit contract did not change with it. Documentation alone cannot close that gap.

## Constraints

1. The audit remains fail closed: every required workflow path must be present exactly once and sourced from `ContextualWisdomLab/.github@refs/heads/main`.
2. Existing repository-scope, pull-request review, deletion, non-fast-forward, and stacked-PR checks remain unchanged.
3. The three workflow files already exist in the canonical repository; this decision does not copy workflow source into consumers.
4. No mutable branch or PR head becomes consumer release authority. Live ruleset source ref remains `refs/heads/main` and protected-main history remains the production authority.
5. The PR remains Draft/Proposed until exact-current-head required Checks, security evidence, and independent reviews are terminal and clean.

## Alternatives

### Keep the audit at seven paths and rely on rollout documentation

Rejected. The original incident was caused by documentation and live policy diverging. A prose-only control repeats the same failure mode.

### Add a separate optional code-scanning audit

Rejected. These workflows are already part of the same active organization required-workflow rule. Optional or separately invoked validation would allow the canonical audit to pass while security-policy drift exists.

### Audit all ten paths in the existing canonical contract

Selected. The existing audit already validates path uniqueness, source repository, and source ref. Extending its required path set reuses the established fail-closed mechanism and makes future drift observable.

## Decision

`REQUIRED_WORKFLOW_PATHS` contains all ten organization-required paths, including:

- `.github/workflows/codeql-pr.yml`
- `.github/workflows/osv-scanner-pr.yml`
- `.github/workflows/scorecard-pr.yml`

The main ruleset fixture is derived from that canonical tuple so tests cannot silently preserve a second seven-path policy. Structural-drift expectations and rollout-document assertions are extended to the three code-scanning paths.

## Test-first evidence

- RED/current-main reconciliation: `3608fbee43da40d91dadda6afaa8881aacd450c3`. Its new regression requires all three code-scanning paths while the exact source at that commit still contains only seven paths.
- Production repair: `3501ac32cbec682a77fbc0b79ff51cb33a7adbde`. Its audit source contains all ten paths and its existing ruleset fixture derives directly from `REQUIRED_WORKFLOW_PATHS`.
- The RED commit is a two-parent, non-force reconciliation of PR #1719 and protected `main@b4eec000d21084accb736d289eb64cfd78e7a91a`; concurrent control-plane work is preserved rather than rebased away.

Hosted exact-current-head evidence and independent review remain required before this ADR may become Accepted.

## Consequences and follow-up

A future removal of CodeQL, Scorecard, or OSV from ruleset `18156473` becomes a deterministic governance failure instead of a silent loss of coverage. The rollout document's historical “audit tool coverage” follow-up text must be reconciled with this source repair before merge so the repository has one current statement of policy.

## Update — 2026-09-03: `codeql-pr.yml` removed from the ruleset; the final tuple has nine paths, not ten

The "Decision" and "Test-first evidence" sections above describe this PR's own mid-flight state, when
`codeql-pr.yml` was still expected to be one of the three newly-required code-scanning workflows. Later
the same day, ruleset `18156473` was updated to **remove** `.github/workflows/codeql-pr.yml` from its
required `workflows` list: every ruleset-injected run of that workflow, across all ~71 covered
repositories, concluded `startup_failure` with zero check runs ever created -- `github/codeql-action/init`
and `github/codeql-action/analyze` are categorically disallowed inside a ruleset-required workflow, a
GitHub platform restriction, not a defect in the workflow file's own content. See
`docs/org-required-workflow-rollout.md`'s "Audit tool coverage" section and the 2026-09-03 12:20 KST
evidence entry for the full removal record, and `docs/doctoring/codeql-pr-required-workflow-always-fails.md`
for the platform-restriction root cause.

**The actual, final `REQUIRED_WORKFLOW_PATHS` therefore contains nine paths, not ten** --
`.github/workflows/scorecard-pr.yml` and `.github/workflows/osv-scanner-pr.yml` are included exactly as
decided above, but `.github/workflows/codeql-pr.yml` is deliberately excluded and must stay excluded;
re-adding it to this tuple would silently reintroduce the 100% `startup_failure` regression the removal
fixed. `tests/test_code_scanning_required_workflow_contract.py::test_ruleset_audit_deliberately_excludes_codeql_pr`
is the permanent regression guard for this. Left as an "Update" rather than rewriting the sections above,
so the historical record of what this PR's own RED/GREEN commits contained at each point stays intact.

## References

GitHub. (n.d.). *REST API endpoints for rules*. GitHub Docs. https://docs.github.com/rest/repos/rules

GitHub. (n.d.). *Available rules for rulesets*. GitHub Docs. https://docs.github.com/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets
