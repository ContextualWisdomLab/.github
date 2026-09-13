# OpenRouter ZDR feed route keys used the wrong field — 2026-09-13

## Symptom

`noema-review` and `strix` both failed closed on `ContextualWisdomLab/late-life-anxiety-reanalysis#10` (head `a1cd5bc6783c6510dfcf937f523c733366e82213`, runs `34700409452`/job `103571267389` and `34700409446`/job `103571829483`) against central `fb17ef556f94f673234aa557254ae52779e9a7b0`, both exiting with `PolicyError: no attested ZDR model route is available with the ZDR policy; orchestrator/free would fail closed`. Every private/internal consumer runs `--require-zdr` (ADR-0003), so this is a hard boot failure, not a degraded catalog.

## Root cause (feed schema)

`_load_zdr_endpoints` (`scripts/ci/contextual_orchestrator_review_policy.py`) built route keys from `endpoint.get("model_name")`. On the real `https://openrouter.ai/api/v1/endpoints/zdr` feed (see OpenRouter's ZDR docs, https://openrouter.ai/docs/guides/features/zdr), `model_name` is a human display string (e.g. "DeepSeek: DeepSeek V4.1 Flash") while `model_id` is the slug contextual-orchestrator discovery reports as `model` (e.g. `inclusionai/ling-3.0-flash-vl:free`). No live-feed key ever matched `is_zdr_model(...)`, so the catalog was always empty under `--require-zdr`. The three fixtures in `tests/test_contextual_orchestrator_review_policy.py` put slugs into `model_name`, which is why this was invisible to tests since the keying was introduced in 17052a7ca (#1360, 2026-08-27).

## Repair

`_load_zdr_endpoints` now keys on `endpoint.get("model_id")`; there is no fallback to the display name, and rows missing `model_id` or `provider_name` are still skipped. The three fixtures were corrected to carry the real feed schema (`model_id` slug + a display-string `model_name`). `is_zdr_model` and `zdr_policy.py` are unchanged.

## Offline reproduction (before / after)

Discovery: a 60-row consumer snapshot (20 each openrouter/nvidia_nim/nvidia_nim_sub free rows). Feed: the live 859-entry `/api/v1/endpoints/zdr` response fetched 2026-09-13, carrying three matching `inclusionai/ling-3.0-flash-*:free` openrouter routes served by `Novita`.

- Before: `--require-zdr --pool free` exits 1 with the `PolicyError` above.
- After: exits 0, `zdr_selected_count: 3`, selecting exactly `openrouter/inclusionai/ling-3.0-flash-{vl,sante,fin}:free`, all `zdr: true`.
- Without `--require-zdr`: `zdr_selected_count: 3` and those three routes rank first in the 12-route free catalog.

## Hosted acceptance still required

This is an offline fix against a static discovery/feed snapshot. It does not prove a newly loaded central SHA boots the sidecar on the private consumer's exact head, and it does not change how the gateway itself requests ZDR routing from OpenRouter — that remains a separate contextual-orchestrator (CO)-side check.
