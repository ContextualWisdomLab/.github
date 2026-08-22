# OpenCode same-repository status credential

## Operator outcome

An OpenCode repository-dispatch run targeting `ContextualWisdomLab/.github`
publishes its optional `opencode-review` commit status with the current job's
`github.token`. Cross-repository targets continue to use the configured PAT or
OpenCode App installation token, because `github.token` is limited to the
repository containing the workflow.

If status publication fails, inspect the logged token-source label and the
endpoint response. Do not weaken the formal exact-head Reviews API verdict or
branch protection: the commit status is complementary evidence.

## Root cause and decision

Run 32560612401 declared `statuses: write` for the OpenCode job but selected the
separate OpenCode App token for a same-repository status write. GitHub rejected
`POST /repos/ContextualWisdomLab/.github/statuses/{sha}` with HTTP 403 because
that installation token did not carry commit-status write permission.

The smallest repair is credential precedence at the existing publication
boundary. Same-repository publication uses `github.token`, whose effective
permissions are already narrowed by the job. Cross-repository publication
retains the established PAT/App chain and the existing neutral path when only a
repository-scoped workflow token is available. No new credential, permission,
provider, retry, or fallback abstraction is introduced.

This boundary supports SOC 2 and CSAP evidence expectations by preserving
least privilege, explicit credential provenance, exact-head status binding,
and an auditable failure instead of broadening the OpenCode App installation.

## Verification

- The contract test requires both `GH_TOKEN` and its logged source to select
  `github-token` first only when the target equals the workflow repository.
- The existing cross-repository notice and fail-closed exact-head review path
  remain unchanged.
- The complete Python, shell, compilation, docstring, and branch-coverage gates
  remain mandatory before merge.

## APA 7th references

GitHub. (n.d.). *GITHUB_TOKEN*. GitHub Docs. Retrieved August 22, 2026, from
https://docs.github.com/en/actions/concepts/security/github_token

GitHub. (n.d.). *Permissions required for GitHub Apps*. GitHub Docs. Retrieved
August 22, 2026, from
https://docs.github.com/en/rest/authentication/permissions-required-for-github-apps
