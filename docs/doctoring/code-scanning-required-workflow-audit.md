# Code-scanning required-workflow audit repair

## Incident

PR #1719 corrected the rollout record after live organization policy and the repository documentation diverged. The same evidence showed a second owner defect: after ruleset `18156473` gained central CodeQL, Scorecard, and OSV required workflows, `scripts/ci/audit_central_required_workflows.py` still treated only the older seven workflows as authoritative. A future regression of any code-scanning member could therefore escape the scheduled audit.

## Test-first repair

The repair is deliberately split so the behavior change has a genuine RED predecessor.

### RED — `3608fbee43da40d91dadda6afaa8881aacd450c3`

A new executable contract requires these paths to be members of `audit.REQUIRED_WORKFLOW_PATHS`:

- `.github/workflows/codeql-pr.yml`
- `.github/workflows/osv-scanner-pr.yml`
- `.github/workflows/scorecard-pr.yml`

At the same exact commit, the production tuple still contains only the original seven paths. The regression therefore fails for the intended missing-policy reason rather than an environment/setup failure. That commit also reconciles PR #1719 with protected `main@b4eec000d21084accb736d289eb64cfd78e7a91a` using two parents and a non-force ref update.

### GREEN source — `3501ac32cbec682a77fbc0b79ff51cb33a7adbde`

The canonical tuple now contains all ten required workflow paths. The pre-existing ruleset fixture derives its workflow list from that tuple instead of duplicating a stale second policy list; its success count is ten, structural-drift expectations include the three code-scanning workflows, and the rollout contract asserts all three paths are documented.

Focused verification contract:

```bash
PYTHONPATH=. pytest -q \
  tests/test_code_scanning_required_workflow_contract.py \
  tests/test_central_required_workflow_ruleset_audit.py
```

Repository-wide coverage, security, review, and exact-current-head required Checks remain authoritative before merge.

## Runtime meaning

The scheduled central ruleset audit already verifies that every member of `REQUIRED_WORKFLOW_PATHS` exists exactly once and points to repository `1274066402` at `refs/heads/main`. By extending the canonical set rather than introducing a parallel scanner-specific exception, CodeQL, OSV, and Scorecard now receive the same source/ref/uniqueness drift protection as Strix, Noema, OpenCode, Semgrep, Security Scan, and the scheduler.

No workflow source is copied into consumers and no branch/PR head becomes production authority. If live ruleset evidence loses one of these paths, the audit must fail until the organization policy itself is repaired.

## Documentation reconciliation

The rollout record now distinguishes the historical seven-path incident from the current nine-path exact-inventory audit and documents the live repository exclusions `.github`, `noema`, and `IRT-bibliography-set`. This closes the documentation gate without rewriting the incident chronology; ADR-0027 remains Proposed until ordinary protected integration and exact-head evidence complete.

## Update — 2026-09-03: `codeql-pr.yml` removed after the GREEN commit above landed

The RED/GREEN commits described above are an accurate record of what those specific commits contained at
the time: a ten-path canonical tuple including `codeql-pr.yml`. Later the same day, ruleset `18156473` had
`.github/workflows/codeql-pr.yml` removed from its required `workflows` list -- every ruleset-injected run
of that workflow across all ~71 covered repositories concluded `startup_failure` with zero check runs ever
created, a GitHub platform restriction (`github/codeql-action/*` cannot run inside a ruleset-required
workflow), not a defect this audit could have caught or should try to re-require. `REQUIRED_WORKFLOW_PATHS`
was updated accordingly to nine paths -- `scorecard-pr.yml` and `osv-scanner-pr.yml` stay required exactly
as this repair decided, but `codeql-pr.yml` is now deliberately excluded, with
`tests/test_code_scanning_required_workflow_contract.py::test_ruleset_audit_deliberately_excludes_codeql_pr`
as the permanent regression guard against re-adding it. See ADR-0027's own "Update" section and
`docs/org-required-workflow-rollout.md`'s "Audit tool coverage" section for the full current-state record.

## References

GitHub. (n.d.-a). *REST API endpoints for rules*. GitHub Docs. https://docs.github.com/rest/repos/rules

GitHub. (n.d.-b). *Available rules for rulesets*. GitHub Docs. https://docs.github.com/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets
