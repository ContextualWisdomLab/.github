# Provider-Neutral Preflight Resilience Implementation Plan

**Goal:** Keep central review preflight evidence-only and provider-neutral: one provider-default request per admitted route, no repository-authored token/sampling allocation, no inference retry budget, no fixed total model deadline, and concurrent progress across independently credentialed provider-account lanes.

**Incident history:** DiagramWeave Actions run `33554858825`, job `100013111840` exposed an HTTP 502 on one discovered route and a long-running review path. The observed DeepSeek/NVIDIA NIM identity is incident evidence only; it is not a policy key. Later organization evidence in `.github#712` showed that review-sidecar provisioning could hold hosted runner slots for hours after the protected Contextual-Orchestrator client moved to an intentionally unbounded default model timeout. That operational evidence does not justify restoring a 90-second model deadline or inventing repository-local retry/token policy.

**Ownership:**

- `ContextualWisdomLab/contextual-orchestrator#1106` owns the generic free-pool admission, routing and test-time-compute contract; immutable released gateway/client/schema artifacts are the final shared boundary.
- `ContextualWisdomLab/.github#1629` owns the central review launcher's temporary consumer-side admission/preflight behavior while that migration is incomplete.
- `.github#2139/#2140` own progress/idle continuation and runner-occupancy semantics. A progress/idle control must not become a total elapsed inference deadline.
- `.github#1150/#712` own read-only queue-health evidence and classification, not review-lane mutation.

## Invariants

- `ModelClient.timeout=None` means no hidden total wall-clock inference deadline for any model.
- Explicit user cancellation, provider termination, stale-head cancellation and administrative workflow termination remain distinct lifecycle events.
- Preflight sends one semantic provider-default request once. HTTP 502, 503, 429, timeout, connection reset and other transport outcomes remain evidence; they do not allocate another model call in the central launcher.
- HTTP 400, 401, 403 and other permanent failures remain bounded rejection evidence under the owner taxonomy.
- Central preflight does not author `max_tokens`, `temperature`, retry budgets, model-name allowlists or semantic token escalation. Token/sampling/TTC policy belongs to the Contextual-Orchestrator owner boundary.
- `model`, `agent_id`, `provider_name`, `reasoning_effort_supported`, completion timing and discovery order do not decide inference deadlines or compute allocation.
- A response containing reasoning but no usable content is rejected as observed evidence after the single provider-default request; it is not retried with a larger token budget.
- Independent provider-account lanes may probe concurrently; routes sharing one provider account remain serialized. Published results return to catalog order, so completion timing cannot become routing preference.
- Provider response bodies, prompts, exception messages, credentials and internal topology are not persisted in preflight evidence.
- Queue/runner admission and repository source correctness are classified separately. A job with no runner and no executed steps is incomplete admission evidence, not source GREEN or RED.

## Task 1: One-shot provider-neutral regression

**Files:**

- `tests/test_contextual_orchestrator_review_no_heuristic_compute.py`
- `tests/test_contextual_orchestrator_review_transient_preflight.py`
- `tests/test_contextual_orchestrator_review_preflight_concurrency.py`

- [x] Parameterize transient HTTP failure evidence across `reasoning_effort_supported = None, False, True` without model-name policy.
- [x] Prove HTTP 401 remains single-attempt and terminal.
- [x] Prove concurrency across independent provider-account lanes while same-account routes remain serialized.
- [x] Prove the concurrency fixture itself does not inject `max_tokens` or `temperature`.
- [x] Require a reasoning-only/content-less response to be rejected after one provider-default request.
- [ ] Remove the remaining launcher-side fixed token/sampling constants and semantic escalation path.
- [ ] Remove the sidecar gateway inference replay so startup uses the same one-shot contract end to end.

## Task 2: Progress and runner occupancy

**Files / owners:** `.github#712`, `.github#1150`, `.github#2139/#2140`, `contextual-orchestrator#1106`.

- [x] Preserve exact `{repo, PR, head, base, workflow, run, job, runner assignment}` identity when classifying queue delay.
- [x] Preserve current-head review work rather than cancelling it merely to free capacity.
- [ ] Bound avoidable provisioning occupancy structurally through provider-account concurrency and progress/idle semantics, not total inference duration.
- [ ] Demonstrate that unrelated current-head required jobs regain hosted runner admission without changing leaf `runs-on`, weakening gates or synthesizing statuses.
- [ ] Migrate provider probing/credential/routing authority to an immutable released Contextual-Orchestrator gateway contract and remove duplicated central policy.

## Task 3: Exact-head verification

Run the focused central contract suite on the unchanged final owner head:

```bash
python -m pytest -q \
  tests/test_contextual_orchestrator_review_no_heuristic_compute.py \
  tests/test_contextual_orchestrator_review_transient_preflight.py \
  tests/test_contextual_orchestrator_review_runtime_preflight.py \
  tests/test_contextual_orchestrator_review_preflight_concurrency.py \
  tests/test_contextual_orchestrator_review_sidecar_contract.py
```

Then require normal repository CI, security, supply-chain and independent-review gates to reach terminal success on that same exact head. Queued, skipped, cancelled, predecessor-head or status-only results are not GREEN. The owner branch must contain no purpose-complete source-rewriting workflow, trigger or repair driver before protected integration.

After the central owner repair is normally integrated and the Contextual-Orchestrator boundary is immutably released, verify an unchanged downstream review consumer. Close the incident only when that consumer obtains real runner assignment and terminal exact-head review evidence without local provider/model hard-coding, paid fallback or timeout rollback.
