# Fork-head OpenCode review dispatch

## Decision

An allowlisted ContextualWisdomLab base repository may dispatch an open pull
request whose head repository is a canonical `owner/repository` fork. The fork
is review data, never a trusted workflow source. The central
scheduler and OpenCode workflow continue to re-read the live pull request,
bind the base and head refs and commit SHAs, run protected default-branch
workflow code, update an external head only under the existing
maintainer-writable rule, and exclude external heads from automated merge.

## Root cause

Production scheduler run `32549777222` received an exact request for
`ContextualWisdomLab/contextual-orchestrator#820`, but rejected the open PR
before review because its head repository was a fork. This contradicted the
existing scheduler policy, which already classifies external heads as
reviewable while reserving their merge and update decisions for a maintainer.

## Trust boundary

The smallest repair removes only the false base-equals-head requirement. The
allowlisted base repository must still match the live PR, the head repository
must be a canonical GitHub repository name, and both validation passes must
observe the same exact base/head refs and SHAs. Source is fetched through the
base repository's authenticated PR boundary, materialized at the validated
commits, and handled by the existing credential-scrubbed review sandbox. No
fork workflow is loaded and no new write permission, provider credential, or
mutation or merge authority is granted. This follows GitHub's requirement to treat fork
content as untrusted and the SSDF practice of addressing a root cause without
weakening the surrounding security controls.

## Verification

The executable scheduler regression accepts a canonical fork head while
preserving the exact base branch and head SHA outputs, then rejects a malformed
three-component head repository. Static workflow contracts keep the live base
repository match, exact-head revalidation before OIDC/model work, canonical
head-repository validation, and the absence of the former same-repository
guard.

## APA 7th references

GitHub, Inc. (n.d.-a). *REST API endpoints for pull requests*. GitHub Docs.
Retrieved August 22, 2026, from
https://docs.github.com/en/rest/pulls/pulls

GitHub, Inc. (n.d.-b). *Secure use reference*. GitHub Docs. Retrieved August
22, 2026, from
https://docs.github.com/en/actions/reference/security/secure-use

Souppaya, M., Scarfone, K., & Dodson, D. (2022). *Secure Software Development
Framework (SSDF) version 1.1: Recommendations for mitigating the risk of
software vulnerabilities* (NIST Special Publication 800-218). National
Institute of Standards and Technology. https://doi.org/10.6028/NIST.SP.800-218
