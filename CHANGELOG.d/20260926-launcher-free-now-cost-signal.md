### Review sidecar admits free routes only when servable free now

- `scripts/ci/contextual_orchestrator_review_launcher.py` no longer treats a
  zero catalog price alone as `orchestrator/free` admission. Candidates are
  the orchestrator's zero-priced rows plus rows it nominated from Experiential
  Labs' public keyless `promotions[]` catalog (`free_promotion`), limited to
  general-chat, text-output routes before any probe. `_free_now_models`
  consults the pinned orchestrator's `free_serving_evidence` signal (the same
  predicate its `general_free_serving_candidates` and
  `TaskOrchestrator._is_free_agent` use): `probe_free_candidates` sends at
  most `REVIEW_FREE_EVIDENCE_MAX_PROBES = 4` 16-token probes per run to
  evidence-required routes (Experiential Labs), and a route is admitted only
  when a response reported `usage.cost == 0` with `is_byok: false`. A positive
  cost, a 429 `free_limit_reached` / `insufficient_quota`, a missing or
  unparseable cost, or a failed probe keeps the route out of the free pool (it
  stays eligible as priced). That a free-tier call reports exactly
  `cost: 0` with `is_byok: false` is inferred from the provider docs and not
  yet observed on a live response.
- Such rows reach the policy with `free_evidence: "per_call_zero_cost"` and no
  token prices; `contextual_orchestrator_review_policy.parse_discovery_report`
  classifies them free with `non_token_price_evidence`
  `{"source": "usage.cost", "price": 0.0, "unit": "per_call"}`, only for
  `experiential_labs` rows marked `is_free: true`.
- When the pinned orchestrator predates that module (or lacks
  `probe_free_candidates`), those providers are treated as paid
  (fail-closed), matching the pin's own serving selector so no dead route
  occupies a free slot. The discovery artifact records the `free_now` signal,
  probe count, probed routes, and withheld routes with reasons.
