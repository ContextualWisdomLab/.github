# DeepSeek Preflight Resilience Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep a DeepSeek route eligible after one transient HTTP 502 and stop the review sidecar from cutting off slow reasoning-model responses at the vendored client's 90-second default.

**Architecture:** Preserve contextual-orchestrator as the owner of HTTP error classification, jittered backoff, and retry behavior. The central review launcher will call `ModelClient.proxy_send()` only for idempotent preflight probes, configure exactly one transient retry, and set `timeout=None` on both preflight and serving clients; token-budget escalation remains a separate route-local semantic attempt. Provider-account lanes continue to start concurrently, and completion timing, retry count, or provider name must not become admission or routing authority.

**Tech Stack:** Python 3.12, `contextual_orchestrator.orchestrator.ModelClient`, pytest, AST-based source-contract tests, GitHub Actions.

**Spec:** DiagramWeave Actions run `33554858825`, job `100013111840`, step 12; contextual-orchestrator PR `#971`; central review-control PR `#1629`.

## Global Constraints

- The central review pool remains fail-closed `orchestrator/free`; this repair does not admit priced or unevidenced routes.
- Retry only failures already classified transient by contextual-orchestrator; authentication, validation, malformed response, and policy errors remain terminal.
- Preflight transport retry budget is exactly `1`; it is independent of the existing one-time output-token escalation.
- Do not copy provider response bodies, exception messages, credentials, or prompts into persisted evidence.
- Do not introduce route caps, provider ranking, completion-time ranking, or a shared first-come retry quota.
- Both preflight and serving inference clients must carry `timeout=None`; workflow/job deadlines remain the outer operational cancellation boundary.

---

### Task 1: Pin the failing runtime contracts

**Files:**
- Create: `tests/test_contextual_orchestrator_review_transient_preflight.py`
- Test: `tests/test_contextual_orchestrator_review_transient_preflight.py`

**Interfaces:**
- Consumes: `_preflight_review_agents(agents: list[object], *, client: Any)` from `scripts/ci/contextual_orchestrator_review_launcher.py`.
- Produces: executable contracts proving retry-enabled preflight dispatch, terminal 401 behavior, and no inference deadline in both `ModelClient` constructors.

- [ ] **Step 1: Write the failing 502 recovery test**

```python
def test_preflight_recovers_deepseek_route_after_transient_502() -> None:
    namespace = _load_launcher()
    agent = SimpleNamespace(
        id="nvidia_nim_deepseek_v4_flash",
        provider_name="nvidia_nim",
        model="deepseek-ai/deepseek-v4-flash-0731",
    )
    client = _RetryingProbeClient([_http_error(502), _openai_text("OK")])

    viable, report = namespace["_preflight_review_agents"]([agent], client=client)

    assert viable == [agent]
    assert client.retrying_calls == 1
    assert client.one_shot_calls == 0
    assert client.transport_attempts == 2
    assert report["routes"][0]["transport_retry_budget"] == 1
```

- [ ] **Step 2: Write the terminal-error and constructor tests**

```python
def test_preflight_does_not_retry_permanent_auth_failure() -> None:
    namespace = _load_launcher()
    client = _RetryingProbeClient([_http_error(401)])
    with pytest.raises(namespace["ReviewPreflightError"]) as excinfo:
        namespace["_preflight_review_agents"]([_agent()], client=client)
    assert client.transport_attempts == 1
    assert excinfo.value.report["routes"][0]["http_status"] == 401


def test_review_clients_have_no_inference_deadline_and_one_transient_retry() -> None:
    calls = _review_model_client_calls()
    assert len(calls) == 2
    assert all(_kw(call, "timeout").value is None for call in calls)
    preflight = next(call for call in calls if _kw(call, "max_retries") is not None)
    assert isinstance(_kw(preflight, "max_retries"), ast.Name)
    assert _kw(preflight, "max_retries").id == "REVIEW_PREFLIGHT_TRANSIENT_RETRIES"
```

- [ ] **Step 3: Run the tests and verify RED**

Run: `python -m pytest -q tests/test_contextual_orchestrator_review_transient_preflight.py`

Expected: FAIL because current code calls `proxy_send_once`, records a single 502 as rejected, configures `max_retries=0`, and omits `timeout=None`.

### Task 2: Reuse the orchestrator retry policy and remove the inference cap

**Files:**
- Modify: `scripts/ci/contextual_orchestrator_review_launcher.py`
- Test: `tests/test_contextual_orchestrator_review_transient_preflight.py`
- Test: `tests/test_contextual_orchestrator_review_runtime_preflight.py`
- Test: `tests/test_contextual_orchestrator_review_preflight_concurrency.py`

**Interfaces:**
- Consumes: `ModelClient.proxy_send(agent, endpoint, payload)` and contextual-orchestrator's existing transient classifier/backoff.
- Produces: `_send_preflight_request(client: Any, agent: object, payload: dict[str, object]) -> object` and `REVIEW_PREFLIGHT_TRANSIENT_RETRIES = 1`.

- [ ] **Step 1: Add the bounded transport contract**

```python
REVIEW_PREFLIGHT_TRANSIENT_RETRIES = 1


def _send_preflight_request(
    client: Any, agent: object, payload: dict[str, object]
) -> object:
    """Use the client's bounded transient-retry path for an idempotent probe."""
    retrying_send = getattr(client, "proxy_send", None)
    if callable(retrying_send):
        return retrying_send(agent, "chat/completions", payload)
    return client.proxy_send_once(agent, "chat/completions", payload)
```

The fallback preserves existing deterministic test doubles and compatibility clients; the real vendored `ModelClient` always takes the `proxy_send` branch.

- [ ] **Step 2: Route both semantic probe attempts through the helper**

Replace both base and escalated `client.proxy_send_once(...)` calls in `_preflight_review_agent` with `_send_preflight_request(...)`. Add `"transport_retry_budget": REVIEW_PREFLIGHT_TRANSIENT_RETRIES` to each route row. Keep `row["attempts"]` as the semantic prompt-attempt count so a token-budget escalation remains distinguishable from transport retries hidden inside `ModelClient`.

- [ ] **Step 3: Configure the two clients**

```python
client = ModelClient(
    timeout=None,
    max_output_tokens=REVIEW_MAX_OUTPUT_TOKENS,
    max_retries=REVIEW_PREFLIGHT_TRANSIENT_RETRIES,
    temperature=REVIEW_TEMPERATURE,
)
```

Use `timeout=None` on the serving `ModelClient` as well, without overriding its ordinary bounded retry policy.

- [ ] **Step 4: Run focused GREEN verification**

Run:

```bash
python -m pytest -q \
  tests/test_contextual_orchestrator_review_transient_preflight.py \
  tests/test_contextual_orchestrator_review_runtime_preflight.py \
  tests/test_contextual_orchestrator_review_preflight_concurrency.py \
  tests/test_contextual_orchestrator_review_sidecar_contract.py
python -m compileall -q scripts/ci/contextual_orchestrator_review_launcher.py
python -m interrogate --fail-under 100 scripts/ci/contextual_orchestrator_review_launcher.py
```

Expected: all tests and documentation coverage pass. Existing evidence order, provider-account concurrency, token escalation, secret redaction, and free-only contracts remain unchanged.

### Task 3: Revalidate the protected integration path

**Files:**
- Modify: PR `ContextualWisdomLab/.github#1629` description/evidence only after the source commit exists.
- Observe: contextual-orchestrator PR `ContextualWisdomLab/contextual-orchestrator#971`.
- Re-run: the affected DiagramWeave review workflow after the owning fixes are available on the consumed ref.

**Interfaces:**
- Consumes: exact source head produced by Task 2 and GitHub check-runs bound to that SHA.
- Produces: current-head test evidence and an explicit downstream revalidation requirement; no stale-head status is transferred.

- [ ] **Step 1: Confirm the exact branch head and changed files**

Run: `git diff --check && git status --short && git rev-parse HEAD`

Expected: only the launcher, focused regression test, and this plan are publishable changes; no temporary repair workflow or driver remains.

- [ ] **Step 2: Let protected checks run on the exact head**

Required evidence includes the repository's normal test, security, supply-chain, and review gates. Queued or predecessor-head checks do not count as GREEN.

- [ ] **Step 3: Re-run the DiagramWeave failure path**

Expected runtime evidence:

```text
nvidia_nim / deepseek-v4-flash: a first transient 502 may recover inside one preflight call
reasoning routes: no launcher-imposed 90-second inference timeout
preflight: provider-account lanes start concurrently and evidence remains in catalog order
```

Do not claim the incident closed until an unchanged consumed head produces terminal workflow evidence.
