# GitHub API HTTP error response lifecycle

Status: Proposed source repair; exact-head hosted security Checks and independent review remain mandatory.

## Incident and exact owner

Protected `ContextualWisdomLab/.github` `main` at
`37b10243cec3d160ecc9c1be75c71428b160a703` reproduced eight failures in
`tests/test_github_api_url_boundary.py` under Python 3.14.7 with warnings promoted
to errors. Both authenticated GitHub REST clients correctly refused a synthetic
302 without sending a second request, but the resulting `HTTPError` response was
left open and Python reported `ResourceWarning: Implicitly cleaning up
<HTTPError 302: 'Found'>`.

The exact RED command was:

```console
GITHUB_ACTIONS=true python -m pytest tests/test_github_api_url_boundary.py -q -W error
```

Result on the protected revision: `8 failed, 26 passed`. The same result in a
clean protected-revision worktree proves this is a pre-existing central supplier
defect rather than a consumer or `.github#2040` branch-only failure.

## Root cause and repair

Python documents `urllib.error.HTTPError` as both an exception and the same kind
of file-like response returned by `urlopen()`, with a readable error-body file
pointer. The clients converted the exception into their domain error but did not
close that response object. Success responses already used context managers; the
HTTP error path violated the same lifecycle boundary.

The repair keeps the existing fail-closed redirect policy and error mapping:

- `codeql_ghas_configuration_identity._request_json` reads the bounded diagnostic
  body and closes the `HTTPError` in `finally`, including decode/read failures;
- `strix_evidence_binding.default_github_opener` snapshots the status code,
  closes the response, and then raises `EvidenceBindingError`;
- the production-opener regression now asserts that the single synthetic 302
  response is closed as well as proving no redirected bearer request occurs.

No warning filter, security suppression, redirect allowance, timeout, or check
threshold changed.

## Acceptance

1. The protected-revision RED becomes GREEN under Python 3.14.7 and `-W error`.
2. CodeQL identity, Strix evidence, and URL-authority suites remain GREEN with
   `GITHUB_ACTIONS=true`.
3. Both affected production modules retain 100% statement/branch coverage and
   100% public-doc coverage.
4. Hosted Semgrep, Bandit, CodeQL, dependency, and independent review Checks pass
   on the exact PR head before ordinary protected merge.
5. `.github#2040` then merges the protected repair normally and regenerates its
   own exact-head evidence; stale predecessor failures are not rerun as proof.

Local repair evidence on Python 3.14.7 is `34 passed` for the original
URL-authority RED, `219 passed` for the eight-file CodeQL/Strix impact suite,
and `5159 passed, 10 skipped, 40 subtests passed` for the complete test tree.
The two affected modules each report 100% statement/branch coverage, while the
repository-wide report remains at its pre-existing 99% because unrelated
production files outside this delta retain uncovered branches. Hosted exact-head
Checks, rather than this local evidence, remain the merge authority.

## Primary reference

Python Software Foundation. (2026). *urllib.error — Exception classes raised by
urllib.request* (Python 3.14.7 documentation).
https://docs.python.org/3.14/library/urllib.error.html
