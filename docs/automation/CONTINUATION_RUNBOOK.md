# Autonomous continuation runbook

Status: active_pr operability companion
Last reviewed: 2026-08-10
Scope: work-conserving queue rotation, wait/defer semantics, user-redirection recovery, real run-budget exhaustion, and observable termination evidence

This runbook operationalizes ADR-0007, [AUTONOMY_THREATS.md](AUTONOMY_THREATS.md), and the logical `continuation_handoff` model. It does not replace workflow-specific timeouts or GitHub rulesets.

## 1. Operator rule

A blocked or waiting item is **local state**, not run completion. The automation defers the exact identity and selects another safe lane. Hourly recurrence means continuation after a genuine practical run/tool limit, not “stop after about an hour.” Prompt or documentation maintenance is control-plane preparation and cannot be the final voluntary action while safe repository work exists.

## 2. Observable lane states and reason codes

| Reason code | Meaning | Allowed action | Run terminal? |
|---|---|---|---|
| `EXECUTABLE_NOW` | Safe mutation/test/merge/operational action exists and writer lease is available. | Execute highest-value item. | No |
| `USER_REDIRECTION_INCIDENT` | User reports that a prior invocation stopped while executable work remained. | Reconstruct missed terminal condition, rebuild whole queue, perform same-invocation substantive recovery, then restart exit sweeps. | No |
| `WAIT_CHECK_PENDING` | Exact-head required check is queued/in-progress. | Defer exact PR/head/check identity; rotate. | No |
| `WAIT_REVIEW_PENDING` | Current-head automated or human review is pending. | Defer exact PR/head/reviewer identity; rotate. | No |
| `WAIT_EXTERNAL_APPROVAL` | Qualifying independent human approval is the local remaining gate. | Preserve expected-head-safe merge posture if policy allows; rotate. | No |
| `WAIT_PROVIDER_COOLDOWN` | Provider/reviewer is rate-limited/unavailable. | Record bounded provider identity/time; rotate. | No |
| `WAIT_DEPENDENCY` | Another PR/release/protected-main change is an exact prerequisite. | Bind dependency identity; rotate to disjoint work. | No |
| `WAIT_WRITER_LEASE` | Another write-capable actor owns the exact branch/head. | Freeze only that branch; do not race. | No |
| `BLOCK_POLICY` | Live ruleset/permission/security policy forbids proposed action. | RCA; execute a feasible policy/source remedy if authorized, otherwise defer exact external prerequisite. | No by itself |
| `BLOCK_SOURCE_DEFECT` | Current-head source/test/security defect is proven. | Test-first repair or hand to the active exact-branch writer. | No |
| `BLOCK_INFRA_PERMANENT` | Auth/integrity/TLS/ref/schema/policy failure is fail-closed. | Do not retry as transient; repair root cause or defer external owner. | No |
| `RETRY_INFRA_TRANSIENT` | Bounded evidence class such as reset/DNS/5xx/capacity is eligible for limited retry. | Retry within component budget, then defer/rotate. | No |
| `META_INTERMEDIATE` | Prompt/doc/status/comment/review request/dispatch/Draft/Ready/auto-merge/commit/merge/document completion occurred. | Re-scan executable queue immediately. | No |
| `SWEEP1_EMPTY` | First fresh whole-queue sweep found no executable lane. | Perform second fresh sweep from new live reads. | No |
| `SWEEP2_EMPTY` | Second fresh whole-queue sweep independently found no executable lane. | Termination is permitted if no real budget/error boundary requires a handoff. | Yes |
| `RUN_BUDGET_EXHAUSTED` | External execution/tool boundary prevents further safe calls in this finite invocation. | Emit exact continuation handoff; next recurrence resumes. | Yes, as continuation—not completion |
| `SAFETY_BOUNDARY` | Policy/safety tool denies further operation across all applicable lanes. | Preserve evidence and stop; user/operator escalation only if needed. | Yes |

“Elapsed time exceeds N minutes” is intentionally absent. Component timeouts may have explicit finite budgets, but the outer maintenance run cannot invent a soft elapsed-time terminal reason.

## 3. Defer key

A deferred item must be precise enough not to suppress unrelated work:

```json
{
  "repository": "ContextualWisdomLab/.github",
  "work_kind": "pull_request_check",
  "pull_request_number": 123,
  "source_head_sha": "<40 hex>",
  "live_base_tip_sha": "<40 hex when material>",
  "external_identity": "workflow/check/reviewer/dependency identity",
  "reason_code": "WAIT_CHECK_PENDING",
  "observed_at": "<RFC 3339>"
}
```

Do not defer an entire repository merely because one branch or provider item waits. A changed head/base/external identity invalidates the old defer key and requires a fresh observation.

## 4. Continuation handoff receipt

Only `RUN_BUDGET_EXHAUSTED` needs a `continuation_handoff` when executable work remains. The bounded receipt contains identifiers and next actions, not raw logs or credentials.

```json
{
  "schema": "cwl.automation-continuation/v1",
  "run_identity": "<bounded invocation identity>",
  "reason_code": "RUN_BUDGET_EXHAUSTED",
  "recorded_at": "<RFC 3339>",
  "deferred_items": [
    {
      "repository": "ContextualWisdomLab/.github",
      "pull_request_number": 123,
      "source_head_sha": "<40 hex>",
      "reason_code": "WAIT_REVIEW_PENDING",
      "external_identity": "<review identity>"
    }
  ],
  "next_executable_lanes": [
    "re-fetch exact PR heads/live bases and resume highest-value executable work"
  ]
}
```

The receipt is not persisted in a new database by this document. A GitHub artifact, automation task state, or other existing bounded continuation store may represent it. Persistence changes require the data-model ADR gate.

Use this sink and acknowledgement order:

1. Persist the exact JSON in an existing bounded automation task-state or run-artifact field when the execution platform exposes one.
2. If no durable structured field is available, emit the receipt as the **sole** terminal user-visible output and label it `NON_CLEAN_CONTINUATION`; it is not `SWEEP2_EMPTY` or completion.
3. Do not create a database, credential, branch, workflow, or GitHub issue solely as a handoff store without the data-model ADR gate.
4. The next recurrence loads the most recent available receipt, acknowledges its `run_identity`, re-fetches every recorded head/base/external identity, discards stale defer keys, and resumes queue selection.
5. If the receipt is missing or unreadable, perform a full fresh sweep. Missing handoff state never authorizes a clean exit.

## 5. User-redirection recovery

A user statement such as “work remained,” “why did you stop,” or an equivalent request to repair the prompt is direct evidence that the previous exit proof failed. Classify `USER_REDIRECTION_INCIDENT` and recover in the **same invocation**.

Use this order:

1. Reconstruct the last voluntary terminal condition from available evidence. Identify at least one missed safe lane; do not substitute a generic apology or status recap.
2. Refetch the full live queue, protected main, exact PR heads, independently resolved live base tips, current writer leases, reviews/checks/security evidence, canonical documentation, and protected-main acceptance debt.
3. Repair the scheduler prompt or canonical documentation only when the incident exposes an actual control-contract gap. Prompt editing, inventory, RCA prose, documentation assessment/mutation, one commit/PR/check/review request/merge/blocker, or one product slice receives **zero completion credit** by itself.
4. Resume substantive repository execution immediately. If **at least two materially distinct** independent safe execute-now lanes exist, advance at least two before termination is eligible. At least one recovery action must be **non-documentation** whenever a safe non-documentation lane exists. A documentation action may satisfy at most one lane.
5. If fresh evidence proves only one execute-now lane exists, execute it and then perform **two fresh whole-queue sweeps** from new live reads to prove no second lane is executable.
6. Reset the exit-sweep count after every recovery action. A final response that knowingly leaves an `EXECUTABLE_NOW` lane is another `USER_REDIRECTION_INCIDENT`.

The action-count rule never changes authority. Two unsafe writes, two actions on the same waiting identity, duplicate review requests, or a raced writer do not satisfy recovery. Distinct actions must each be independently safe and materially advance repository state or exact acceptance evidence.

## 6. Double exit sweep

### Sweep 1

Freshly enumerate:

- every open PR and exact current head;
- independently resolved live base tips where material;
- open issues and dependencies;
- required checks/statuses/reviews/threads/security evidence;
- active writers and branch-local leases;
- protected-main/consumer acceptance still owed by merged repairs;
- canonical documentation versus live implementation;
- tests/coverage/docstrings/security/supply-chain/release debt; and
- one bounded buyer/control-plane gap if existing work is non-actionable.

If any safe action exists, classify `EXECUTABLE_NOW`, execute it, and the exit sequence resets.

### Sweep 2

Only after `SWEEP1_EMPTY`, perform the same inventory from **new live reads**. Do not reuse cached PR/check/reviewer state as proof. If still empty, `SWEEP2_EMPTY` permits termination.

A queued check or external approval on one PR does not make the sweep empty if any other safe lane exists. After `USER_REDIRECTION_INCIDENT`, the two fresh sweeps begin only after the required same-invocation recovery work has been performed.

## 7. Retry and timeout interaction

Workflow/component timeouts remain bounded and are separate from maintenance-run termination.

- provider attempt timeout → classify provider result and continue/fallback/defer according to provider policy;
- network/bootstrap transient retry → bounded retry count/time and then rotate;
- integrity/auth/TLS/ref/schema failure → immediate permanent/fail-closed class, no transient retry;
- long OpenCode/Noema/Strix job → defer exact run identity and continue other work;
- GitHub Actions queue saturation → do not poll; advance source/docs/issues that do not conflict.

## 8. Split authority operational check

Before merge, mutation, or protected incident closure, operator evidence must answer separately:

- Which exact source head was evaluated?
- What PR-base snapshot was observed?
- What is the independently resolved current live base tip?
- Which required Check Runs passed on the exact head?
- Which Commit Statuses exist and who created them?
- Which formal reviews are current and which reviewer, if any, qualifies independently?
- Which model judgments exist and what authority class do they have?
- Which branch writer owns the mutation lane?
- Did GitHub accept the expected-head mutation?
- What protected merge revision resulted?
- What protected-main/consumer acceptance scenario proves runtime closure?

A missing answer cannot be inferred from another channel.

## 9. Monitoring

Useful finite-cardinality measures:

- oldest executable-lane age;
- oldest deferred-lane age by reason code;
- count of branch-local writer collisions avoided;
- transient retry attempts/exhaustions by failure class;
- time from exact-head gate-clean to protected merge;
- time from protected merge to operational acceptance;
- count of `META_INTERMEDIATE` events followed by another substantive action;
- count of `USER_REDIRECTION_INCIDENT` recoveries that advanced one versus at least two distinct lanes;
- count of redirection recoveries where a safe non-documentation lane followed documentation repair;
- count of first exit sweeps that discovered work; and
- number of `RUN_BUDGET_EXHAUSTED` continuation handoffs with executable lanes remaining.

Do not place repository source text, comment bodies, PII, model output, or credentials in metric labels.

## 10. Reopening and escalation

Reopen continuation incidents when:

- a run terminates after a meta/control event while safe work existed;
- user redirection is answered only with prompt/document/report work while safe repository execution exists;
- two independent safe lanes exist after redirection but only one is advanced before termination;
- documentation is the last recovery action while a non-documentation lane is executable;
- a waiting PR starves an unrelated lane;
- a defer key suppresses a changed head/base or unrelated branch;
- a second exit sweep reused stale evidence;
- `RUN_BUDGET_EXHAUSTED` is reported as software/product completion; or
- one evidence authority is used to fill a missing field from another authority.

Escalate to the user/operator only when a genuinely external permission/governance/safety decision is required **and** the fresh whole queue has no other safe executable work.