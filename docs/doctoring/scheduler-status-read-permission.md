# Scheduler commit-status read permission (#2120)

The organization-required scheduler selected `github.token` for same-repository
reads but omitted `statuses` from `scan-pr-queue.permissions`. The private
consumer's combined-status GET consequently failed with HTTP 403 before a merge
verdict. `checks: read` does not grant classic commit-status access.

Source baseline: `fb17ef556f94f673234aa557254ae52779e9a7b0`.
Consumer evidence: ContextualWisdomLab/late-life-anxiety-reanalysis#10,
head `3d1e3ae56e3ef6ca0a995b6082c4f4a13629e0f6`, run `34698738407`,
job `103566634488` (2026-09-12). The reported failing endpoint is
`GET /repos/{repository}/commits/{head}/status`.

The repair adds only `statuses: read` to the existing scan job. Workflow defaults,
mutation credentials, cross-repository credential selection and fail-closed API
errors remain intact. It adds no status publication or App installation grant.
The existing credential-contract test now requires exactly `read` in that job's
permission block; its RED revision is `9521b6771`.

Validation uses the existing pytest workflow/credential/status suites and
Actionlint's workflow validation. Local tests prove the declared contract, not a
hosted permission grant. After protected integration, validate a newly loaded
central source SHA and the consumer's exact current head: the combined-status
request must succeed, and missing checks or substantive failures must still block
merge. For reusable callers, every caller permission ceiling must also admit
status reads; the inspected consumer PR head has no `.github` tree, so do not
invent a repository-local caller or modify App permissions to compensate.

Next integration review: 2026-09-13, because this prevents the current private
consumer's mandatory scheduler from evaluating status evidence. #2116's HWPX
classification remains a separate bootstrap repair. Reverting this one-line grant
restores the pre-existing 403 behavior; it is not a viable consumer repair.

## Reference

GitHub. (n.d.). *REST API endpoints for commit statuses: Get the combined status
for a specific reference*. Retrieved September 12, 2026, from
https://docs.github.com/en/rest/commits/statuses#get-the-combined-status-for-a-specific-reference
