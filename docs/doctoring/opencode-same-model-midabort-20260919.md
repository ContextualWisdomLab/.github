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

- Provider-specific route evidence remains inside ContextualWisdomLab/contextual-orchestrator.
  The leaf does not consume mutable `attempts[]`, provider, model, phase, or status
  fields from open CO PR #1205; a released provider-neutral projection is required
  before any owner telemetry can enter continuation control context.
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
| Provider-specific route telemetry on retry | Discarded | Still discarded at the leaf; CO remains the observability owner |
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


### Provider-neutral owner-boundary repair (2026-09-20)

The existing P0 review showed that the leaf parser read the mutable CO #1205
`model`, `provider_name`, phase, attempt number, and HTTP status fields and
formatted them into the next model prompt. That made two envelopes with the
same provider-neutral outcome produce different control context and duplicated
an unreleased owner schema inside ContextualWisdomLab/.github.

RED `7c5c6a7548f5836d956cb196427581060951021b` and
`3a8c056bc2b4e0f5b012f900b24bfc54636e24ba` require provider/model/phase/
status values to have zero effect on the appendix. GREEN
`866cc6a4a1285936da5110ea0a28071548da09e2` and
`8c04d1284f96eb0a702a24287290e30ba3f1bb9d` remove route parsing, storage,
formatting, CLI plumbing, and runner input. Commits
`51a531886962f35eb091b97cf8ec2d6e05dcec81` and
`b7e8256f4c8a9cf7cf1022312ee86ba6f985f9a4` retire the consumer-owned parser
and fixtures entirely.

Fresh exact materialization at `7c5844ad…` (tree `53908068…`) passed Python
compilation, Bash syntax, checkpoint/runner **65 tests**, and the full
warnings-as-errors suite (**3,428 passed / 5 skipped / 40 subtests passed**).
The provider-neutral probe injects hostile legacy `openrouter`, phase, HTTP 429,
and served-model fields into a checkpoint and proves none reaches the
continuation appendix. RED `68459817…` additionally proves both direct CLI paths
previously accepted negative budget authority and exited zero; GREEN
`7c5844ad…` rejects it at the parser boundary. CO issue #1106 records the
required immutable, provider-neutral, allocator/fast-mlsirm receipt before any
owner telemetry or valid budget can be consumed.
