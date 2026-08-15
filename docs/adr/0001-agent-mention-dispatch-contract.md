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
10. Strix provider/model tool-contract failures may move to a distinct
    fallback model only when the log contains an exact observed tool name
    (`execute`, `exec_cmd`, or `agent_finish`), the exact
    `ModelBehaviorError` line, and both Strix execution and Agents resolution
    traceback frames. A quoted exception or source-text imitation is not a
    fallback signal. If no fallback produces a complete report, the gate stays
    fail-closed; future tool names require a real traceback and a regression
    test before being admitted.
11. Every `repository_dispatch` body is validated against GitHub's complete
    boundary before network mutation: `event_type` is a non-empty string of at
    most 100 characters, `client_payload` is JSON-serializable, has at most 10
    direct properties, and is strictly below 64 KiB when compactly encoded as
    UTF-8. Noema and OpenCode payload builders use this same validator, so a
    new dispatch producer cannot silently bypass one of the limits.
12. Strix evidence publication captures both the trusted gate status and the
    `tee` log-capture status. Candidate evidence is collected rather than
    accepted at the first matching file; a present `expires_at` must be a
    valid future timestamp, and exactly one eligible completed successful
    `run.json` plus its non-empty report must remain. Legacy run metadata that
    omits `expires_at` remains eligible for backward compatibility, but two
    eligible candidates are always ambiguous and fail closed.
13. The scheduler has a distinct post-merge Strix dispatch path. It validates
    the closed PR's live base repository/ref, original head SHA, `merged_at`,
    and merge-commit SHA, then dispatches immutable metadata. The receiver
    rechecks those fields against the live PR, checks out the merge commit,
    and scans the merged target tree. It does not compare a pre-merge base SHA
    after merge; the open-PR path retains the existing exact base/head binding.
14. Redaction keeps structured JSON valid by applying unstructured scrubbing
    only to JSON string leaves, while non-JSON lines retain the existing
    assignment and operational-identifier scrubber. IPv4 matching is bounded
    to valid octets, and all fail-closed Strix PR-scope error paths emit the
    run-scoped gate marker before exiting. These are behavior contracts with
    focused regressions, not source-text-only assurances.

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
- Fresh request-only reviews for exact current head
  `1676c45b21d1ba96972b503addfbc26d40657cc0` reproduced both pre-merge
  default-branch boundaries: router run `31858797545` failed before dispatch
  with `Invalid request. No more than 10 properties are allowed; 14 were
  supplied. (HTTP 422)`, and the second request `31858798815` reached the
  target mutation boundary and failed with `Resource not accessible by
  integration (HTTP 403)`. Neither run is a review or approval; keep the
  current PR-head fix as untrusted until the normal post-merge default-branch
  router executes and publishes bound evidence. Do not replace this path with
  direct repository dispatch, self-approval, or protection bypass.
- For current head `48973815a48be963f79681d34398d393a679adba`, trusted-base
  Strix run `31858860791`/job `94948463735`/artifact `9240014805` completed
  with zero findings. Its report SHA-256 is
  `063739a6c30bcade1395331fbf289636d317b6f7976e1b712c4a67cb1ea9fbde`,
  `run.json` SHA-256 is
  `e106d7fc0766a4cb38e830e16566812a084f60e663aa432d75527e35bce67916`, and
  gate-console SHA-256 is
  `7474cf177533bd8a7de07078fb20ed131dc7338b4c5d1c9699b5c2fb07f06433`.
  The artifact has no `evidence-binding.json` and its run metadata contains
  only an ephemeral target path, so retain it as provider/content evidence,
  not a clean exact-head security gate.
- The paired default-branch repository-dispatch Strix run
  `31858873824`/job `94948457916` for the same head failed closed after the
  provider emitted `Tool agent_finish not found in agent strix`; no
  vulnerability report artifact was produced. The follow-up status publisher
  also recorded target status mutation `HTTP 403`, but correctly did not turn
  the provider failure into a green status. Treat this as provider/tooling
  infrastructure evidence, retry only after the trusted Strix/provider
  contract is healthy, and never bypass the gate or substitute an unbound
  zero-finding report.
- Request-only review attempts for the later exact head
  `7123bee37a32e05b5e04c9298b01ed0174a4d199` reproduced the same protected
  main bootstrap boundaries: router runs `31859383105` and `31859383242`
  failed with target mutation `HTTP 403` and dispatch payload `HTTP 422`
  (`No more than 10 properties are allowed; 14 were supplied`), respectively.
  They produced no current-head approval or repository-dispatch review; keep
  the failure evidence visible and require the normal post-merge router fix to
  run before treating any review or merge state as complete.
- Provider logs exposed two additional real Strix tool-contract variants that
  the former classifier missed: fast-mlsirm run `31859274416` emitted
  `Tool exec_cmd not found in agent strix`, while central dispatch run
  `31858873824` emitted `Tool agent_finish not found in agent strix`. The gate
  now admits only these observed aliases plus the previously supported
  `execute` form, and only with the complete traceback shape. The focused
  classifier suite passed (`9 passed`), the full central quick gate passed
  with its documented local 1/2-second timeout fixture, and the Python suite
  passed (`983 passed`, 16 subtests).
- The follow-up hardening adds regression coverage for dispatch event and
  payload-size limits, merged-target Strix metadata, tee failure propagation,
  expired/duplicate evidence candidates, bounded IPv4 redaction, valid JSON
  redaction, fail-closed gate markers, and shared test fixtures. The focused
  suite passed after the implementation change (`273 passed`); the final
  working-tree verification passed with `989 passed`, 16 subtests, 100%
  statement/branch coverage, 100% public-docstring coverage, compileall, and
  the full quick gate.

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
