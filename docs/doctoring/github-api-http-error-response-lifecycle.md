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

The repair keeps the existing fail-closed redirect policy and error mapping.
The first exact-tree verification also exposed the same lifecycle defect in
other central HTTP boundaries, so the owner repair now covers every observed
path rather than leaving warning-fatal failures for a successor:

- `codeql_ghas_configuration_identity._request_json` reads at most 400 bytes of
  diagnostic body and closes the `HTTPError` in `finally`, including decode/read
  failures;
- `strix_evidence_binding.default_github_opener` snapshots the status code,
  closes the response, and then raises `EvidenceBindingError`;
- `noema_review_gate.call_llm` extracts only bounded allowlisted gateway
  telemetry and then closes the response in `finally`;
- the Pingora artifact client closes JSON and raw-blob HTTP errors after
  preserving its existing 404/domain-error mapping;
- the review preflight closes provider HTTP errors after recording only the
  safe status and retry fields;
- Pages publication and sandbox readiness probes close rejected redirects
  before returning their existing fail-closed result;
- the production-opener regression now asserts that the single synthetic 302
  response is closed as well as proving no redirected bearer request occurs,
  and each newly discovered caller has an equivalent close contract.

The 400-byte intake bound matches the pre-existing 400-character public
diagnostic limit without reading an arbitrarily large untrusted response first.
No warning filter, security suppression, redirect allowance, timeout, or check
threshold changed.

## Acceptance

1. The protected-revision RED becomes GREEN under Python 3.14.7 and `-W error`.
2. CodeQL identity, Strix evidence, Noema, Pingora, review-preflight, Pages,
   sandbox readiness, and URL-authority suites remain GREEN with warnings
   fatal.
3. Changed production behavior retains contract coverage and public docs.
4. Hosted Semgrep, Bandit, CodeQL, dependency, and independent review Checks pass
   on the exact PR head before ordinary protected merge.
5. `.github#2040` then merges the protected repair normally and regenerates its
   own exact-head evidence; stale predecessor failures are not rerun as proof.

Local repair evidence on Python 3.14.7 is `35 passed` for the URL-authority
suite after adding the bounded-intake regression (`1 failed` before the repair),
`220 passed` for the original eight-file CodeQL/Strix impact suite, `69 passed`
for the sandbox E2E suite, and `5161 passed, 10 skipped, 40 subtests passed`
for the complete warning-fatal test tree. The original two production modules
each report 100% statement/branch coverage, while the repository-wide report
remains at its pre-existing 99% because unrelated production files outside this
delta retain uncovered branches. Hosted exact-head Checks, rather than this
local evidence, remain the merge authority.

## Primary reference

Python Software Foundation. (2026). *urllib.error — Exception classes raised by
urllib.request* (Python 3.14.7 documentation).
https://docs.python.org/3.14/library/urllib.error.html
