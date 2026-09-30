# Review transport continuation dispatch token RCA

Status: Proposed and blocked on `ContextualWisdomLab/noema#735`; no production
authority claim is made by this document.

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

The repository already uses `/exchange_github_app_token` for some
repository-scoped operations, but that does not prove authority for central
dispatch. Retained protected evidence for
`late-life-anxiety-reanalysis@34032cff52e8522db6ea0aad9f68ae0217e86ee3`
shows the exchange at line 141 of
`local/supervisor-audit-20260912/current-ci/103571810868.log` followed by the
central dispatch at line 158 and the same HTTP 403 at line 173 (evidence blob
`cb91b0c0bfe1ff9001cab9e1675d97b00cfcef32`). Thus merely reusing the endpoint
would repeat a known-failing authority pattern.

The consumer adapter in this proposal removes the consumer-token fallback,
keeps consumer `contents` and `pull-requests` access read-only, and fails closed
when exchange credentials are absent or are not a single JSON object containing
a nonempty whitespace-free string. It is not mergeable until Noema issue #735
delivers a versioned least-privilege contract and immutable release that binds
the OIDC identity, exact source revision, explicit central target, and allowed
dispatch action. No PAT or inherited-secret workaround is permitted.

## Test-first evidence

Before the implementation change, executable shell regressions proved that a
numeric OIDC value, object App token, and multiline App token all exited zero;
the multiline value could append another `$GITHUB_OUTPUT` record. The proposed
adapter now reuses the strict single-object/string parsing contract already
exercised by Strix admission. After the parser repair:

- both malformed-response RED tests pass against the actual workflow shells;
- the four affected workflow contract files report `120 passed` with warnings
  fatal;
- both workflow files parse with `yaml.safe_load`;
- the combined warning-fatal suite reports
  `5172 passed, 6 skipped, 40 subtests passed` on Python 3.12.14;
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

Source convergence is not production evidence. First, Noema #735 must publish
an immutable, versioned capability release and this repository must pin that
release. Admission then requires a consumer exact-head capacity failure to show
all of the following on one current head:

1. OIDC exchange succeeds without a repository secret or consumer token
   fallback.
2. The continuation job creates the central `repository_dispatch` event.
3. The central handler preserves repository, PR number, and expected head SHA.
4. The follow-up review produces a fresh exact-head model verdict.
5. Required Checks and independent review are terminal and successful.

No manual status, skipped job, predecessor verdict, or rerun without a cause
change satisfies this acceptance contract.
