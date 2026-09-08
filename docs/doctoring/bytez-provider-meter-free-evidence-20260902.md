# Bytez provider-meter free-evidence repair — 2026-09-02

## Incident and owner boundary

`ContextualWisdomLab/.github` consumes the exact vendored `ContextualWisdomLab/contextual-orchestrator` discovery runtime when it constructs the central review sidecar. The review control plane owns admission of discovered routes into `orchestrator/free`; the reusable provider parser and its source-price semantics remain owned by `contextual-orchestrator`.

PR #1651 pins contextual-orchestrator commit `045d17da5e2aea56a97e241ee158ab1628d78660`. At that immutable source, the Bytez parser treats `meterPrice` as provider-native GPU/time-meter evidence rather than fabricating prompt/completion token prices. Its regression contract proves that `"0 / sec"` yields `DiscoveredModel.is_free == True` while both per-1k token price fields remain `None`; missing, malformed, boolean, and nonzero meter rates remain non-free. This is the upstream authority used here.

## Root cause

The central launcher preserved the upstream `is_free` route identity but the central policy required both `prompt_price_per_1k` and `completion_price_per_1k`. Consequently, an exact-zero Bytez meter price was reclassified from upstream free evidence to `COST_UNKNOWN`, so Bytez could never enter the authorized free review pool even when discovery succeeded.

The defect was not a Bytez pricing problem and was not repaired by inventing token prices. It was an Anti-Corruption Layer loss: a provider-native price dimension was collapsed into a token-only central contract.

## RED → GREEN evidence

The RED integration regression is `tests/test_contextual_orchestrator_bytez_catalog_integration.py` at commit `a598f500f6c278b44c40ea093954eb1de508a595`. It passes a pinned-runtime-shaped Bytez row through the real launcher `_report_rows`, then `parse_discovery_report`, then `build_zdr_prioritized_catalog`. Before the production repair, the route is `COST_UNKNOWN` and cannot be selected.

Production repair commits `90dee49e4d357b655480b86a4201291f9be02cc3` and `f20ab8469e5875732e587f69c3ba950b4169ef80` preserve the upstream exact-zero Bytez attestation as a separate `non_token_price_evidence` object:

```json
{
  "source": "bytez.meterPrice",
  "price": 0.0,
  "unit": "provider_meter_unit"
}
```

The existing `_normalize_cost_evidence` token-vector compatibility contract remains unchanged: a generic free marker without a complete token vector is still unknown. Only Bytez rows whose pinned upstream parser already attested exact-zero provider-meter price receive the non-token evidence object. Bytez rows without that attestation remain unknown and fail closed.

Selected-route audit evidence carries the same non-token object so the central review record does not erase why the route qualified as free.

## Invariants

- Never fabricate Bytez prompt/completion per-token prices.
- Never infer free status from model name, provider name alone, missing price, or a nonzero/malformed meter rate.
- `OPENAI_API_KEY` remains excluded from `orchestrator/free` admission by the independent source-credential policy.
- ZDR/private-target admission remains independent from cost evidence and still fails closed.
- Provider discovery failure remains failure/absence evidence; this repair does not relabel an HTTP 500 or unavailable Bytez catalog as success.
- The central policy consumes the pinned upstream parser contract; mutable open-PR bytes are not runtime authority.

## Follow-up boundary

A future provider-native pricing model with a different billing dimension requires its own explicit upstream evidence contract and central adapter decision. This Bytez repair is not a generic rule that `is_free=True` can replace missing price evidence for arbitrary providers.
