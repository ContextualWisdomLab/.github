# ADR-0001: Bound review-agent dispatch payloads and isolate acknowledgements

- Status: Accepted
- Date: 2026-08-15

## Context

The central review-agent router dispatches trusted pull-request mentions through
GitHub `repository_dispatch`. A live `@opencode-agent` request failed with
HTTP 422 because its `client_payload` contained 14 direct properties, while
GitHub accepts at most 10. A separate Noema request reached the dispatch path
but failed later with HTTP 403 while adding the optional target-repository
reaction. The durable central dispatch had already succeeded in that case.

## Decision

1. The router validates every generated `client_payload` before calling GitHub
   and rejects more than 10 direct properties.
2. The OpenCode wrapper keeps identity and provenance fields at the top level
   and groups review-control flags under `client_payload.control`. Its
   scheduler forward carries exactly the target identity and explicit
   review-only behavior flags; the immutable artifact claim remains the
   source-comment, actor, agent, and invocation-key provenance record.
3. Target reactions and acknowledgement comments are best-effort UX signals.
   Their failures are logged after durable dispatch and do not authorize a
   redispatch. Central dispatch, artifact claiming, and wrapper validation
   remain fail-closed.
4. Review-agent invocations remain review-only: automatic merge, branch
   updates, and direct merge stay disabled.
5. The router's long scheduled organization sweep and immediate local comment
   route use separate concurrency groups, so a five-minute sweep cannot evict
   a pending current-head review request.
6. Evidence publication decodes candidate files as UTF-8 before redaction and
   copies non-text files unchanged. Binding lookup calls have a bounded
   timeout, reuse the result for a run ID, and reject the same traversal and
   absolute-path patterns in both consumers.
7. Redaction preserves JWT and operational-identifier boundaries without
   lookaround expressions. The trusted OpenCode process launcher continues
   after a `setsid` permission failure, and exact structured-status descriptions
   are required before a Strix status can be used as evidence.
8. The default-branch router remains the only dispatch authority. A PR that
   changes that router cannot self-route its own OpenCode review from the PR
   branch; no direct repository-dispatch call, self-approval, or protection
   bypass is permitted. The normal path is to obtain an independent review
   through the configured default-branch service and then re-run the exact-head
   merge gate. Until this PR is merged, the default branch may still contain the
   pre-fix router and must be treated as a bootstrap dependency, not as evidence
   that the PR-head router has executed.
9. Webhook-derived pull-request numbers, comment IDs, and receipt-marker IDs
   require exact built-in integers; Python booleans are rejected even though
   `bool` subclasses `int`. This keeps JSON types, receipt parsing, and
   idempotency keys stable at the trust boundary.

## Evidence

- Failed run `31851199110`: GitHub returned `Invalid request. No more than 10
  properties are allowed; 14 were supplied`.
- Failed run `31851168323`: GitHub returned `Resource not accessible by
  integration` at the optional target reaction boundary.
- Run `31852135609` was cancelled when the next scheduled sweep entered the
  shared router concurrency group, demonstrating why event classes need
  separate queues.
- Local validation after the follow-up: `981 passed`, 16 subtests, 100%
  statement and branch coverage, 100% public-docstring coverage, and
  `test_strix_quick_gate: PASS` with the timeout fixture shortened to 1/2s
  locally (the production contract remains bounded and unchanged).
- CodeRabbit's exact-head review of `320e999714849740d2b497e7c717d5c1384bd9af`
  identified eight unresolved threads covering binary redaction, bounded
  Strix binding lookup/cache, report-path parity, JWT boundaries, operational
  marker coverage, `setsid` handling, and lookaround detection. The follow-up
  changes address those findings; the full suite, coverage, docstring gate,
  and quick gate passed before the follow-up commit.
- A subsequent exact-head review of `6c0316b46fc54da64c8bf239ea592fbb742cef6f`
  correctly identified that the initial `setsid` regression only inspected
  source text. The test now runs the extracted launcher in an isolated
  `sitecustomize` harness, forces `os.setsid()` to raise `PermissionError`, and
  records the continuing `os.execvpe("timeout", ...)` call plus credential
  removal. The focused runner suite passed (`30 passed`), and the full suite
  remained `981 passed` with 100% statement/branch coverage and 100%
  public-docstring coverage.
- Fresh exact-head review request `@opencode-agent review` on
  `25b619fc65112b1d41e28a528f5d26529e9c80cd` reproduced the bootstrap boundary
  before the PR fix was active: workflow run `31856400747` executed the
  default-branch `agent_mention_router.py` and failed with
  `gh: Invalid request. No more than 10 properties are allowed; 14 were
  supplied. (HTTP 422)`. No repository dispatch was created, so this run is
  evidence of the pre-merge default-branch defect only; it is not a review or
  approval of the PR head. After merge, the canonical review request must be
  repeated and bound to the exact PR head.
- A second fresh request for the same exact head, `31856496239`, reached the
  default-branch router's target-repository mutation and failed with
  `Resource not accessible by integration (HTTP 403)`. This confirms the
  target-reaction/acknowledgement boundary is independently permission-limited;
  it must remain best-effort after durable central dispatch and must never be
  interpreted as a successful review or merge authorization.
- Central exact-head Strix run `31856556623`, job `94942344498`, artifact
  `9239425223`, found a real MEDIUM type-confusion issue in
  `agent_mention_router.py`: `isinstance(value, int)` accepted JSON booleans
  for PR/comment IDs and could emit unparseable `True`/`False` receipt markers.
  The report digest was
  `8c03038e7defe06249107db995515770eb6a2232d15ada30baf9c04244538fac`, and
  the gate-console digest was
  `39ffcc3c7a47efdae294d496930b11040079f4c610928c3686f3dc2791fbed35`.
  The source-backed fix changes the trust-boundary and receipt checks to exact
  integer validation and adds boolean regressions; the predecessor terminal
  failure remains a real finding until a fresh exact-head Strix run verifies
  the fix.
- Fresh central Strix run `31857507595`, job `94944941166`, artifact
  `9239605933`, completed successfully with a zero-finding security report
  (report SHA-256
  `0f82cd4c71969d1882e15898fbfa995d5694d6e145ee799c2cbe74dae11588c5`,
  `run.json` SHA-256
  `f7d894edb9ce44fa91e40406f58b9664803ac6bb12df413ec708c7251448499e`,
  gate-console SHA-256
  `3787da4c7a08966a6e3e6c6727b10af32075ada2fee144b449e4ea3556ba83bc`).
  The report suggested a `redact_sensitive_log.py` deduplication bug using
  `comment.get("login")`, but exact-source inspection found no such expression
  (the cited line is a function boundary and `agent_mention_router.py` already
  reads `user.get("login")`). This is a provider/content false positive, not a
  source fix to apply. The artifact still had no `evidence-binding.json`
  because the `pull_request_target` run used the protected base workflow, so
  the result remains non-clean until the post-merge default-branch structured
  binding run succeeds.

## Consequences

The API contract is checked before network mutation, and a target-token
permission problem cannot turn completed dispatch into retry noise. Provenance
is retained in the exact-name artifact ledger rather than duplicated in the
downstream scheduler envelope. Operators must inspect the durable ledger and
authoritative review workflow for dispatch state; target comments and reactions
are not evidence.

## References

- [GitHub REST API: Create a repository dispatch event](https://docs.github.com/en/rest/repos/repos#create-a-repository-dispatch-event)
- [GitHub REST API: Create reaction for an issue comment](https://docs.github.com/en/rest/reactions/reactions#create-a-reaction-for-an-issue-comment)
