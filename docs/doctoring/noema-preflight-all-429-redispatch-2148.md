# All-429 sidecar preflight never reached the Noema transport re-dispatch — 2026-09-22

## Symptom

From 2026-09-16 to 2026-09-21, 17 of 89 `noema-review` runs (19 %) failed at sidecar preflight
(`review sidecar preflight failed`, `ready_count: 0`). All 17 were private targets
(`late-life-anxiety-reanalysis` 15, `gyeot` 2) with `CONTEXTUAL_ORCHESTRATOR_REQUIRE_ZDR=true`.
Every pool was OpenRouter-only with 4 or 5 candidates, and every route was `status=rejected`,
`http_status=429`, with no `retry_after_s`. Example: `late-life-anxiety-reanalysis#218`, head
`e2393877`, job `106085557453` failed after about 3 minutes with
`sidecar exited before healthz (status 1)`.

## Root cause

ADR-0031 re-dispatches only on outputs from `Prepare Noema model verdict` (`noema_prepare`). An
all-429 preflight fails in `Provision contextual-orchestrator review sidecar`, and every later
success-gated step, including `noema_prepare`, is skipped. The re-dispatch `if:` therefore saw empty
outputs, and the review ended as a plain failure even though the failure was the same
provider-capacity class ADR-0031 already recovers from. ADR-0031's Consequences section says #2148
"shares the classification and attempt evidence, but does not widen this ADR's re-dispatch bound".

## Repair

- The provision step now has `id: sidecar`. A new step,
  `Classify all-429 sidecar preflight as provider capacity`, runs only when that step failed. It
  calls `scripts/ci/noema_preflight_capacity.py` on
  `strix_runs/contextual-orchestrator-preflight.json`.
- A report counts as capacity only when:
  - `contract` is `strix-plain-chat-preflight-v2`;
  - `ready_count` is the integer 0;
  - `probed_count` is at least 1;
  - `routes` holds exactly `probed_count` rows;
  - every row is `rejected` or `deferred` with integer `http_status` 429;
  - any nested `primary_attempt` meets the same rule.

  Anything else is not capacity and keeps today's plain failure. That includes a missing, empty,
  oversized, non-UTF-8, or malformed report, and any other status such as 404, 5xx,
  `RemoteDisconnected`, or `escalation_budget_exhausted`.
- The step emits the same outputs as `two_phase._emit_transport_capacity_outputs`, using the same
  `NOEMA_TRANSPORT_RETRY_ATTEMPT` counter, `MAX_TRANSPORT_REDISPATCH_ATTEMPTS`, and
  `transport_redispatch_delay_seconds`. A route `retry_after_s` is used only when it is inside
  `[1, TRANSPORT_REDISPATCH_RETRY_AFTER_MAX_SECONDS]`. When several routes carry one, the longest
  wait wins. Otherwise the deterministic head-keyed jitter applies.
- `Schedule bounded Noema transport re-dispatch` now accepts either source's capacity-and-eligible
  pair. Its bounded-delay, attempt-counter, and live-head checks are unchanged.

The job still fails, and no approval is produced. The re-dispatch is a same-head continuation that
the existing step re-validates against the live head.

## Not changed

This change leaves the ZDR policy, candidate sets, `REQUIRE_ZDR`, provider lists, the sidecar and
launcher, and every model-path timeout unchanged.

## Follow-up

`strix.yml` provisions the same sidecar and fails the same way on an all-429 private pool. It has
no bounded re-dispatch of its own, so it is not covered here.
