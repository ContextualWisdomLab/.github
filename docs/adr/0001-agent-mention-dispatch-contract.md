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

## Evidence

- Failed run `31851199110`: GitHub returned `Invalid request. No more than 10
  properties are allowed; 14 were supplied`.
- Failed run `31851168323`: GitHub returned `Resource not accessible by
  integration` at the optional target reaction boundary.
- Run `31852135609` was cancelled when the next scheduled sweep entered the
  shared router concurrency group, demonstrating why event classes need
  separate queues.
- Local validation after the change: `979 passed`, 16 subtests, 100% statement
  and branch coverage, 100% public-docstring coverage, and
  `test_strix_quick_gate: PASS`.

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
