# Provider-Neutral Preflight Resilience Implementation Plan

> **For agentic workers:** Use `superpowers:executing-plans` or `superpowers:subagent-driven-development` when continuing this plan.

**Goal:** Recover any eligible model route after a bounded transient transport failure, remove implicit inference deadlines for every model, and reserve reasoning-specific handling for capability or response evidence rather than model/provider names.

**Incident:** DiagramWeave Actions run `33554858825`, job `100013111840` exposed an HTTP 502 on one discovered route and a long-running review path. The observed DeepSeek/NVIDIA NIM identity is incident evidence only; it is not a policy key.

**Ownership:**

- `ContextualWisdomLab/contextual-orchestrator#971` owns the generic `ModelClient` transport and inference-deadline contract.
- `ContextualWisdomLab/.github#1629` owns the central review launcher's preflight use of that contract.
- Merged central PR `#1546` already removed fixed Noema/OpenCode/sidecar inference deadlines. This plan does not replace that work or reintroduce per-model timeout tables.

## Invariants

- `ModelClient.timeout=None` means no hidden wall-clock inference deadline for any model.
- Explicit caller cancellation, stale-head cancellation, and workflow/job termination remain valid outer lifecycle controls.
- Connection establishment and other transport controls are independent configuration. They are not selected from model names or reasoning capability.
- HTTP 502, 503, 429, timeout, and connection failures are retried only when Contextual-Orchestrator classifies them as transient.
- HTTP 400, 401, 403 and other permanent failures remain terminal under the existing taxonomy.
- Preflight transport retry budget is exactly one recovery attempt and is recorded separately from semantic prompt attempts.
- No branch may inspect `model`, `agent_id`, `provider_name`, or `reasoning_effort_supported` to decide inference timeout or transport retry eligibility.
- Reasoning-specific token escalation is triggered by response evidence: `finish_reason == "length"` or populated reasoning with no usable content. It is independent of transport retry and does not require a model-name allowlist.
- Independent provider-account lanes may probe concurrently; routes sharing one provider account remain serialized. Published results return to catalog order.
- Completion timing, retry count, provider identity, and discovery order do not become routing or admission authority.
- Provider response bodies, prompts, exception messages, credentials, and internal topology are not persisted in preflight evidence.

## Task 1: Generic transport regression

**Files:**

- `ContextualWisdomLab/contextual-orchestrator/tests/test_provider_gateway_resilience.py`
- `ContextualWisdomLab/.github/tests/test_contextual_orchestrator_review_transient_preflight.py`

- [x] Parameterize the HTTP 502 recovery test across `reasoning_effort_supported = None, False, True`.
- [x] Use an arbitrary provider/model identity so the test fails if policy becomes model-name-dependent.
- [x] Prove HTTP 401 remains single-attempt and terminal.
- [x] Prove every review `ModelClient` constructor carries `timeout=None`, while only idempotent preflight receives the one-retry budget.

## Task 2: Response-driven reasoning behavior

**Files:**

- `scripts/ci/contextual_orchestrator_review_launcher.py`
- `tests/test_contextual_orchestrator_review_transient_preflight.py`
- `tests/test_contextual_orchestrator_review_runtime_preflight.py`

- [x] Keep the cheap base token budget for ordinary routes.
- [x] Escalate the same route once when its response reports length exhaustion or reasoning without visible content.
- [x] Add a regression using an arbitrary model name and unknown reasoning metadata; the response alone must trigger escalation from 16 to 4096 tokens.
- [x] Keep `attempts` as semantic payload attempts and `transport_retry_budget` as transport policy evidence.

## Task 3: Exact-head verification

Run on each unchanged final head:

```bash
# contextual-orchestrator
python -m pytest -q tests/test_provider_gateway_resilience.py tests/test_provider_reliability.py

# central review control plane
python -m pytest -q \
  tests/test_contextual_orchestrator_review_transient_preflight.py \
  tests/test_contextual_orchestrator_review_runtime_preflight.py \
  tests/test_contextual_orchestrator_review_preflight_concurrency.py \
  tests/test_contextual_orchestrator_review_sidecar_contract.py
```

Then require the normal repository CI, security, supply-chain and independent-review gates to reach terminal success on those exact heads. Queued, skipped, cancelled, predecessor-head or status-only results are not GREEN.

After both owner changes are integrated into the refs consumed by the reusable workflow, rerun the unchanged DiagramWeave PR head. Close the incident only when the downstream Noema review produces terminal exact-head evidence.
