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
- A probe sent after the organization's free allowance is used up can be
  billed once; this happens only when org-wide credits overflow is on
  (otherwise the provider answers 429 and nothing is billed). That single
  billed call demotes the route until the next 00:00 UTC reset and is an
  accepted trade-off (the repository owner's decision). Runs with
  `--require-zdr` send no probe at all, since Experiential Labs has no ZDR
  scope and its routes would be dropped by the ZDR filter anyway; the
  artifact records `probe_skipped: "require_zdr"`. Probes stay bounded by
  count only; per ADR 0003 they carry no fixed wall-clock timeout.
- An unexpected shape of the pinned signal (a missing `FREE_SERVING_LEDGER`,
  a changed signature, any other error from it) no longer aborts the
  sidecar: only evidence-required and promotion-only routes are withheld as
  `no_signal`, and the artifact records `signal: "incompatible"` with the
  error type. The evidence-required provider set and the per-call marker are
  defined once in `contextual_orchestrator_review_policy` and reused by the
  launcher.
