# Stacked Python and runtime review coverage

Decision date: **2026-09-07**

## Incident

A pull request targeting the feature branch for `ContextualWisdomLab/.github#2002`
created Security Scan, SAST Semgrep, and CodeQL PR runs, but no Python Security
or Agent Review Runtime Quality CI run. Both missing workflows restricted the
`pull_request` base branch, while the existing stacked-PR regression covered
only Security Scan and SAST Semgrep.

## Decision

All four owner review workflows run for every pull-request base ref. Python
Security retains its event-type filter and Runtime Quality retains its path
filter; only the base-branch filters are removed. Push and schedule behavior is
unchanged. The single permanent contract enumerates all four workflow files.

## Failure scenes

- A dependent PR targets a feature branch and edits scheduler Python: Python
  Security and Runtime Quality must both be created.
- A PR does not touch Runtime Quality paths: its existing path filter still
  prevents irrelevant work.
- Closing a Python PR: the existing event/action guards continue to apply.

## Evidence and follow-up

RED commit: `890bac2f69ff1a51f774ddf5d6c5d819afed4ac9`.
Fresh exact-head hosted runs and independent review remain required.

## Reference

GitHub. (2026). *Workflow syntax for GitHub Actions: on.pull_request.branches*.
https://docs.github.com/actions/reference/workflows-and-actions/workflow-syntax
