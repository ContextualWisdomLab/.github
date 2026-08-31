"""Serve the librarian-controlled ``orchestrator/free`` review sidecar.

This launcher runs with the vendored ``contextual-orchestrator`` source on
``PYTHONPATH``; it deliberately mirrors ``contextual_orchestrator.review_gateway``
(the org's reference CI sidecar) so that the five provider credentials and the
gateway bearer token enter the process-local KV exactly once, in the same
process that performs model discovery and serves requests. Provincial
credentials never cross a process boundary and are never read from ``os.environ``
at request time — env is bootstrap transport into the KV.

The difference from ``review_gateway.main()`` is the agent pool: discovery runs
in-process (so the KV-backed credentials are visible to it), the zero-cost
("free") routes are collected into a report, and
``scripts/ci/contextual_orchestrator_review_policy.py`` turns that report into a
ZDR-prioritized, provider-family-diverse catalog for ``orchestrator/free``.
Keeping the decision logic in that stdlib-only module lets every branch of the
ZDR policy be tested offline in this repository while ``orchestrator/free``
still resolves from authentically zero-priced models discovered by the
orchestrator itself. This module is exercised at CI runtime only.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
import re
import sys
import threading
from pathlib import Path
from typing import Any


# The vendored server's generic 64 KiB default is intentionally conservative.
# This loopback, bearer-authenticated review sidecar accepts OpenAI's image-input
# request ceiling so repository context can include inline image inputs.
REVIEW_MAX_BODY_BYTES = 512 * 1024 * 1024
# Keep ordinary review turns portable across small zero-cost providers. The
# failing Strix run used 32768 for every call, including its two-word warm-up.
REVIEW_MAX_OUTPUT_TOKENS = 4096
# Provider-neutral sampling: several modern endpoints reject non-default
# temperatures, while 1.0 is the OpenAI-compatible default.
REVIEW_TEMPERATURE = 1.0
# A selected route that cannot answer within ten seconds is not reliable enough
# for a required CI gate. Four-route batches let discovery try a broader but
# still finite catalog while keeping the worst-case provider wait below the
# sidecar's three-minute readiness deadline.
REVIEW_PREFLIGHT_TIMEOUT_SECONDS = 10
# The serving call has the same 120-second transport budget as the Noema review
# gate; startup admission stays short so an unavailable route cannot delay healthz.
REVIEW_SERVING_TIMEOUT_SECONDS = 120
REVIEW_PREFLIGHT_BATCH_SIZE = 4
REVIEW_PREFLIGHT_MAX_TOTAL_ROUTES = 24
REVIEW_PREFLIGHT_PRIMARY_ROUTE_LIMIT = 8
# ADR-0005: a single fixed max_tokens cannot fit every model in a heterogeneous
# pool -- some spend internal reasoning tokens before visible content and need
# more, others have a real completion ceiling a large budget would exceed. The
# base probe is deliberately cheap (16 -- the value this codebase ran with
# before #1436, and independently the floor OpenRouter's own schema documents
# for the deprecated max_tokens field: "some providers enforce a minimum of
# 16"): being wrong is fine here because it is diagnosed and escalated below,
# unlike a single guess that fails outright.
REVIEW_PREFLIGHT_BASE_TOKENS = 16
# Escalated budget used only when the base probe's response was empty because
# choices[0].finish_reason == "length" (OpenAI's documented signature of
# "budget too small", not "candidate unreachable"). Reuses the existing,
# already-proven-working REVIEW_MAX_OUTPUT_TOKENS rather than inventing a new
# number.
REVIEW_PREFLIGHT_ESCALATED_TOKENS = REVIEW_MAX_OUTPUT_TOKENS
# Shared cap on how many candidates in one preflight run may use the
# escalation retry above, so Layer 1's PROBING worst case stays computed and
# bounded. Merged with the batched concurrent preflight below
# (REVIEW_PREFLIGHT_BATCH_SIZE): candidates within one batch of up to
# REVIEW_PREFLIGHT_BATCH_SIZE run concurrently, so a batch's own wall time is
# its slowest candidate, not the sum of all of them -- worst case, a batch
# containing an escalating candidate costs 2 * REVIEW_PREFLIGHT_TIMEOUT_SECONDS
# (base + escalated attempt, sequential within that one candidate's thread),
# not REVIEW_PREFLIGHT_TIMEOUT_SECONDS. With
# REVIEW_PREFLIGHT_MAX_TOTAL_ROUTES=24 candidates in batches of
# REVIEW_PREFLIGHT_BATCH_SIZE=4, that is ceil(24/4)=6 batches; even the fully
# pessimistic bound of every batch needing its worst case is
# 6 * 2 * 10 = 120s (REVIEW_PREFLIGHT_WORST_CASE_SECONDS below), since
# REVIEW_PREFLIGHT_MAX_ESCALATIONS=4 means at most 4 of those 6 batches can
# actually contain an escalating candidate. See
# docs/adr/0005-sidecar-preflight-token-budget.md, Decision section 3 for the
# ADR's own (pre-batching, sequential) 160s derivation of this same shared
# cap's value; batching changes the wall-clock arithmetic, not the cap itself.
#
# FIXED (ContextualWisdomLab/.github#1455, Devin Review finding "Startup
# watchdog preempts valid preflight"): the bound above covers only probing,
# not the discover_all_models() call that runs before it, inside the SAME
# sidecar startup watchdog (contextual_orchestrator_review_sidecar.sh). Both
# phases run sequentially in one process before the server can start
# accepting `/healthz`, so the watchdog must cover their SUM, not either one
# alone -- previously the watchdog was a bare, uncoordinated 180s shell
# constant that only happened to exceed the probing-only figure above by
# coincidence, while the combined real worst case (see
# REVIEW_STARTUP_WATCHDOG_SECONDS below) is larger than that. Verified
# directly against the vendored contextual-orchestrator source at
# ORCHESTRATOR_PIN_SHA (contextual_orchestrator_review_sidecar.sh):
# discover_all_models() makes up to REVIEW_DISCOVERY_MAX_SEQUENTIAL_HTTP_CALLS
# sequential HTTP calls (the shared models.dev fetch; one per
# PROVIDER_MODEL_SOURCES entry with a registered credential -- of the sidecar's
# five bootstrapped secrets, that is openai/openrouter/nvidia_nim/
# nvidia_nim_sub/bytez, since opencode_zen's OPENCODE_ZEN_API_KEY is never one
# of the five secrets the sidecar registers and so it always short-circuits
# with zero calls; and the OpenRouter ZDR endpoint fetch, unconditional), each
# up to REVIEW_DISCOVERY_TIMEOUT_SECONDS. contextual_orchestrator_review_sidecar.sh
# imports REVIEW_STARTUP_WATCHDOG_SECONDS from this module (a stdlib-only,
# dependency-free import) as its watchdog loop bound -- a single source of
# truth so a future change to either phase's constants cannot silently
# desynchronize the two budgets again. #1454 (a base-probe *success* never
# confirms the candidate at the real serving budget, REVIEW_MAX_OUTPUT_TOKENS)
# is a separate, still-open gap this fix does not address.
REVIEW_PREFLIGHT_MAX_ESCALATIONS = 4

# Mirrors contextual_orchestrator.model_discovery.DISCOVERY_TIMEOUT_SECONDS at
# ORCHESTRATOR_PIN_SHA (contextual_orchestrator_review_sidecar.sh) exactly. Not
# imported directly: that module's own dependency tree is only installed after
# the sidecar's vendoring step, while this constant must be readable earlier
# (this module's top-level imports are deliberately stdlib-only). Re-verify
# this mirror whenever ORCHESTRATOR_PIN_SHA moves.
REVIEW_DISCOVERY_TIMEOUT_SECONDS = 15.0
# Verified against the vendored contextual_orchestrator.model_discovery source
# at ORCHESTRATOR_PIN_SHA: discover_all_models() calls, strictly sequentially,
# one shared models.dev fetch (triggered once any source with a registered
# credential declares models_dev_provider_id), then discover_provider_models()
# once per PROVIDER_MODEL_SOURCES entry with a registered credential (skipped
# instantly, no HTTP call, for an entry with none), then one unconditional
# OpenRouter ZDR endpoints fetch. With every one of the sidecar's five
# bootstrapped secrets present (openai, openrouter, nvidia_nim, nvidia_nim_sub,
# bytez -- opencode_zen is never among them), that is 1 (models.dev) + 5
# (providers) + 1 (ZDR) = 7 sequential calls, each independently bounded by
# REVIEW_DISCOVERY_TIMEOUT_SECONDS.
REVIEW_DISCOVERY_MAX_SEQUENTIAL_HTTP_CALLS = 7
REVIEW_DISCOVERY_WORST_CASE_SECONDS = (
    REVIEW_DISCOVERY_MAX_SEQUENTIAL_HTTP_CALLS * REVIEW_DISCOVERY_TIMEOUT_SECONDS
)
# The batched-probing worst case derived in the comment above
# REVIEW_PREFLIGHT_MAX_ESCALATIONS: ceil(REVIEW_PREFLIGHT_MAX_TOTAL_ROUTES /
# REVIEW_PREFLIGHT_BATCH_SIZE) batches, each up to
# 2 * REVIEW_PREFLIGHT_TIMEOUT_SECONDS (one base + one escalated attempt,
# sequential within a single candidate's own thread).
REVIEW_PREFLIGHT_WORST_CASE_SECONDS = (
    -(-REVIEW_PREFLIGHT_MAX_TOTAL_ROUTES // REVIEW_PREFLIGHT_BATCH_SIZE)
) * 2 * REVIEW_PREFLIGHT_TIMEOUT_SECONDS
# Explicit, justified slack beyond the two computed network-bound worst cases
# above, for the parts of startup that formula does not (and should not try
# to) model precisely: Python interpreter/module import overhead, in-memory
# catalog construction and JSON evidence-file writes, and the sidecar shell
# script's own 1-second `/healthz` polling granularity. None of those is
# individually large, but the fix here is specifically about correcting a
# previously-absent deadline, not about shaving margin as tight as possible --
# a generous, explicit constant is preferable to a precise-looking one that
# quietly under-covers real (non-network) startup cost. Deliberately kept
# small relative to the two network-bound terms above so it cannot itself
# mask a future regression in either of them.
REVIEW_STARTUP_HEADROOM_SECONDS = 30
# The single source of truth for the sidecar's startup watchdog. Both startup
# phases (discovery, then batched preflight probing) run sequentially in one
# process before `/healthz` can respond, so the watchdog covering both must be
# their sum, not either phase's own bound alone.
# contextual_orchestrator_review_sidecar.sh imports this exact constant
# (rather than hard-coding its own timeout) so a future change to any input
# constant above automatically propagates to the watchdog, instead of
# silently reintroducing the coordination bug this fixes
# (ContextualWisdomLab/.github#1415, Devin Review "Startup watchdog preempts
# valid preflight").
REVIEW_STARTUP_WATCHDOG_SECONDS = int(
    REVIEW_DISCOVERY_WORST_CASE_SECONDS
    + REVIEW_PREFLIGHT_WORST_CASE_SECONDS
    + REVIEW_STARTUP_HEADROOM_SECONDS
)


class _EscalationBudget:
    """Thread-safe shared counter bounding ADR-0005 escalation retries.

    ADR-0005 documents ``REVIEW_PREFLIGHT_MAX_ESCALATIONS`` as one shared,
    run-wide budget, never per-candidate. The batched concurrent preflight
    below probes several candidates in separate threads at once, so a plain
    ``int`` passed by value between sequential calls -- correct when probing
    is strictly sequential -- cannot coordinate admission safely once
    multiple threads can observe and spend the same budget concurrently.
    This class holds the run's one shared count and reserves a slot
    atomically under a lock, so the cap is a hard invariant regardless of
    thread scheduling.
    """

    def __init__(self, limit: int, used: int = 0) -> None:
        """Start a shared budget at ``used`` (e.g. carried over from a prior stage)."""
        self._limit = limit
        self._used = used
        self._lock = threading.Lock()

    def try_reserve(self) -> bool:
        """Atomically claim one escalation slot; return False once spent."""
        with self._lock:
            if self._used >= self._limit:
                return False
            self._used += 1
            return True

    @property
    def used(self) -> int:
        """Return the total escalations spent so far."""
        with self._lock:
            return self._used


class ReviewPreflightError(RuntimeError):
    """Raised when no selected free provider route is ready for review traffic."""

    def __init__(self, message: str, report: dict[str, object]) -> None:
        """Store the sanitized route report alongside the bounded error message."""
        super().__init__(message)
        self.report = report


def _build_model_client(client_type: Any, *, timeout: int) -> Any:
    """Build a no-retry client with the transport policy for its lifecycle phase."""
    return client_type(
        timeout=timeout,
        max_output_tokens=REVIEW_MAX_OUTPUT_TOKENS,
        max_retries=0,
        temperature=REVIEW_TEMPERATURE,
    )


def _has_text_output(model: object) -> bool:
    """Return whether a discovered model can emit text responses."""
    modalities = getattr(model, "output_modalities", None)
    if modalities is None:
        return False
    if isinstance(modalities, str):
        modalities = (modalities,)
    return not modalities or "text" in {
        str(modality).casefold() for modality in modalities
    }


_DISCOVERY_DIAGNOSTICS_COMPLETE_SENTINEL = "discovery_diagnostics_complete"


def _log_discovery_errors(errors: list[object]) -> None:
    """Print one bounded, secret-free diagnostic per provider discovery failure.

    ``discover_all_models()`` isolates one provider's failure from the
    others by design, but a caller that discards the returned errors cannot
    tell "this provider has zero free models" from "this provider's
    discovery silently failed" -- exactly the ambiguity that made a real
    incident impossible to diagnose from CI logs alone. Each error's
    ``error_code`` is a bounded classification (``http_status_NNN`` /
    ``timeout`` / ``transport_error`` / ``invalid_response``) that never
    carries raw provider response text, so this is safe to print to stderr.

    Always emits a trailing sentinel line, even with zero errors: the sidecar
    shell script's async stream sanitizer processes stderr lines strictly in
    order, so once the sanitizer has passed the sentinel through, every
    discovery-error line printed here is guaranteed to have already reached
    the sanitized file too -- letting the shell script wait for a
    deterministic marker instead of racing a fixed-size or fixed-timeout
    guess at whether the sanitizer has caught up yet.
    """
    for error in errors:
        print(
            f"provider_discovery_failed provider={getattr(error, 'provider_name', 'unknown')} "
            f"code={getattr(error, 'error_code', 'unknown')}",
            file=sys.stderr,
            flush=True,
        )
    print(_DISCOVERY_DIAGNOSTICS_COMPLETE_SENTINEL, file=sys.stderr, flush=True)


def _routable_discovered_models(discovered: list[object] | None) -> list[object]:
    """Drop evidence-only discovery rows before any live-serving selection.

    Evidence-only rows (e.g. the OpenRouter catalog) exist solely to supply
    ZDR evidence for other providers' models; contextual_orchestrator's own
    ``agent_from_discovered()`` refuses to turn one into a serving agent.
    Filtering here keeps that same invariant in this sidecar's selection path,
    which builds its catalog independently rather than calling
    ``agent_from_discovered()`` directly.
    """
    return [model for model in (discovered or []) if not getattr(model, "evidence_only", False)]


def _route_identity(model: object) -> tuple[str, str]:
    """Return the provider/model identity used to bind price evidence."""

    return (
        str(getattr(model, "provider_name", None) or ""),
        str(getattr(model, "model_id", None) or ""),
    )


def _report_rows(
    discovered: list[object], free_route_identities: frozenset[tuple[str, str]]
) -> list[dict[str, object]]:
    """Convert in-process discovered models into price-evidenced report rows.

    Only routes the orchestrator itself marks zero-priced (whole-prompt and
    whole-completion published price equal to zero; never name-implied) are
    admitted to the ``orchestrator/free`` pool. Provider routing metadata is
    read from the discovered model when present and otherwise falls back to the
    org ZDR policy table (``scripts/ci/zdr_policy.py``).

    Args:
        discovered: Selected ``discover_all_models()`` result.
        free_route_identities: Routes the orchestrator attested as zero-priced.

    Returns:
        Price-evidenced rows shaped for
        ``contextual_orchestrator_review_policy.parse_discovery_report``.
    """
    from scripts.ci import zdr_policy

    rows: list[dict[str, object]] = []
    for model in discovered:
        provider = str(getattr(model, "provider_name", None) or "")
        model_id = str(getattr(model, "model_id", None) or "")
        if not provider or not model_id:
            continue
        base_url = str(
            getattr(model, "chat_base_url", None)
            or zdr_policy.PROVIDER_BASE_URLS[provider]
        )
        credential_key = str(
            getattr(model, "credential_name", None)
            or zdr_policy.PROVIDER_CREDENTIAL_NAMES[provider]
        )
        auth_scheme = str(
            getattr(model, "auth_scheme", None)
            or zdr_policy.PROVIDER_AUTH_SCHEMES[provider]
        )
        rows.append(
            {
                "provider": provider,
                "model": model_id,
                "agent_id": str(
                    getattr(model, "agent_id", None) or f"{provider}_{model_id}"
                ),
                "is_free": (provider, model_id) in free_route_identities,
                "prompt_price_per_1k": getattr(model, "prompt_price_per_1k", None),
                "completion_price_per_1k": getattr(
                    model, "completion_price_per_1k", None
                ),
                "currency_code": getattr(model, "currency_code", None),
                "base_url": base_url,
                "credential_key": credential_key,
                "auth_scheme": auth_scheme,
            }
        )
    return rows


def _chat_response_has_text(response: object) -> bool:
    """Return whether an OpenAI-compatible response contains non-empty text."""
    if not isinstance(response, dict):
        return False
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        return False
    first = choices[0]
    if not isinstance(first, dict):
        return False
    message = first.get("message")
    if not isinstance(message, dict):
        return False
    content = message.get("content")
    return isinstance(content, str) and bool(content.strip())


def _safe_http_status(exc: Exception) -> int | None:
    """Return one bounded HTTP status without persisting an exception message."""
    status = getattr(exc, "code", None)
    if type(status) is int and 100 <= status <= 599:
        return status
    return None


def _response_finish_reason(response: object) -> str | None:
    """Return a bounded ``finish_reason`` string from an OpenAI-compatible response.

    Returns ``None`` when no usable ``finish_reason`` is present. A value is
    "unknown" rather than the raw provider string whenever it does not look
    like a real, short, stable enum token (real values are e.g. ``stop``,
    ``length``, ``tool_calls``, ``content_filter``) -- this evidence must
    never become an unbounded copy of arbitrary provider text.
    """
    if not isinstance(response, dict):
        return None
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    first = choices[0]
    if not isinstance(first, dict):
        return None
    finish_reason = first.get("finish_reason")
    if not isinstance(finish_reason, str) or not finish_reason:
        return None
    if len(finish_reason) > 32 or not all(
        character.isalnum() or character == "_" for character in finish_reason
    ):
        return "unknown"
    return finish_reason


def _record_provider_exception(row: dict[str, object], exc: Exception) -> None:
    """Record one sanitized, bounded classification of a provider exception.

    Never overclaims a specific root cause from an HTTP status alone: an
    auth failure (401), rate limit (429), or server error (5xx) is not
    evidence of a token-budget problem, and this codebase has no validated
    signal today (evidence deliberately never carries raw provider error
    text) that distinguishes a genuinely budget-specific rejection from any
    other non-2xx response -- so this records the exception's own sanitized
    type name (or a bounded placeholder when that name is unsafe to log)
    plus an optional numeric HTTP status, identically regardless of which
    probe attempt (base or escalated) raised it. Mutates ``row`` in place.

    Also clears any ``finish_reason``/``reasoning_without_content`` already
    on ``row`` from an EARLIER attempt on the same candidate (a no-op for
    the base probe, which never set them yet, but essential for the
    escalated probe: an exception here means there is no response object at
    all for THIS attempt, so the base attempt's stale diagnostic fields must
    not silently linger and look like they describe the outcome being
    recorded now -- the same mixed-attempt-telemetry problem already fixed
    for the escalated-empty and escalated-success outcomes, closed here too).

    Args:
        row: The in-progress per-route evidence row to update.
        exc: The exception a probe attempt raised.
    """
    row["status"] = "rejected"
    error_type = type(exc).__name__
    row["error_type"] = (
        error_type if error_type.isidentifier() and len(error_type) <= 64 else "provider_error"
    )
    http_status = _safe_http_status(exc)
    if http_status is not None:
        row["http_status"] = http_status
    row.pop("finish_reason", None)
    row.pop("reasoning_without_content", None)


def _response_has_reasoning_without_content(response: object) -> bool:
    """Return whether a response matches the vendored "reasoning, no content" signature.

    Mirrors ``contextual_orchestrator.orchestrator.ModelClient._response_content``'s
    own check exactly (a populated ``message.reasoning`` field with no string
    ``content``) rather than inferring it from ``finish_reason`` -- a reasoning
    model can exhaust its budget mid-reasoning under a ``finish_reason`` other
    than ``"length"`` (provider ``finish_reason`` semantics for this case are
    not verified as uniform across the pool), so ``finish_reason == "length"``
    alone would miss the exact original failure mode this preflight exists to
    diagnose (PR #1436).

    True only when BOTH conditions hold: a populated ``message.reasoning``
    field, AND ``_chat_response_has_text`` is false for this SAME response.
    A normal, complete answer that happens to also disclose a reasoning
    trace alongside real, non-empty content is never "starved" -- checking
    ``reasoning`` alone, with no check that content is actually
    absent/empty, would wrongly flag a genuinely healthy response and
    pollute this preflight's own evidence. Reusing
    ``_chat_response_has_text``'s existing "empty or missing" definition,
    rather than duplicating similar-but-subtly-different logic, keeps the
    two predicates provably consistent: this one can never be true for a
    response the other already accepts as having usable text.
    """
    if not isinstance(response, dict):
        return False
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        return False
    first = choices[0]
    if not isinstance(first, dict):
        return False
    message = first.get("message")
    if not isinstance(message, dict) or not message.get("reasoning"):
        return False
    return not _chat_response_has_text(response)


def _preflight_review_agents(
    agents: list[object],
    *,
    client: Any,
    escalations_used: int = 0,
    escalation_budget: "_EscalationBudget | None" = None,
) -> tuple[list[object], dict[str, object]]:
    """Probe each route with the runtime request contract and keep ready routes.

    ADR-0005: a single fixed ``max_tokens`` cannot fit every model in a
    heterogeneous pool. Each candidate gets one cheap base-budget probe
    (``REVIEW_PREFLIGHT_BASE_TOKENS``); when that specific candidate's
    response is empty for a "budget too small" reason -- either
    ``choices[0].finish_reason == "length"`` (OpenAI's documented signature),
    or the vendored ``ModelClient._response_content``'s own broader signature
    (a populated ``message.reasoning`` with no string ``content``, which a
    reasoning model can hit under a different ``finish_reason`` -- provider
    ``finish_reason`` semantics for this case are not verified as uniform
    across the pool, and this is the exact original failure mode PR #1436
    responded to) -- that *same* candidate is retried once at a larger,
    escalated budget (``REVIEW_PREFLIGHT_ESCALATED_TOKENS``) before being
    marked rejected -- bounded by a shared ``REVIEW_PREFLIGHT_MAX_ESCALATIONS``
    counter, which the ``escalations_used`` argument carries forward across
    calls (not per candidate, and not reset per call): a caller that probes
    two stages of the same preflight run (e.g. ``_preflight_with_fallback``'s
    primary and fallback stages) must pass the previous stage's ending count
    back in here so the two stages share one budget instead of each getting
    its own -- otherwise the computed worst-case bound this counter exists to
    enforce silently doubles. Every other failure class (transport exception,
    non-2xx, or empty content matching neither signature) is not retried: a
    genuinely-down candidate never reaches the escalation path, so it cannot
    produce a false "healthy" read.
    An exception on the escalated attempt (transport failure, auth failure,
    rate limit, server error, or a genuine budget rejection) is recorded via
    ``_record_provider_exception`` -- the SAME sanitized classification the
    base probe uses, regardless of attempt. An HTTP status alone does not
    distinguish "this candidate's real ceiling is below the escalated
    budget" from any other cause (401/429/5xx are not budget evidence); this
    codebase has no validated signal today that does, so it does not invent
    one via an over-specific label.

    The report deliberately records only stable route identity, a bounded
    exception class name, an optional numeric HTTP status, attempt count, and
    a bounded ``finish_reason``. Provider response bodies, exception
    messages, URLs, prompts, and credentials are never copied into evidence.
    ``finish_reason`` and ``reasoning_without_content`` are populated on
    every response-bearing outcome -- success included, not just
    failure/escalation, so future tuning has a real "normal" baseline to
    compare against -- and always describe the same, most recent attempt for
    a route (the base attempt when only one was made; the escalated attempt
    when a second was made) -- never a mix of the two attempts' state. When
    the escalated attempt raises an exception instead of returning a
    response, both fields are absent entirely (there is no response to
    describe) rather than silently retaining the base attempt's values.

    Batched concurrent probing (``_preflight_review_agent_batches``) calls
    this function once per candidate, concurrently, from several threads at
    once within one batch. A plain ``escalations_used`` int passed by value
    cannot coordinate admission safely once multiple threads can observe and
    spend the same budget concurrently, so callers that need cross-thread
    coordination pass a shared ``escalation_budget`` instead; a caller that
    only ever probes sequentially (every direct call in this module's own
    test suite, and any single, unbatched invocation) can keep passing a
    plain ``escalations_used`` int, which is wrapped in a private,
    single-owner budget for the duration of this one call -- identical
    external behavior to before this thread-safety addition.

    Args:
        agents: Selected zero-cost model agents.
        client: Vendored ``ModelClient``-compatible transport.
        escalations_used: Escalations already spent earlier in this same
            preflight run (e.g. by a prior stage), so the shared budget is
            honored across calls rather than restarted at zero. Ignored when
            ``escalation_budget`` is given.
        escalation_budget: A shared, thread-safe budget to coordinate
            admission across concurrent callers. When omitted, a private
            budget seeded from ``escalations_used`` is used instead.

    Returns:
        A pair of viable agents and a sanitized preflight report. The
        report's ``escalations_used`` is the running total including
        ``escalations_used``'s starting value, so a caller chaining another
        stage can pass it straight back in.

    Raises:
        ReviewPreflightError: If no provider route returns usable text.
    """
    budget = escalation_budget or _EscalationBudget(
        REVIEW_PREFLIGHT_MAX_ESCALATIONS, escalations_used
    )
    viable: list[object] = []
    routes: list[dict[str, object]] = []
    for agent in agents:
        row: dict[str, object] = {
            "agent_id": str(getattr(agent, "id", "")),
            "provider": str(getattr(agent, "provider_name", "") or "unknown"),
            "model": str(getattr(agent, "model", "")),
            "attempts": 1,
        }
        base_payload: dict[str, object] = {
            "model": getattr(agent, "model", ""),
            "messages": [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Reply with just 'OK'."},
            ],
            "temperature": REVIEW_TEMPERATURE,
            "max_tokens": REVIEW_PREFLIGHT_BASE_TOKENS,
            "stream": False,
        }
        try:
            response = client.proxy_send_once(agent, "chat/completions", base_payload)
        except Exception as exc:  # noqa: BLE001 - sanitize at the provider boundary
            _record_provider_exception(row, exc)
            routes.append(row)
            continue
        if _chat_response_has_text(response):
            # KNOWN GAP, tracked (not yet fixed) as
            # ContextualWisdomLab/.github#1454: this admits the candidate
            # having only proven it works at REVIEW_PREFLIGHT_BASE_TOKENS
            # (16), never at the real serving budget
            # (REVIEW_MAX_OUTPUT_TOKENS, 4096) main()'s ModelClient actually
            # requests. ADR-0005's own Research (axis 2) already documents
            # that a provider's hard completion-token ceiling is a real,
            # separate-from-reasoning-overhead quantity per model; a
            # candidate whose real ceiling sits strictly between 16 and 4096
            # would pass here and only fail later, on real review traffic.
            # Mitigated in production (not fixed here) by
            # contextual_orchestrator.orchestrator.TaskOrchestrator's own
            # per-request failover/circuit-breaker, which this preflight
            # does not replace.
            row["status"] = "ready"
            # Populated on every outcome, including this most-common,
            # ordinary success path -- not just failure/escalation --  so
            # future tuning has a real "normal" baseline to compare against,
            # not just evidence of what went wrong.
            row["finish_reason"] = _response_finish_reason(response) or "unknown"
            row["reasoning_without_content"] = _response_has_reasoning_without_content(response)
            routes.append(row)
            viable.append(agent)
            continue
        finish_reason = _response_finish_reason(response)
        row["finish_reason"] = finish_reason or "unknown"
        reasoning_without_content = _response_has_reasoning_without_content(response)
        row["reasoning_without_content"] = reasoning_without_content
        budget_signature = finish_reason == "length" or reasoning_without_content
        # KNOWN, ACCEPTED, TRACKED LIMITATION on the escalations_used >=
        # REVIEW_PREFLIGHT_MAX_ESCALATIONS branch below, ContextualWisdomLab/.github#1458
        # (originally documented on ADR-0005, docs/adr/0005-sidecar-preflight-token-budget.md):
        # escalations_used is one shared, first-come-first-served counter for
        # the whole run, consumed in catalog order
        # (build_zdr_prioritized_catalog's (cost_evidence_rank,
        # zdr_attested_rank, provider, model) sort, not random). A
        # later-sorting candidate can be denied its own escalation attempt
        # purely because REVIEW_PREFLIGHT_MAX_ESCALATIONS earlier candidates
        # already claimed the shared budget -- even if it would have been the
        # only one to succeed at REVIEW_PREFLIGHT_ESCALATED_TOKENS.
        # Deliberately not reordered (round-robin/random): a fixed-size
        # shared budget smaller than the candidate pool always has to deny
        # someone an escalation, so reordering only changes who, and picking
        # a specific policy without real telemetry on which candidates
        # actually need escalation would itself be the kind of unjustified
        # heuristic this design rejects elsewhere.
        if not budget_signature or not budget.try_reserve():
            row["status"] = "rejected"
            row["error_type"] = (
                "invalid_chat_response" if not budget_signature else "escalation_budget_exhausted"
            )
            routes.append(row)
            continue
        row["attempts"] = 2
        escalated_payload = dict(base_payload)
        escalated_payload["max_tokens"] = REVIEW_PREFLIGHT_ESCALATED_TOKENS
        try:
            escalated_response = client.proxy_send_once(
                agent, "chat/completions", escalated_payload
            )
        except Exception as exc:  # noqa: BLE001 - sanitize at the provider boundary
            # An HTTP status alone (401 auth, 429 throttle, 5xx server
            # error, ...) is not evidence the escalated *budget* specifically
            # caused the rejection -- only that some request failed. Record
            # the same sanitized classification the base probe uses, rather
            # than the previous "escalated_probe_rejected" label, which
            # over-claimed budget-specific attribution this codebase has no
            # validated signal to actually support.
            _record_provider_exception(row, exc)
            routes.append(row)
            continue
        if _chat_response_has_text(escalated_response):
            row["status"] = "ready"
            row["escalated"] = True
            # Overwrite the base attempt's stale diagnostic fields with the
            # escalated (successful, final) attempt's own state -- otherwise
            # a ready route's evidence would still show the budget-too-small
            # signature that triggered the escalation in the first place,
            # describing a response this route no longer produced.
            row["finish_reason"] = _response_finish_reason(escalated_response) or "unknown"
            row["reasoning_without_content"] = _response_has_reasoning_without_content(
                escalated_response
            )
            routes.append(row)
            viable.append(agent)
            continue
        row["status"] = "rejected"
        row["error_type"] = "invalid_chat_response"
        # Both fields now describe this escalated (2nd, final) attempt,
        # never a mix with the base attempt's state -- see the docstring.
        row["finish_reason"] = _response_finish_reason(escalated_response) or "unknown"
        row["reasoning_without_content"] = _response_has_reasoning_without_content(
            escalated_response
        )
        routes.append(row)

    report: dict[str, object] = {
        "contract": "strix-plain-chat-preflight-v2",
        "probed_count": len(agents),
        "ready_count": len(viable),
        "rejected_count": len(agents) - len(viable),
        "escalations_used": budget.used,
        "escalation_budget": REVIEW_PREFLIGHT_MAX_ESCALATIONS,
        "routes": routes,
    }
    if not viable:
        raise ReviewPreflightError(
            "no provider route passed the Strix plain-chat preflight", report
        )
    return viable, report


def _preflight_review_agent_batches(
    agents: list[object],
    *,
    client: Any,
    escalation_budget: "_EscalationBudget | None" = None,
) -> tuple[list[object], dict[str, object]]:
    """Probe bounded concurrent batches until one batch contains a ready route.

    Candidates are probed ``REVIEW_PREFLIGHT_BATCH_SIZE`` at a time, each in
    its own thread, so a full ``REVIEW_PREFLIGHT_MAX_TOTAL_ROUTES``-candidate
    catalog stays within the sidecar's readiness budget: batch wall time is
    the slowest candidate in that batch, not the sum of all of them. Batches
    themselves still run one after another, and probing stops as soon as one
    batch yields at least one ready route -- a later, unprobed batch can
    never "hide" a route this run already found usable.

    ADR-0005's escalation budget (``REVIEW_PREFLIGHT_MAX_ESCALATIONS``) is
    still one shared, run-wide count, not one per batch or per candidate;
    since several candidates in the same batch can reach the escalation
    decision concurrently, admission is coordinated through
    ``_EscalationBudget``'s lock rather than a plain int, so the cap is never
    exceeded even under concurrency. One consequence of that concurrency:
    ADR-0005's "first-come-first-served in catalog order" framing holds
    strictly only ACROSS batches (which stay sequential); WITHIN one batch,
    whichever candidate's thread reaches the reservation first wins it. This
    changes at most which candidate among a few concurrently-probed ones
    claims a scarce slot -- the shared cap itself is a hard, lock-enforced
    invariant regardless of scheduling.

    Args:
        agents: Selected zero-cost model agents, probed in catalog order.
        client: Vendored ``ModelClient``-compatible transport.
        escalation_budget: A shared budget to coordinate escalation
            admission with another stage (see ``_preflight_with_fallback``).
            A fresh, run-local budget is created when omitted.

    Returns:
        A pair of viable agents (from the first batch with any) and a
        sanitized, aggregated preflight report across every batch attempted.

    Raises:
        ReviewPreflightError: If every batch is exhausted with no viable
            route.
    """
    budget = escalation_budget or _EscalationBudget(REVIEW_PREFLIGHT_MAX_ESCALATIONS)
    attempted_routes: list[dict[str, object]] = []
    attempted_count = 0
    for offset in range(0, len(agents), REVIEW_PREFLIGHT_BATCH_SIZE):
        batch = agents[offset : offset + REVIEW_PREFLIGHT_BATCH_SIZE]
        with ThreadPoolExecutor(max_workers=len(batch)) as executor:
            futures = [
                executor.submit(
                    _preflight_review_agents,
                    [agent],
                    client=client,
                    escalation_budget=budget,
                )
                for agent in batch
            ]
            viable: list[object] = []
            for future in futures:
                try:
                    route_viable, route_report = future.result()
                except ReviewPreflightError as exc:
                    route_viable = []
                    route_report = exc.report
                viable.extend(route_viable)
                attempted_routes.extend(route_report["routes"])
                attempted_count += int(route_report["probed_count"])
        if viable:
            return viable, {
                "contract": "strix-plain-chat-preflight-v2",
                "probed_count": attempted_count,
                "ready_count": len(viable),
                "rejected_count": attempted_count - len(viable),
                "escalations_used": budget.used,
                "escalation_budget": REVIEW_PREFLIGHT_MAX_ESCALATIONS,
                "routes": attempted_routes,
                "batch_size": REVIEW_PREFLIGHT_BATCH_SIZE,
            }
    report: dict[str, object] = {
        "contract": "strix-plain-chat-preflight-v2",
        "probed_count": attempted_count,
        "ready_count": 0,
        "rejected_count": attempted_count,
        "escalations_used": budget.used,
        "escalation_budget": REVIEW_PREFLIGHT_MAX_ESCALATIONS,
        "routes": attempted_routes,
        "batch_size": REVIEW_PREFLIGHT_BATCH_SIZE,
    }
    raise ReviewPreflightError(
        "no provider route passed the Strix plain-chat preflight", report
    )


def _preflight_with_fallback(
    primary_agents: list[object], fallback_agents: list[object], *, client: Any
) -> tuple[list[object], dict[str, object], bool]:
    """Use the priced catalog only after every primary route rejects.

    The two stages -- each itself run through
    ``_preflight_review_agent_batches``'s bounded concurrent batching -- share
    ADR-0005's one ``REVIEW_PREFLIGHT_MAX_ESCALATIONS`` budget for the whole
    preflight run, not one budget each: one ``_EscalationBudget`` is created
    here and passed into both stages, so a run that rejects all primary
    routes and then probes the fallback catalog still spends at most
    ``REVIEW_PREFLIGHT_MAX_ESCALATIONS`` escalations in total across both
    stages combined -- otherwise the computed worst-case bound this counter
    exists to enforce would silently double. Both stages' reports remain in
    the result: the fallback (or sole) stage's report carries the run's
    final, cumulative ``escalations_used``, and ``primary_attempt`` nests the
    primary stage's own report -- including its own ``escalations_used`` --
    whenever a fallback stage ran at all.
    """
    budget = _EscalationBudget(REVIEW_PREFLIGHT_MAX_ESCALATIONS)
    try:
        viable, report = _preflight_review_agent_batches(
            primary_agents, client=client, escalation_budget=budget
        )
        return viable, report, False
    except ReviewPreflightError as primary_error:
        if not fallback_agents:
            raise
        try:
            viable, report = _preflight_review_agent_batches(
                fallback_agents, client=client, escalation_budget=budget
            )
        except ReviewPreflightError as fallback_error:
            fallback_error.report["primary_attempt"] = primary_error.report
            raise
        report["primary_attempt"] = primary_error.report
        report["fallback_reason"] = "primary_routes_unavailable"
        return viable, report, True


def _log_preflight_rejections(report: dict[str, object]) -> None:
    """Print one bounded diagnostic line per rejected preflight route to stderr.

    ``report["routes"]`` rows are already sanitized by ``_preflight_review_agents``
    (stable route identity, a bounded exception class name, an optional numeric
    HTTP status -- never provider response bodies, exception messages, URLs,
    prompts, or credentials). Before this, that bounded evidence reached only
    the ``--preflight-out`` artifact file, invisible in the job log an operator
    reads first, so a real "every free route rejected" failure was
    indistinguishable from any other cause of ``review sidecar preflight
    failed`` in normal CI output. This is printed to stderr (not stdout) so it
    reaches the sidecar's sanitized stderr stream the same way discovery and
    gateway diagnostics already do.
    """
    primary_attempt = report.get("primary_attempt")
    if isinstance(primary_attempt, dict):
        _log_preflight_rejections(primary_attempt)
    routes = report.get("routes")
    if not isinstance(routes, list):
        return
    for row in routes:
        if not isinstance(row, dict) or row.get("status") != "rejected":
            continue
        # Re-validate rather than trust the caller's own sanitization: this
        # print reaches the sidecar's sanitized stderr stream unchanged, so an
        # out-of-contract value here (not a plain identifier) must degrade to
        # a safe placeholder instead of ever being formatted into the line.
        provider_value = row.get("provider")
        provider = (
            provider_value
            if isinstance(provider_value, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,63}", provider_value)
            else "unknown"
        )
        error_type_value = row.get("error_type")
        error_type = (
            error_type_value
            if isinstance(error_type_value, str) and error_type_value.isidentifier() and len(error_type_value) <= 64
            else "UnknownError"
        )
        http_status = row.get("http_status")
        if isinstance(http_status, int) and not isinstance(http_status, bool) and 100 <= http_status <= 599:
            print(
                f"preflight_route_rejected provider={provider} "
                f"error_type={error_type} http_status={http_status}",
                file=sys.stderr,
            )
        else:
            print(
                f"preflight_route_rejected provider={provider} error_type={error_type}",
                file=sys.stderr,
            )


def _write_json(path: str, payload: object) -> None:
    """Write one deterministic UTF-8 JSON evidence file."""
    Path(path).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _bounded_primary_catalog_limit(
    requested_limit: int, *, pool: str, has_free_rows: bool
) -> int:
    """Return the primary-stage route limit within one startup budget."""
    if requested_limit < 1:
        raise ValueError("ORCHESTRATOR_CATALOG_LIMIT must be positive")
    total_limit = min(requested_limit, REVIEW_PREFLIGHT_MAX_TOTAL_ROUTES)
    if pool == "auto" and has_free_rows:
        return min(total_limit, REVIEW_PREFLIGHT_PRIMARY_ROUTE_LIMIT)
    return total_limit


def _bounded_fallback_catalog_limit(requested_limit: int, *, primary_count: int) -> int:
    """Return remaining priced-fallback capacity after primary selection."""
    if requested_limit < 1:
        raise ValueError("ORCHESTRATOR_CATALOG_LIMIT must be positive")
    total_limit = min(requested_limit, REVIEW_PREFLIGHT_MAX_TOTAL_ROUTES)
    if primary_count < 0 or primary_count > total_limit:
        raise ValueError("primary route count exceeds the preflight budget")
    return total_limit - primary_count


def _catalog_family_cap() -> int:
    """Return the configured family cap without narrowing the bounded default."""
    return int(
        os.environ.get(
            "ORCHESTRATOR_CATALOG_FAMILY_CAP",
            str(REVIEW_PREFLIGHT_MAX_TOTAL_ROUTES),
        )
    )


def _with_discovery_counts(
    report: dict[str, object],
    rows: list[dict[str, Any]],
    *,
    provider_family: Any,
) -> dict[str, object]:
    """Copy a stage report while restoring full discovery-tier counts.

    ``free_family_diversity`` is recomputed here from the full discovery-wide
    ``rows``, not trusted from the stage report: the primary ``auto``-pool
    stage may have selected only ZDR-admitted free rows (undercounting
    diversity whenever ``--require-zdr`` excludes some free routes) and the
    priced-fallback stage selects only priced rows (so its own internally
    computed diversity is always zero) -- either stage report's
    ``free_family_diversity``, as returned by ``build_zdr_prioritized_catalog``
    from whatever narrower row set it was given, would otherwise contradict
    that field's documented "among *all* discovered free routes" contract.
    """
    enriched = dict(report)
    enriched.update(
        {
            "total_routes": len(rows),
            "total_free_routes": sum(row.get("cost_evidence") == "free" for row in rows),
            "total_priced_routes": sum(row.get("cost_evidence") == "priced" for row in rows),
            "total_unknown_routes": sum(row.get("cost_evidence") == "unknown" for row in rows),
            "free_family_diversity": len(
                {
                    provider_family(str(row["provider"]))
                    for row in rows
                    if row.get("cost_evidence") == "free"
                }
            ),
        }
    )
    return enriched


def _zdr_admitted_rows(
    rows: list[dict[str, Any]],
    *,
    require_zdr: bool,
    zdr_endpoints: frozenset[str],
    checker: Any,
) -> list[dict[str, Any]]:
    """Return rows that can enter the selected privacy boundary."""
    if not require_zdr:
        return list(rows)
    return [
        row
        for row in rows
        if checker(
            str(row["provider"]),
            model=str(row["model"]),
            zdr_endpoints=zdr_endpoints,
        )
    ]


def _load_temporary_agents(
    path: str, catalog_agents: list[dict[str, Any]], *, loader: Any
) -> list[object]:
    """Load one transient catalog and remove it on every exit path."""
    catalog_path = Path(path)
    _write_json(str(catalog_path), {"agents": catalog_agents})
    try:
        return list(loader(str(catalog_path)))
    finally:
        catalog_path.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    """Bootstrap the KV, discover and preflight free models, then serve.

    Args:
        argv: CLI arguments (``--host``, ``--port``, ``--auth-token``,
            ``--catalog-out``, ``--report-out``, ``--preflight-out``,
            ``--discovery-out``, ``--zdr-endpoints``).

    Returns:
        0 when the server exits cleanly; 1 on any configuration error.

    Raises:
        SystemExit: If the vendored library is missing, no provider credential
            is in the KV, no free model was discovered, no route passes runtime
            preflight, or no auth token is available — the sidecar must fail
            closed rather than boot a mock or unaudited pool.
    """
    parser = argparse.ArgumentParser(
        description="Serve the contextual-orchestrator review sidecar."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18080)
    parser.add_argument(
        "--auth-token",
        default="",
        help="Explicit bearer token; else resolve from the KV",
    )
    parser.add_argument(
        "--discovery-out",
        required=True,
        help="Path to write the free-only discovery report JSON",
    )
    parser.add_argument(
        "--catalog-out", required=True, help="Path to write the agents catalog JSON"
    )
    parser.add_argument(
        "--report-out", required=True, help="Path to write the policy evidence JSON"
    )
    parser.add_argument(
        "--preflight-out",
        required=True,
        help="Path to write sanitized runtime preflight JSON",
    )
    parser.add_argument(
        "--zdr-endpoints",
        default=None,
        help="Optional OpenRouter /api/v1/endpoints/zdr JSON path",
    )
    parser.add_argument("--require-zdr", action="store_true")
    parser.add_argument("--pool", choices=("free", "auto"), default="free")
    args = parser.parse_args(argv)

    from contextual_orchestrator.credentials import get_credential
    from contextual_orchestrator.chat_capability import is_general_chat_agent_model_id
    from contextual_orchestrator.model_discovery import (
        discover_all_models,
        free_discovered_models,
    )
    from contextual_orchestrator.orchestrator import (
        ModelClient,
        TaskOrchestrator,
        load_agents,
    )
    from contextual_orchestrator.review_gateway import (
        REVIEW_AUTH_CREDENTIAL_NAME,
        register_review_credentials,
    )
    from contextual_orchestrator.server import SecurityConfig, serve
    from scripts.ci.contextual_orchestrator_review_policy import (
        PolicyError,
        _load_zdr_endpoints,
        build_zdr_prioritized_catalog,
        is_zdr_model,
        parse_discovery_report,
        provider_family,
    )

    registered = register_review_credentials(os.environ)
    auth_token = args.auth_token or get_credential(REVIEW_AUTH_CREDENTIAL_NAME)
    if not auth_token:
        raise SystemExit(
            "review sidecar requires an explicit --auth-token or the "
            f"KV credential {REVIEW_AUTH_CREDENTIAL_NAME!r}"
        )
    if not any(
        name.startswith(("BYTEZ_", "NVIDIA_", "OPENROUTER_", "OPENAI_"))
        for name in registered
    ):
        raise SystemExit(
            "review sidecar requires at least one provider credential in the KV"
        )

    try:
        discovered, discovery_errors = discover_all_models()
    except Exception as exc:  # pragma: no cover - provider/networking failure is runtime-only
        raise SystemExit(f"review sidecar discovery failed: {exc}") from exc
    _log_discovery_errors(discovery_errors)
    routable_discovered = _routable_discovered_models(discovered)
    free_models = list(free_discovered_models(routable_discovered)) if routable_discovered else []
    free_route_identities = frozenset(_route_identity(model) for model in free_models)
    selected_models = []
    for model in routable_discovered:
        model_id = getattr(model, "model_id", "")
        if not is_general_chat_agent_model_id(model_id) or not _has_text_output(model):
            continue
        if args.pool == "free" and _route_identity(model) not in free_route_identities:
            continue
        selected_models.append(model)
    if not selected_models:
        raise SystemExit(
            f"review sidecar discovered no eligible models; orchestrator/{args.pool} would fail closed"
        )

    rows = _report_rows(selected_models, free_route_identities)
    _write_json(args.discovery_out, {"models": rows})
    zdr_endpoints = _load_zdr_endpoints(args.zdr_endpoints)
    normalized_rows = parse_discovery_report({"models": rows})
    free_rows = [row for row in normalized_rows if row.get("cost_evidence") == "free"]
    priced_rows = [
        row for row in normalized_rows if row.get("cost_evidence") == "priced"
    ]
    admitted_free_rows = _zdr_admitted_rows(
        free_rows,
        require_zdr=args.require_zdr,
        zdr_endpoints=zdr_endpoints,
        checker=is_zdr_model,
    )
    admitted_priced_rows = _zdr_admitted_rows(
        priced_rows,
        require_zdr=args.require_zdr,
        zdr_endpoints=zdr_endpoints,
        checker=is_zdr_model,
    )
    requested_catalog_limit = int(os.environ.get("ORCHESTRATOR_CATALOG_LIMIT", "24"))
    primary_limit = _bounded_primary_catalog_limit(
        requested_catalog_limit, pool=args.pool, has_free_rows=bool(admitted_free_rows)
    )
    primary_rows = (
        (admitted_free_rows or admitted_priced_rows)
        if args.pool == "auto"
        else normalized_rows
    )
    result = build_zdr_prioritized_catalog(
        primary_rows,
        limit=primary_limit,
        family_cap=_catalog_family_cap(),
        zdr_endpoints=zdr_endpoints,
        require_zdr=args.require_zdr,
        pool=args.pool,
    )
    result["report"] = _with_discovery_counts(
        result["report"], normalized_rows, provider_family=provider_family
    )
    Path(args.catalog_out).write_text(
        json.dumps({"agents": result["agents"]}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _write_json(args.report_out, result["report"])

    agents = load_agents(args.catalog_out)
    primary_report = result["report"]
    fallback_result = None
    fallback_agents: list[object] = []
    fallback_limit = _bounded_fallback_catalog_limit(
        requested_catalog_limit, primary_count=len(result["agents"])
    )
    if (
        args.pool == "auto"
        and admitted_free_rows
        and admitted_priced_rows
        and fallback_limit
    ):
        try:
            fallback_result = build_zdr_prioritized_catalog(
                admitted_priced_rows,
                limit=fallback_limit,
                family_cap=_catalog_family_cap(),
                zdr_endpoints=zdr_endpoints,
                require_zdr=args.require_zdr,
                pool="auto",
            )
        except PolicyError:
            fallback_result = None
        if fallback_result is not None:
            fallback_result["report"] = _with_discovery_counts(
                fallback_result["report"], normalized_rows, provider_family=provider_family
            )
            fallback_result["report"]["primary_selected_count"] = primary_report[
                "selected_count"
            ]
            fallback_result["report"]["primary_selection"] = primary_report["selected"]
            fallback_agents = _load_temporary_agents(
                f"{args.catalog_out}.priced",
                fallback_result["agents"],
                loader=load_agents,
            )
    client = _build_model_client(
        ModelClient, timeout=REVIEW_PREFLIGHT_TIMEOUT_SECONDS
    )
    try:
        agents, preflight_report, fallback_used = _preflight_with_fallback(
            agents, fallback_agents, client=client
        )
    except ReviewPreflightError as exc:
        _write_json(args.preflight_out, exc.report)
        _log_preflight_rejections(exc.report)
        raise SystemExit(f"review sidecar preflight failed: {exc}") from None
    if fallback_used and fallback_result is not None:
        Path(args.catalog_out).write_text(
            json.dumps({"agents": fallback_result["agents"]}, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        result = fallback_result
        result["report"]["fallback_reason"] = "primary_routes_unavailable"
        _write_json(args.report_out, result["report"])
    _write_json(args.preflight_out, preflight_report)

    client = _build_model_client(
        ModelClient, timeout=REVIEW_SERVING_TIMEOUT_SECONDS
    )
    orchestrator = TaskOrchestrator(agents, client=client)
    serve(
        orchestrator,
        host=args.host,
        port=args.port,
        security=SecurityConfig(
            auth_token=auth_token,
            max_body_bytes=REVIEW_MAX_BODY_BYTES,
        ),
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
