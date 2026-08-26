# Queue hygiene live-reference race

## Incident

On 2026-08-26, LineageWeave PR #667 received a new same-repository head
`37cc9ab1163f213105d420618e2e8ee69ec6673d`. Its new pull-request workflows
started, but the organization queue sweep cancelled them while GitHub's open-PR
payload still exposed the preceding head. The runs were current for the branch
ref and stale only in the pull-request listing used by the cancellation map.

This was a control-plane defect, not a test failure. Re-running the jobs without
repairing the comparison source would leave the same race available to every
repository in the organization.

## Decision

Queue hygiene still enumerates open pull requests to identify eligible head
repositories and branch names. Before cancelling anything, it now resolves each
head through GitHub's `Get a reference` endpoint and compares active runs with
that live Git reference. A missing, inaccessible, or malformed ref makes the
repository's cancellation pass unavailable; no run is cancelled from partial
evidence.

No time delay or grace-period heuristic is used. A branch ref is the exact
commit pointer the check run is meant to validate. The existing rule remains:
previous-head runs may be cancelled, current-head runs may not.

## Verification

- `uv run --group dev pytest -q tests/test_required_workflow_queue_contract.py`
- `actionlint .github/workflows/pr-review-merge-scheduler.yml`
- `git diff --check`

## Reference

GitHub. (n.d.). *REST API endpoints for Git references*. GitHub Docs. Retrieved
August 26, 2026, from https://docs.github.com/en/rest/git/refs
