# ADR-0029: Review sidecar preflight fills the served set lazily to a readiness target

- **Status:** Proposed
- **Date:** 2026-09-06
- **Scope:** `scripts/ci/contextual_orchestrator_review_launcher.py` (`_preflight_review_agents`, the stage limits), `scripts/ci/contextual_orchestrator_review_sidecar.sh` (`ORCHESTRATOR_CATALOG_LIMIT` default), ADR-0003 §2's stage budget sentence
- **Amends:** ADR-0003 (the "twelve-route startup budget" clause). ADR-0005's attempt counts are historical and are not restored.

## Problem

The review sidecar selected a fixed catalog of twelve routes and probed every one of them, then served whatever was ready. `.github#1939` made the selection diverse (round-robin across credential accounts inside each cost/ZDR tier, four routes per account), which was right, but it exposed a second defect: the per-account slice is filled from an alphabetically sorted model list, and for both NVIDIA NIM keys the first four models are `deepseek-v4-flash`, `deepseek-v4-pro`, `gemma-3-12b`, `gemma-3-4b`. NIM lists the two `gemma-3` models but answers `404` to every chat request on every run observed. Each NVIDIA key therefore served two working routes, both the most contended models, while the pre-#1939 eight-slot fill had reached `meta/llama-3.2-11b`, `llama-3.2-90b` and `meta/muse-glimmer-30b`, which were ready in every Strix artifact of that afternoon.

Measured on `ContextualWisdomLab/.github` (lane jan's census on `#1948`, verdict-step conclusions only, draft skips excluded):

| window | preflight ready of 12 | `noema-review` success / failure |
|---|---|---|
| before `#1939` (`main@f2f91b80`, 2026-09-05T17:25Z) | 6, 6, 5 (16:37–16:56Z artifacts) | 7 / 14 |
| after | 1–3 (23:47Z onward) | 0 / 22 |

The evening's rate-limit pressure is a confound; the mechanism is not. A fixed slice from a list with dead entries wastes the slice, and probing every candidate regardless of how many are already ready spends per-key rate budget (`#1948`) for nothing.

## Constraints

1. No model name is hard-coded anywhere in the fill; a dead candidate is discovered by its probe, not by a list.
2. Probe spend per sidecar boot stays bounded and is stated as a number, because the probes themselves consume the per-key budgets the served routes need (`#1948`).
3. `#1947`'s deferral (a probed route that answered a transient status is kept behind the ready routes) applies unchanged to whatever was probed.
4. ADR-0003's evidence-triggered priced fallback (only after every free candidate rejects) keeps its shape; the two stages still share one startup budget.
5. `ready_count` keeps its meaning (routes proven ready by a probe) so the peers' post-merge discriminators stay comparable.

## Decision

The catalog is a **candidate list**, not the served set. `build_zdr_prioritized_catalog` keeps its tier-then-round-robin order (`#1939`) and is asked for up to `REVIEW_PREFLIGHT_MAX_TOTAL_ROUTES = 24` candidates (per-account cap unchanged at 8; the sidecar's `ORCHESTRATOR_CATALOG_LIMIT` default rises from 12 to 24). `_preflight_review_agents` probes candidates **in that order and stops** as soon as `REVIEW_PREFLIGHT_TARGET_READY = 8` routes are ready or `REVIEW_PREFLIGHT_MAX_PROBES = 16` probes have been spent, whichever comes first. The auto pool's split becomes 16 free candidates and up to 8 priced fallback candidates; each stage's list fits the probe cap, so the worst case remains "every candidate probed once".

The report gains `candidate_count`, `target_ready` and `probe_budget`; `probed_count` now counts probes actually sent, and `rejected_count` is `probed − ready − deferred`. Unprobed candidates get no `routes` row.

## Consequences

- **Good:** a dead candidate costs one probe and yields its place to the next candidate in the same account's list; a healthy hour stops after about eight to twelve probes instead of always twelve; a bad hour is bounded at sixteen probes per stage.
- **Cost:** in an hour where nothing is ready the sidecar sends up to 16 probes per stage where it sent 12, a third more against already exhausted keys. This is the price of finding routes past the dead ones; `#1948`'s shared rate ledger is the lever above it.
- **Unchanged:** a route that answers the probe and then goes silent at request time still costs the gateway's full retry budget (`contextual-orchestrator#1045`); readiness is measured at 16 tokens (`#1454`).
- **Discriminator:** post-merge, `probed_count` versus `candidate_count` per boot and `ready_count` of the served set, read from the `runtime preflight summary` in the job log or the `noema-sidecar-evidence` artifact, compared with the table above.

## Alternatives considered

- **Raise the per-account cap back to 8 with a 12-route limit** — restores the pre-#1939 pool but reintroduces the single-account fill that `#1939` fixed; the 404s would still occupy slots.
- **Exclude models that 404 by name** — a hard-coded exclusion list the next discovery change silently invalidates; rejected by constraint 1. The discovery-side question (why NIM lists models it does not serve) remains open in `contextual-orchestrator`.
- **Family-level round-robin before the per-account cap** (jan's fallback proposal) — reduces same-family contention but does not touch dead candidates; can be layered later if the census shows family contention as the residual.
- **Probe all 24 candidates** — best served set, double the probe spend in the hour that can least afford it; rejected by constraint 2.
