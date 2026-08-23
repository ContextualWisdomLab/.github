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

## Same-repository credential isolation

Targeted scheduler runs `32556458196` and `32556607016` revalidated
`.github#1210` at the exact current head, then stopped before review dispatch
because their general Actions inventory read used an exhausted organization-wide
OpenCode App installation token. The scheduler already carried the receiving
repository's `github.token`, but selected the App for every targeted dispatch,
including the same repository.

Same-repository `SCHEDULER_ACTIONS_TOKEN` and `SCHEDULER_READ_TOKEN` now use the
job-scoped `github.token`. Cross-repository reads retain the explicit PAT/App
chain, and `GH_TOKEN` retains the existing mutation chain, so this does not
grant the workflow token sibling-repository access or make it authoritative for
branch mutation. This separates the repository-local rate-limit bucket from the
shared App installation bucket and follows GitHub's documented authentication
rate-limit scopes (GitHub, Inc., n.d.-c). The existing
`SCHEDULER_DISPATCH_TOKEN` remains the repository token because GitHub explicitly
permits `repository_dispatch` created with `GITHUB_TOKEN` to start a workflow
(GitHub, Inc., n.d.-d).

The static regression requires both read and Actions-control expressions to
distinguish a same-repository target from a cross-repository target. The full
Python suite, 100% statement/branch/docstring gates, and the CI-budget Strix
shell gate remain authoritative before publication.

Targeted cross-repository run `32566396712` later exposed the remaining host
boundary: while reviewing `contextual-orchestrator#820`, active OpenCode run
discovery queried the central `.github` Actions inventory with the shared App
token and exhausted that installation's quota before dispatch. Active-run
inventory and stale-run cancellation now select credentials by the repository
hosting the run. Central required-workflow runs use the receiving repository's
job token; target-repo run inventory and mutations retain the explicit
cross-repository credential. The regression exercises discovery and
cancellation on both hosts so a later refactor cannot collapse them back onto
one rate-limit bucket.

Targeted scheduler run `32569094917` then exposed a second inventory boundary:
GitHub returned the configured `run-name` in the Actions run `name` field for an
already-running exact-head OpenCode dispatch. Filtering that field as a workflow
alias before checking the trusted exact dispatch title missed run `32569021159`
and created duplicate run `32569106868`, which was cancelled before model work.
Central dispatch inventory now validates the exact repository, PR, and head SHA
encoded in the dispatch title before applying the legacy workflow-name filter.
The regression covers both API shapes so only one exact-head model review runs.

Live retry `32572857921` exposed one remaining pre-dispatch quota consumer. Every
PR inspection unconditionally enumerated queued and running workflows in the
target repository to cancel old-head CI before it examined the centrally hosted
review run. The shared App installation was already rate-limited, so
`contextual-orchestrator#820` stopped on that non-authoritative cleanup read and
never reached exact-head review dispatch. When the required reviewer is hosted
centrally, target-repository old-head jobs do not supply current-head approval or
merge evidence and the central dispatch functions already deduplicate and cancel
their own stale review runs. Centralized inspections therefore skip only that
target old-head inventory/cancellation step. Same-repository schedulers retain it,
and all current-head checks, review identity, target reads needed for live PR
validation, and explicit target mutations remain fail-closed. This removes two
target Actions-list requests per inspected PR without widening any authority.

Exact-head Strix [run 32579981586](https://github.com/ContextualWisdomLab/.github/actions/runs/32579981586)
then reported a HIGH mismatch between the
declared mutation-credential source and the token actually inherited by `gh`.
Its illustrative fallback helper was not present in the scheduler, and the
workflow expressions select `GH_TOKEN` and `SCHEDULER_MUTATION_TOKEN_SOURCE`
from the same precedence chain. The executable boundary nevertheless relied on
that expression-level coupling: a missing token or inconsistent GitHub App
`available` output could select the runner `github.token` while the Python
guard still trusted the stronger source label.

Every scheduler mutation entrypoint now receives the runner token separately
as `SCHEDULER_WORKFLOW_TOKEN`. A head update is authorized only when the source
is allowlisted, the selected `GH_TOKEN` and comparison token are both present,
and the two actual token values differ. Neither value is logged. Tests cover an
empty selected token and a source-label/runner-token mismatch, while the offline
self-test uses distinct synthetic values. Repository-host identity comparisons
also use case-folded canonical names, so a case-only spelling difference cannot
move central Actions inventory onto a shared App credential or skip
same-repository stale-run cleanup. This is a zero-trust verification at the
mutation boundary rather than trust in an upstream environment label (Rose et
al., 2020).

The scheduler also records the credential refusal in each immutable decision
reason and renders later JSON and Actions guidance from that captured evidence.
It does not re-read mutable process credentials while serializing a decision,
so a surrounding test or caller cannot turn a valid wait into a summary-time
exception by changing the environment after inspection.

## Draft merge defense in depth

Exact-head Strix run `32573579932` reported `vuln-0001`, alleging that a draft
pull request could forge successful checks and reach merge without OpenCode
approval. The proposed proof of concept does not traverse the executable
control flow: `inspect_pr` returns `skip: draft PR` before stale-run cleanup,
review interpretation, auto-merge, or direct merge, and an arbitrary author's
review is not an exact-head OpenCode approval. The report also assumed a fork
pull-request token could create base-repository check runs and approvals,
contrary to the least-privilege fork boundary documented by GitHub (GitHub,
Inc., n.d.-b).

The finding is retained as security evidence rather than broadly suppressed.
As defense in depth against a future caller bypassing `inspect_pr`, both guarded
merge mutation functions now reject `isDraft` before actor validation or any
GitHub call. The regression invokes both mutation boundaries with a valid head
SHA and asserts an exception plus zero outbound commands. The existing
top-level draft regression remains, and a new exact-head Strix run must clear
the changed code; no scanner severity, check requirement, workflow identity, or
finding allowlist changed.

## APA 7th references

GitHub, Inc. (n.d.-a). *REST API endpoints for pull requests*. GitHub Docs.
Retrieved August 22, 2026, from
https://docs.github.com/en/rest/pulls/pulls

GitHub, Inc. (n.d.-b). *Secure use reference*. GitHub Docs. Retrieved August
22, 2026, from
https://docs.github.com/en/actions/reference/security/secure-use

GitHub, Inc. (n.d.-c). *Rate limits for the REST API*. GitHub Docs. Retrieved
August 22, 2026, from
https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api

GitHub, Inc. (n.d.-d). *GITHUB_TOKEN*. GitHub Docs. Retrieved August 22, 2026,
from https://docs.github.com/en/actions/concepts/security/github_token

Rose, S., Borchert, O., Mitchell, S., & Connelly, S. (2020). *Zero trust
architecture* (NIST Special Publication 800-207). National Institute of
Standards and Technology. https://doi.org/10.6028/NIST.SP.800-207

Souppaya, M., Scarfone, K., & Dodson, D. (2022). *Secure Software Development
Framework (SSDF) version 1.1: Recommendations for mitigating the risk of
software vulnerabilities* (NIST Special Publication 800-218). National
Institute of Standards and Technology. https://doi.org/10.6028/NIST.SP.800-218
