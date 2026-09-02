# Strix `orchestrator/free` model-boundary doctoring — 2026-09-02

## Exact failing evidence

Protected `main@23df081c36c93da019c89c474351002afb014daa` already hard-pins the central Strix workflow to `contextual-orchestrator/orchestrator/free`, provisions contextual-orchestrator with `CONTEXTUAL_ORCHESTRATOR_POOL: free`, passes all five bootstrap credentials, and sets `STRIX_FALLBACK_MODELS: ""`. The shared Strix gate nevertheless retained direct-provider normalization and direct-OpenAI/OpenRouter/GitHub Models/Vertex fallback machinery. That created a second provider-routing surface beneath a workflow whose accepted owner contract delegates provider selection and failover to contextual-orchestrator.

## Causal owner

The reusable owner is `ContextualWisdomLab/.github/scripts/ci/strix_model_utils.sh` together with `strix_quick_gate.sh`, not downstream repositories. The first repair is placed at model normalization so a concrete provider identifier cannot cross into any later credential/base/fallback branch.

## Test-first repair

Commit `2083a72dccaa1d96ea423a51af537240fde8a210` adds the regression contract before the production change. It requires exactly the two governed `orchestrator/free` spellings to be admitted and representative direct-provider identifiers to fail closed. Commit `10c1ddf822f1e6336b73a9093a56680fea8f4f54` changes the production normalizer accordingly.

No arbitrary rank, weight, score, threshold, retry preference, or provider order replaces the removed routing surface. The accepted identifier is a categorical authority boundary; contextual-orchestrator owns all downstream model choice.

## Credential and privacy correction retained

This repair intentionally does **not** remove `OPENAI_API_KEY` from central workflow bootstrap. All five credential sources may be registered and globally discovered. The `orchestrator/free` candidate-admission owner remains contextual-orchestrator, where OpenAI-derived candidates are excluded while BYTEZ, NVIDIA NIM primary/subaccount, and OpenRouter sources may be considered subject to explicit free/privacy/capability evidence.

Private-target ZDR remains enforced by the central workflow and sidecar. A direct provider route is rejected before it could bypass that boundary.

## Verification status

Fresh hosted exact-head tests are required before merge. Queued, pending, stale, predecessor-head, or synthetic evidence is non-passing. Historical direct-provider fallback code is now unreachable through the accepted model normalizer but remains cleanup debt until a subsequent exact-head change removes it without losing unrelated Strix scanner behavior.
