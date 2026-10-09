# Complete GHAS analyses pagination

Status: local source repair on base `37b10243cec3d160ecc9c1be75c71428b160a703`;
protected integration, hosted security checks and independent review remain required.

## Root cause and ownership

`list_codeql_analyses()` returned only the first `per_page=100` response and
ignored `Link`. An identity first encountered on a later page could therefore
be absent from the evidence supplied to the existing base/head pairing rule.
The central standalone helper owns this retrieval defect, not a consumer
repository's CodeQL workflow or lifecycle policy.

The read-only overlap survey collected 383 open central PRs and examined the
exact committed helper source in all 11 file-overlap candidates. Ten retained
the single-request implementation; #2205's head has no helper source.
In particular, #2532's HTTP-error-response closure is separate
work: it is not complete-history pagination and is not implemented here.
No duplicate pagination implementation was found in those candidate heads.

## Contract

- Preserve the public `list_codeql_analyses()` arguments and list return shape,
  the optional ref filter, analysis order, and existing identity pairing policy.
- Follow GitHub's `next` Link only after validating canonical HTTPS
  `api.github.com`, the exact repository analyses path, unchanged decoded
  `ref`/`tool_name`/`per_page`, and the next sequential page number. GitHub's
  numeric `/repositories/<id>/code-scanning/analyses` alias is accepted only
  after an authenticated, redirect-free read of the original owner/name
  repository metadata verifies that exact positive integer ID. Cache this
  binding within one collection; never infer it from an analysis row.
- Reject ambiguous/malformed Link relations, query changes, cycles or skips
  before creating another authenticated request. Continue refusing redirects.
- Collect at most **1000 pages**, each with integer `per_page` in **1..100**.
  Exceeding that resource bound raises an incomplete-evidence error; no prefix
  is returned as complete history.
- HTTP/transport errors, non-list JSON, invalid JSON/UTF-8 and empty HTTP bodies
  abort the entire collection. A valid empty JSON array remains supported.
- Do not retire, filter or rewrite configuration identities; do not upload SARIF,
  synthesize security status, weaken a gate or change lifecycle approval policy.

The transport's `_request_json()` still returns JSON to its original callers;
its optional output-header mapping exposes Link to traversal. Repeated physical
Link fields are combined in response order using `get_all("Link")` before the
existing relation grammar is validated; later next relations cannot be hidden,
and duplicates/malformed fields fail closed before another authenticated request.
Dict-shaped test responses retain their single-value lookup compatibility. Its
pre-existing empty-body behavior remains compatible when that mapping is not
requested.
The module remains stdlib-only and executable as a standalone fetched script.

## Regression and validation

`tests/test_codeql_ghas_analyses_pagination.py` drives the actual opener seam
with synthetic HTTP responses, never live credentials or invented GHAS state.
A three-page, 201-row regression keeps an active identity on page three and
proves it still blocks a head missing that identity. Negative cases exercise
poisoned next targets (with no second bearer request), cycles, malformed Link,
later-page errors and the independent literal 1000-page boundary. Positive
cases cover no ref, PR refs, escaped ref characters, query ordering, single
pages, valid empty arrays and the pre-existing non-dict-row behavior.

Validate the helper and existing authority/credential contracts in normal and
`GITHUB_ACTIONS=true` modes, with 100% statements, branches and docstrings.
Run the dispatch workflow contracts too. On macOS, nine unchanged workflow
fixtures fail because they explicitly invoke `/bin/bash` 3.2 with Bash 4+
`${value,,}` syntax; the same failures reproduce in a clean archive of the
exact base. Do not reinterpret those baseline failures as passing CI.

## Primary references

- [GitHub REST pagination](https://docs.github.com/en/rest/using-the-rest-api/using-pagination-in-the-rest-api)
  specifies following response Link relations rather than assuming one page.
- [List code scanning analyses](https://docs.github.com/en/rest/code-scanning/code-scanning?apiVersion=2022-11-28#list-code-scanning-analyses-for-a-repository)
  documents the paginated analyses endpoint, ref filter and page-size limit.

This API-contract repair adds no new scientific inference or model invocation;
there is no paper PDF to redistribute.
