# Doctoring record: Strix `orchestrator/free` reconciliation

- **Date:** 2026-09-01
- **Status:** supersedes the 2026-08-30 diversity-gate proposal
- **Subject:** Noema, OpenCode, and Strix route required review through
  `ContextualWisdomLab/contextual-orchestrator` using `orchestrator/free`.
- **Decision record:** [`docs/adr/0003-contextual-orchestrator-vendored-free-zdr.md`](../adr/0003-contextual-orchestrator-vendored-free-zdr.md)

## Superseded proposal

The earlier version of this record correctly observed an outage-domain
concentration incident, but it proposed automatically switching Strix between
`orchestrator/free` and `orchestrator/auto` when a
`free_account_diversity >= 2` condition was met. That cardinality threshold was
not derived from a reliability model, statistical estimand, authoritative
standard, or experimentally validated routing policy. It is therefore not a
permitted decision rule under the organization no-heuristics contract and must
not be implemented or revived.

`free_account_diversity` or equivalent provider/outage-domain observations may
remain diagnostic evidence. Diagnostics do not acquire routing authority merely
because they are deterministic or measured. Any future reliability-aware model
selection must identify its estimand and be independently evaluated rather than
turning an incident count into a threshold.

## Current executable contract

Protected-main evidence now records the actual Strix policy:

- `.github/workflows/strix.yml` accepts the contextual-orchestrator gateway and
  restricts Strix model overrides to `orchestrator/free`;
- `tests/test_contextual_orchestrator_review_sidecar_contract.py` asserts
  `CONTEXTUAL_ORCHESTRATOR_POOL: free`;
- `scripts/ci/strix_quick_gate.sh` and the required-workflow smoke contracts no
  longer treat `orchestrator/auto` as an allowed Strix model route;
- Noema and Required OpenCode use the same `orchestrator/free` product boundary;
- private/internal review targets require the sidecar's ZDR policy rather than a
  workflow-local model fallback.

The five bootstrap credentials may all be supplied to contextual-orchestrator:
`BYTEZ_API_KEY`, `NVIDIA_NIM_API_KEY`, `NVIDIA_NIM_API_KEY_SUB`,
`OPENROUTER_API_KEY`, and `OPENAI_API_KEY`. Receiving, registering, or globally
discovering through `OPENAI_API_KEY` is not a defect. The invariant is the
`orchestrator/free` candidate-admission boundary: OpenAI-key-derived models are
not eligible for free-pool candidate generation, ranking, routing, serving,
failover, fallback, preflight, or durable free-pool persistence. The four
free-eligible credential sources still require their explicit zero-cost,
privacy, and capability evidence; a supplied credential does not fabricate an
eligible model.

## Admission versus routing

The central review catalog is an admission boundary. It may enforce explicit
pool, zero-cost/price evidence, credential-source, capability, and ZDR
predicates, but it must not turn discovery into a provider quota, family quota,
candidate-count cap, cost/provider/name ordering, synthesized priority, or
first-come escalation preference. Every evidence-eligible route remains in the
catalog. Downstream selection requires identified routing evidence; if that
evidence is unavailable, the runtime fails closed.

PR #1629 restores that contract on current protected-main lineage by removing
the reintroduced catalog cardinality/account caps, ranking, priority synthesis,
launcher route-count caps, and shared escalation quota while preserving the
free-only central-review pool.

## Evidence trail

- `.github/workflows/strix.yml` — executable Strix pool and override boundary.
- `tests/test_contextual_orchestrator_review_sidecar_contract.py` — executable
  `orchestrator/free` sidecar contract.
- `docs/adr/0003-contextual-orchestrator-vendored-free-zdr.md` — current and
  historical pool decisions, including the later amendment superseding Strix
  `orchestrator/auto`.
- `docs/product-technical-gap-baseline.md` — current implementation/gap ledger.
- `scripts/ci/contextual_orchestrator_review_policy.py` — admission evidence,
  not a substantive model router.
