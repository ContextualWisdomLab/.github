# Review transport continuation dispatch token RCA

Status: Proposed until protected integration and hosted exact-head evidence.

## Incident

The required Strix workflow for
`ContextualWisdomLab/wardnet#134@b1758bb838c7b315cdf4e55064985c3626f52e5e`
correctly classified provider capacity, waited for its bounded continuation,
and then failed to create the continuation event. Run `36387392997`, job
`109439414934`, reported:

```text
gh: Resource not accessible by integration (HTTP 403)
```

The rejected request was `POST
repos/ContextualWisdomLab/.github/dispatches`. The same implementation is used
by Noema; `ContextualWisdomLab/contextual-orchestrator#1221` at
`4dcf9e32b057cde83bca67bfd45975fc6deda458` reached that path after a provider
HTTP 504.

## Root cause and boundary

The continuation jobs ran inside each consumer repository's required-workflow
context. They selected `PR_REVIEW_MERGE_TOKEN` when available and otherwise
used `github.token`. Required-workflow consumers do not receive the central
secret, while their `github.token` is scoped to the consumer repository. That
token cannot create `repository_dispatch` in `ContextualWisdomLab/.github`.
The failure is therefore owned by the central workflow contract, not by either
consumer PR and not by the provider-capacity classification.

The repository already uses one canonical cross-repository credential path:
GitHub OIDC is exchanged at `/exchange_github_app_token` for a short-lived,
repository-scoped OpenCode GitHub App token. The repair reuses that path in
both continuation jobs. It removes the consumer-token fallback, keeps consumer
`contents` and `pull-requests` access read-only, and fails closed if OIDC or the
App token is absent.

## Test-first evidence

Before the implementation change, the two new contract assertions failed
because neither continuation job granted `id-token: write`. After the repair:

- the two RED tests pass;
- the Strix, Noema, and required-runner workflow contracts report `24 passed`;
- both workflow files parse with `yaml.safe_load`;
- `git diff --check` passes.

A broader warning-fatal Strix/Noema suite on protected `main@37b10243` first
exposed nine `HTTPError` response-lifecycle warnings. Stacking the existing
`.github#2532` owner repair removed the Strix warning and proved eight Noema
paths still retained their file-like error response. A new RED assertion bound
the Noema 400 response body to `closed`; the production exception boundary now
extracts bounded allowlisted telemetry and closes the response in `finally`.
The direct redirect-handler test also closes the exception it owns. The exact
stacked review suite is now `586 passed, 2 skipped, 21 subtests passed` with
warnings fatal; no warning was filtered or downgraded.

## Hosted acceptance

Source convergence is not production evidence. Admission requires a consumer
exact-head capacity failure to show all of the following on one current head:

1. OIDC exchange succeeds without a repository secret or consumer token
   fallback.
2. The continuation job creates the central `repository_dispatch` event.
3. The central handler preserves repository, PR number, and expected head SHA.
4. The follow-up review produces a fresh exact-head model verdict.
5. Required Checks and independent review are terminal and successful.

No manual status, skipped job, predecessor verdict, or rerun without a cause
change satisfies this acceptance contract.
