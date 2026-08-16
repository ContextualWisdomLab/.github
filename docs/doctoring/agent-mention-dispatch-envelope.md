# Agent-mention repository-dispatch envelope

## Decision

Mention-triggered OpenCode review uses the versioned envelope
`cwl.agent-invocation/v2` with exactly three top-level properties:

```json
{
  "schema": "cwl.agent-invocation/v2",
  "claim": {
    "repository": "ContextualWisdomLab/example",
    "pr_number": 17,
    "head_sha": "<40-hex>",
    "base_sha": "<40-hex>",
    "base_branch": "main",
    "actor": "maintainer",
    "requested_agent": "opencode-agent",
    "source_comment_id": 91,
    "merge_mode": "disabled",
    "trigger_reviews": true,
    "update_branches": false,
    "enable_auto_merge": false,
    "review_dispatch_limit": 1
  },
  "agent_invocation_key": "<sha256-of-canonical-claim>"
}
```

GitHub repository dispatch limits `client_payload` to ten top-level properties
and 65,535 characters. The earlier flat payload used fourteen properties and
was rejected with HTTP 422 before the review scheduler could run. Nesting the
complete immutable claim preserves the invocation and artifact-ledger identity
while keeping the transport within GitHub's contract.

## Trust boundary

The producer, wrapper, and authoritative scheduler independently validate:

- the exact envelope and claim property sets;
- primitive value types and bounded lengths;
- the canonical SHA-256 invocation key;
- the CWL repository allowlist;
- open pull-request state;
- exact live head SHA, base SHA, and base branch;
- review-only policy with branch updates, auto-merge, and merging disabled;
- serialized ledger acquisition before forwarding;
- a distinct event type for the versioned path so it cannot fall through the
  legacy scheduler payload.

The second hop reuses the exact validated three-property envelope. It does not
reconstruct a new flat payload from environment variables. Versioned stale
claims receive a per-invocation concurrency identity and cannot cancel a newer
review request. The legacy `merge-scheduler` path remains explicit for existing
non-mention callers.

A reaction placed on the source comment is only user-interface feedback. A
permission failure after the durable repository dispatch does not invalidate or
repeat the queued review; it is emitted as a warning.

## Test-first evidence

The clean successor PR records a tests-only RED commit before production
changes. Hosted quality evidence on that exact head reports nineteen focused
failures and 1,116 existing passes, including the fourteen-property payload,
missing producer size check, absent wrapper and scheduler validation, missing
quality-gate scope, and reaction-denial propagation.

The regression corpus executes extracted workflow validators, malformed and
policy-violating envelopes, valid and legacy scheduler paths, exact invocation
key binding, downstream idempotency, live-ref authority, and full
statement/branch/docstring quality gates.

## Operational response

When a mention fails to dispatch:

1. inspect the router run before retrying the comment;
2. treat any 4xx dispatch response as a transport or contract defect, not a
   successful review request;
3. do not change the selected pull-request head to manufacture a new request;
4. repair and merge the central router contract first;
5. request a fresh exact-head review after the protected central revision is
   active;
6. never reinterpret predecessor reviews as current-head approval.

## APA 7 references

GitHub. (2026). *Create a repository dispatch event*. GitHub Docs. https://docs.github.com/en/rest/repos/repos#create-a-repository-dispatch-event

GitHub. (2026). *Control the concurrency of workflows and jobs*. GitHub Docs. https://docs.github.com/en/actions/using-jobs/using-concurrency

National Institute of Standards and Technology. (2020). *Security and privacy controls for information systems and organizations* (NIST Special Publication 800-53, Revision 5). https://doi.org/10.6028/NIST.SP.800-53r5
