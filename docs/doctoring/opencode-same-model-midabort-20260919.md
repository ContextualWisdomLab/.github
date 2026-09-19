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
  continuation appendix on retry only when explicit calibrated authority supplies
  `OPENCODE_SESSION_CONTINUATION_BUDGET`; missing authority injects no appendix.

## Before / after (pinned model, fixture-backed)

| Metric | Before | After (this change) |
| --- | --- | --- |
| Same-model retry carries prior termination reason | No | Yes (checkpoint) |
| Same-model retry carries missing required outputs | No | Yes |
| Route attempt telemetry on retry | Discarded | Preserved (CO#1205 allowlist) |
| Continuation budget | Unbounded prompt replay cycles only | Missing authority fails closed; explicit budget path is tested but remains Proposed pending calibration |
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


### Continuation budget authority repair (2026-09-20)

Review of exact `bed37694c191f13bf18a595af672bb4d63e811af` found that
`DEFAULT_CONTINUATION_BUDGET = 2` and
`${OPENCODE_SESSION_CONTINUATION_BUDGET:-2}` silently selected two
decision-affecting continuations while the controlled A/B and allocator
evidence remained open. This violated the no-heuristics contract.

Test-only commits `f0775fd48d31bf033279701f747698310aa6d7c6` and
`c4165352bab48123f9333bcfa11a78d060cb9cb0` require the runner and direct
CLI to reject missing budget authority. Minimal source commits
`3e290447b80c3964599bbb811f5cada2435ce28f` and
`4070c161685298a37554a551e7e3f33b2b6e49ad` remove both numeric defaults:
the runner injects no checkpoint appendix without an explicit non-negative
budget, and both CLI commands require `--budget`.

Fresh materialization of exact `4070c161…` passed Python compilation, full
runner Bash syntax, and four direct authority probes (missing CLI authority
fails, the required argument is diagnosed, an explicit budget remains
accepted, and the shell numeric fallback is absent). The execution image does
not contain pytest, so no fresh pytest count is claimed. An explicit budget is
still Proposed rather than calibrated production authority until controlled
completion/time/token evidence and the selected fast-mlsirm/Fugu/Conductor/
TRINITY-compatible allocator receipt are integrated. Hosted exact-head gates
and independent review remain required.
