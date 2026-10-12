# Repository Metadata Reconcile shallow-ancestry RCA

## Status and exact evidence

Status: Proposed on `ContextualWisdomLab/.github#2536`. Exact-head run
[`36720930491`](https://github.com/ContextualWisdomLab/.github/actions/runs/36720930491),
job `109905558240`, checked out
`737fc6fd3b536495a7d5f8bbbae9d0474771d21f` and failed the repository-wide
suite at
`tests/test_github_api_url_boundary.py::test_documented_opener_lineage_references_published_commits`.
The exact assertion reported evidence commit
`57477289ebec5631b0c48f0bc419f336dbe19deb` as an invalid object.

## Root cause

The workflow verified the exact requested revision but left the pinned
`actions/checkout` input `fetch-depth` at its default value of `1`. The G-17
contract intentionally calls `git cat-file` and `git merge-base --is-ancestor`
for published commits named by the product-gap baseline. A depth-one object
database cannot answer that ancestry question after an ordinary merge even
when the evidence commit is genuinely reachable. The earlier local full-history
run therefore did not reproduce the hosted runner's incomplete Git object
database.

This is a workflow-fixture defect, not a product-source defect and not stale
evidence. Exact-head checkout alone and history availability are distinct
contracts.

## RED, repair, and verification

The new workflow regression failed first because the validation checkout did
not contain `fetch-depth: 0`. Commit
`3bc859c73ed67074df13b2e01aa89dff2159e260` adds that single checkout input and
the regression. The focused workflow and ancestry suites then passed 37 tests.
The exact revision assertion and `persist-credentials: false` remain in place;
the apply job's credential and write boundaries are unchanged.

Hosted exact-head revalidation remains required after publication. A queued,
skipped, pending, cancelled, or predecessor result is not passing evidence.

## Reference

actions/checkout contributors. (2026). *Checkout V7: Fetch all history for all
tags and branches* [Computer software documentation]. GitHub.
https://github.com/actions/checkout/blob/main/README.md#fetch-all-history-for-all-tags-and-branches
