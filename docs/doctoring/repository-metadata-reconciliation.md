# Repository metadata reconciliation

The organization keeps repository-facing description, topics, DeepWiki intent, and
GitHub Pages intent in `config/repository-metadata.json`. The reconciler audits live
GitHub REST state first and applies only the minimal drift.

Apply mode is deliberately separate from ordinary workflow `GITHUB_TOKEN` authority.
GitHub's repository-update and topic endpoints require repository Administration
write permission; creating GitHub Pages additionally requires Pages write permission
and Administration write permission. The workflow therefore accepts only the
dedicated `CWL_REPOSITORY_METADATA_TOKEN` secret for apply mode and fails closed when
it is absent. Do not substitute a review/model credential or broaden `github.token`.

The first managed repositories are `CalendarWeave` and `ConceptWeave`, where live
metadata showed empty topics and, for CalendarWeave, customer-facing internal
instructions in the repository description. Their active foundation PRs already own
the canonical Ask DeepWiki badge and product documentation, so the central manifest
does not create competing README writers.

Pages remains disabled in desired state until a publishable static source is on the
protected default branch. When enabled, the reconciler admits only `/` or `/docs` and
uses GitHub's Pages settings API. A source commit or workflow definition is not
publication evidence; operators must re-read the live Pages endpoint after apply.

## Verification

The focused contract is `tests/test_repository_metadata_reconciler.py`. It covers
manifest casing and bounds, customer-facing description constraints, normalized
repository topics, exact DeepWiki URL formation, minimal repository/topic/Page
operations, GitHub REST failure handling, apply-mode credential refusal, and CLI
execution. The new Python module is expected to retain 100% statement and branch
coverage under the repository coverage gate.

## Primary references

GitHub. (2026). *REST API endpoints for repositories*. GitHub Docs.
https://docs.github.com/en/rest/repos/repos

GitHub. (2026). *REST API endpoints for GitHub Pages*. GitHub Docs.
https://docs.github.com/en/rest/pages/pages
