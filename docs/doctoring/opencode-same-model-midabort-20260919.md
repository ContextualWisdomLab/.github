# OpenCode same-model mid-abort and context loss (2026-09-19)

## Scope

Improve OpenCode stopping mid-work or misunderstanding required outputs on
**same-model retries** under the pinned pool
`contextual-orchestrator/orchestrator/free` (`opencode.jsonc`), without model
changes. Out of scope: inflight same-head dispatch dedupe / pg-erd handshake
waste (`ContextualWisdomLab/.github#2283`).

## Reproduction cases (live Actions)

| Run ID | Repo | Termination | Context loss | Retry/resume | Completion judgment |
| --- | --- | --- | --- | --- | --- |
| `35452307646` | `.github` PR `#2040` | `cancelled` (`cancel-superseded-opencode-review-runs`) | In-flight review discarded on superseded head; no exported session checkpoint | Replacement dispatch queued; prior partial work not reused | Job `cancelled`, not success; no formal verdict on cancelled head |
| `35401977816` | `.github` PR `#2278` | `failure` (`opencode-review` job) | Model pool cycled without host checkpoint; partial assistant export dropped between attempts | Same-model retries restarted from full prompt only | `review_status=exhausted`; fail-closed, no synthetic APPROVE |

Pinned model for measurement: `contextual-orchestrator/orchestrator/free`
(resolved upstream ids recorded from sidecar route evidence when present).

## Reused surfaces

- `scripts/ci/contextual_orchestrator_route_evidence.py` — consumer for typed
  `attempts[]` / `terminal_reason` envelopes from
  `ContextualWisdomLab/contextual-orchestrator#1205` (closes #1016); mirrors the
  allowlist already used in `noema_review_gate.py`.
- `scripts/ci/opencode_review_session_checkpoint.py` — host-managed checkpoint
  ledger (digest-only partial work, missing required outputs, route telemetry).
- `scripts/ci/run_opencode_review_model_pool.sh` — injects bounded same-model
  continuation appendix on retry (`OPENCODE_SESSION_CONTINUATION_BUDGET`, default
  `2`).

## Before / after (pinned model, fixture-backed)

| Metric | Before | After (this change) |
| --- | --- | --- |
| Same-model retry carries prior termination reason | No | Yes (checkpoint) |
| Same-model retry carries missing required outputs | No | Yes |
| Route attempt telemetry on retry | Discarded | Preserved (CO#1205 allowlist) |
| Continuation budget | Unbounded prompt replay cycles only | Explicit env budget, tested |
| False success on incomplete control | Fail-closed already | Unchanged fail-closed |
| Partial provider body replayed into prompt | N/A | Forbidden (digest only) |

Live completion-rate deltas require a controlled replay harness on org runners;
fixture tests prove the host contract; production measurement remains open.

## Remaining

- Executable fresh-session loop with durable SQLite ledger (`#2068`) still needs
  read-only agent boundary preserved.
- Inflight dedupe cancellation waste (`#2283`) remains lead-owned.
- Production before/after completion rate on long tool-heavy reviews is not yet
  measured on live `orchestrator/free` traffic.


## Exact-head review repair (2026-09-20)

Independent review of `9fdfddfaa3d792ad0a2de4d1884df14ad999ffd5`
found four checkpoint-integrity defects:

- bounded log helpers loaded the complete file before slicing;
- user-prompt markers could satisfy assistant-output requirements;
- later retries accumulated every earlier checkpoint appendix;
- checkpoint state and continuations applied to candidates outside
  `contextual-orchestrator/orchestrator/free`.

Test-only commits `cfeda192f68af43077cae3b3cd61ef8f11eaea20` and
`afe1420d3175d81f51c091b3499d792037cc304e` reproduce all four defects.
Fresh execution at the test-only head reported exactly **4 failed**. Minimal
source commits `36fb3907eaa229f8d2292feae3f25e010643693a` and
`b400ad5d993dcc8d5efcdbcb13aafa2f6d295d2c` bound file reads, filter only
assistant text parts, rebuild the base prompt on every retry, and scope
checkpoint read/write to the pinned orchestrator route. Fresh
warnings-as-errors execution passed **43 tests** across the checkpoint, route
evidence, and model-pool suites; Bash syntax, Python compilation, and diff
whitespace checks also passed. Hosted exact-head gates remain separately
required and no predecessor receipt transfers.
