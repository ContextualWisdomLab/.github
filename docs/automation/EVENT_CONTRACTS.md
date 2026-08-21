# Event, payload, and result contracts

Status: active_pr documentation baseline
Last reviewed: 2026-08-09
Scope: central automation envelopes crossing workflow, repository, sandbox, and scheduler boundaries

## 1. Purpose

This document defines versioning, identity, strict parsing, replay, compatibility, and migration rules for central control-plane messages. It does **not** make an unversioned protected-main payload versioned by documentation alone. A runtime schema is `implemented_on_protected_main` only after the producing and consuming code, negative compatibility tests, review, protected merge, and required operational acceptance exist.

GitHub event envelopes remain platform-owned. The schemas below cover the CWL-owned fields placed in GitHub workflow inputs, `repository_dispatch.client_payload`, bounded result JSON, and idempotency receipts.

## 2. Global envelope invariants

Every mutation-capable or review-routing message MUST satisfy all applicable invariants before a credential with broader authority than metadata read is materialized:

1. `target_repository` is an exact allowlisted `ContextualWisdomLab/<repository>` identity, never a prefix/glob chosen by model output.
2. `pull_request_number` is a positive integer and is re-read from live GitHub state.
3. `source_head_sha` is an exact 40-hex source revision and equals the live open PR head at the consumer boundary.
4. `pr_base_snapshot_sha` records the base SHA supplied/observed with the PR/event for provenance only.
5. `live_base_tip_sha` is independently resolved from the current target base ref when the decision depends on the current protected base.
6. `base_branch` and source repository/ref are revalidated rather than inferred from an earlier event.
7. actor/sender/installation identity is authenticated through the event/provider boundary and compared with the configured policy.
8. unknown keys, duplicate JSON keys, wrong types, ambiguous null/empty values, unsupported schema versions, oversized payloads, and identity mismatch fail closed.
9. CWL payloads never carry credential values, raw model prompts, unrestricted logs, or business payloads merely for convenience.
10. idempotency identity binds every field whose change could alter authority or side effects.

A CWL envelope cannot promote a check, status, model result, or comment into a formal human review. Authority class is preserved outside the payload schema.

## 3. Version lifecycle

| State | Meaning | Consumer behavior |
|---|---|---|
| `legacy_implicit_v1` | Protected-main path has no explicit schema field but has a bounded parser/contract. | Continue only where required for compatibility; do not extend with new optional authority fields. |
| `active_pr` | Explicit schema exists only on an open PR. | Never advertise as protected-main support; predecessor consumers reject it unless the PR intentionally contains a dual-parser migration. |
| `implemented_on_protected_main` | Producer and consumer are merged, machine/review gates passed, and protected-source identity is observable. | Accept exact documented version; retain rollback/migration path as specified. |
| `superseded` | A newer version replaced this version after a reviewed migration window. | Reject new production use; retain only bounded historical decoding if incident/replay evidence requires it. |

A major schema change is any change to required fields, field meaning, authority, idempotency identity, rejection semantics, maximum sizes, or side effects. Major changes require a new schema identifier and ADR/traceability update. Additive fields are not automatically backward-compatible: the receiving strict parser decides whether they are allowed.

## 4. Review-agent invocation envelope

### 4.1 Version 2 — `cwl.agent-invocation/v2`

Maturity: `active_pr` while the complete envelope work remains unmerged.

The intended canonical CWL payload has exactly:

```json
{
  "schema": "cwl.agent-invocation/v2",
  "claim": {
    "repository": "ContextualWisdomLab/example",
    "pr_number": 17,
    "head_sha": "<40 hex>",
    "base_sha": "<40 hex PR snapshot base>",
    "base_branch": "main",
    "agent": "opencode-agent",
    "comment_id": 123456,
    "actor": "trusted-maintainer",
    "trigger_reviews": true,
    "review_dispatch_limit": "1",
    "enable_auto_merge": false,
    "update_branches": false,
    "merge_mode": "disabled"
  },
  "agent_invocation_key": "<sha256 canonical claim>"
}
```

For Noema, policy-specific fields not used by that transport remain governed by its own strict wrapper contract; a consumer may not reinterpret an OpenCode policy field as Noema authority.

The outer `client_payload` must stay within GitHub's repository-dispatch constraints and the consumer enforces a stricter exact-key/type/cardinality contract before forwarding. The SHA-256 invocation key is an idempotency/fencing identity, not a credential or approval.

### 4.2 Legacy mention path

Maturity: `implemented_on_protected_main` for the currently protected router/wrapper shapes that predate complete v2 dispatch binding.

Legacy schema-free fields remain compatibility evidence only. They must not silently accept an object claiming `cwl.agent-invocation/v2`, nor may new authority-bearing fields be added to the legacy path. Migration closes only when the protected producer and every authoritative downstream consumer use the explicit version or the legacy path is intentionally retained with a separately documented reason.

## 5. Merge-scheduler review-only dispatch

### 5.1 `merge-scheduler-agent-review-v2`

Maturity: `active_pr` when supplied through the versioned review-agent envelope.

Normative properties:

- review-only: no branch update, auto-merge, direct merge, release, or deployment;
- exact source repository/PR/head/base/base-branch identity bound to the upstream invocation claim;
- two fresh live PR snapshot checks before the mutation-free review decision;
- a different-head active run may suppress duplicate/stale dispatch but cannot validate old evidence;
- receiver concurrency isolation may serialize/idempotently suppress the same invocation but may not cancel a newer valid exact-head request because an older event arrived late.

### 5.2 Legacy merge-scheduler dispatch

Maturity: `legacy_implicit_v1`.

Schema-free scheduler requests remain an explicit compatibility path. They cannot accept the v2 canonical claim by duck typing. Any migration that removes the legacy path must prove every current producer moved first and must retain rollback for at least one protected release interval unless an incident requires immediate fail-closed removal.

## 6. Merge scheduler result receipt

### `pr-review-merge-scheduler/v2`

Maturity: `implemented_on_protected_main` where the current scheduler emits this versioned bounded result.

The receipt records deterministic scheduler observation/decision evidence. At minimum consumers bind:

- schema/version;
- target repository and PR;
- exact expected source head;
- observed base/merge state relevant to the decision;
- decision/action and finite reason code;
- action error separately from ordinary wait/block/defer policy states; and
- attempt/run identity where needed to distinguish retries.

A result receipt is not formal review evidence and does not prove a mutation succeeded unless the GitHub mutation response and subsequent live state confirm it. A future change to terminal workflow policy for `action_error` must version or explicitly preserve the receipt semantics rather than overload `success`.

## 7. Sandbox result envelopes

### 7.1 `SANDBOXED_VERIFY_RESULT`

Maturity: `implemented_on_protected_main`; redaction improvements may be `active_pr` independently.

The bounded JSON result preserves stable fields including `exit_code`, `elapsed_seconds`, `allowed_env`, and `evidence_note` as defined in [TRD.md](TRD.md). Child process stdout/stderr is diagnostic input, not schema authority. A parse/setup failure uses the documented stable exit/result failure semantics and never publishes unsafely parsed raw evidence.

### 7.2 `SANDBOXED_WEB_E2E_RESULT`

Maturity: `implemented_on_protected_main`; redaction/resource-bound improvements may be `active_pr` independently.

The envelope retains stable stage/exit/timing/evidence metadata while backend/frontend logs are separately bounded and redacted. Result JSON must remain valid after redaction; credentials or arbitrary source text are not added as structured fields.

Breaking field/type/exit-code changes require an explicit new result schema/version and migration tests.

## 8. Reusable-workflow contract versioning

Reusable workflows are APIs even when their YAML path is stable.

- Required inputs and secrets form the public interface.
- A caller pinned to an immutable commit receives exactly that reviewed contract.
- Removing/renaming an input or secret, broadening `secrets: inherit`, changing mutation authority, or changing trigger/source identity is a breaking interface change.
- New credentials require explicit purpose and job scope before they are callable.
- A reusable workflow's internal job name may be externally significant when branch/ruleset/check policy relies on it; such names are tracked in TRD/Traceability rather than renamed casually.

The planned `deploy-pages.yml` explicit Cloudflare-secret migration is a contract hardening of an older implicit inheritance interface. It is tracked separately and must be implemented test-first; this document does not make that planned runtime change effective.

## 9. Size, strictness, and GitHub platform bounds

CWL producers MUST validate their stricter schema and bounded string/list sizes before invoking GitHub. They MUST also remain below the platform's repository-dispatch top-level-property and payload-size limits documented by GitHub. A message that would exceed either bound is rejected before dispatch; truncating identity/security fields is forbidden.

Where a payload includes model-generated or source-derived display evidence, the system passes an identifier/digest or a separately bounded artifact rather than expanding the authority envelope.

## 10. Replay and idempotency

- Redelivery of an identical GitHub event may be processed multiple times at the transport layer but must not create duplicate mutation/review authority.
- `invocation_claim`/artifact-ledger identity is exact and stateful; a completed exact request does not forward twice.
- Failed-before-forward recoverability is a separate reliability contract and must not be achieved by weakening the completed-request idempotency key.
- Head/base/actor/comment/policy movement produces a distinct claim or fails live comparison; it never reuses the old completed claim as current authority.
- Rerunning a workflow creates a new run/attempt identity while the exact source/review claim may remain the same. Consumers distinguish retry transport identity from business/idempotency identity.

## 11. Compatibility and rollback matrix

| Change | Migration rule | Rollback rule |
|---|---|---|
| Add explicit version to legacy payload | Dual parser only if producers/consumers cannot move atomically; versioned object must never be accepted as legacy. | Revert producer first or keep dual consumer until all callers are restored. |
| Remove legacy payload | Prove zero live callers through code search + protected consumer evidence. | Restore immutable prior consumer/source and rerun negative/positive canaries. |
| Change required field/type | New schema identifier. | Keep prior parser only for the documented compatibility window. |
| Change idempotency key inputs | New schema/claim version and collision/replay tests. | Do not reinterpret old artifacts under the new key definition. |
| Change reviewer/mutation authority | ADR + security/threat/ruleset review; not a schema-only edit. | Restore previous authority contract; never synthesize missing approvals. |
| Change reusable secret contract | Explicit caller inventory and migration; no blanket inheritance fallback. | Revert callers and called workflow to the same immutable compatible pair. |

## 12. Negative contract tests

Every versioned message family needs tests for:

- missing/extra/duplicate keys;
- wrong scalar/container types and null/empty ambiguity;
- unsupported/newer/older schema values;
- malformed repository/ref/SHA/PR/actor identifiers;
- source-head and live-base movement;
- stale, replayed, duplicate, and out-of-order events;
- payload size/cardinality limits;
- cross-repository confused deputy attempts;
- untrusted model/source text pretending to be schema control fields;
- credential-shaped content rejection/redaction at publication boundaries; and
- legacy/versioned parser non-conflation.

## 13. Traceability and supersession

Runtime schemas are linked from [TRACEABILITY.md](TRACEABILITY.md) to their producers, consumers, tests, maturity state, and protected acceptance receipts. If code and this document disagree, current live source is the observation authority and the mismatch is a documentation or implementation defect—not permission to guess which behavior was intended.

A schema is superseded only after producers, consumers, negative compatibility tests, operator runbook, rollback, and protected-main/consumer acceptance have moved to the successor. Historical payload examples remain non-authorizing evidence.