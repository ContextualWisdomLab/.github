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
ZDR-prioritized, credential-account-diverse catalog for ``orchestrator/free``.
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
# A real review may legitimately run far beyond two minutes.  Keep the short
# timeout confined to startup admission; the outer Noema request/job deadline
# remains the serving safety boundary.
REVIEW_SERVING_TIMEOUT_SECONDS = 9000
REVIEW_PREFLIGHT_BATCH_SIZE = 4
REVIEW_PREFLIGHT_MAX_TOTAL_ROUTES = 24
REVIEW_PREFLIGHT_PRIMARY_ROUTE_LIMIT = 8
# Bound the already-admitted serving catalog so immediate-error failover work
# cannot grow with discovery. The outer Noema request and workflow job remain
# the wall-clock safety boundaries.
REVIEW_SERVING_MAX_CANDIDATES = 10
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
# escalation RESCUE retry below (a FAILED base probe with a "budget too
# small" signature). This budget's purpose is deliberately narrow and
# scarce: rescuing an atypical failure, not confirming an already-successful
# candidate -- see REVIEW_PREFLIGHT_MAX_CONFIRMATIONS below for that
# separate, much more common concern, and why it needs its own budget.
# Merged with the batched concurrent preflight below
# (REVIEW_PREFLIGHT_BATCH_SIZE): candidates within one batch of up to
# REVIEW_PREFLIGHT_BATCH_SIZE run concurrently, so a batch's own wall time is
# its slowest candidate, not the sum of all of them -- worst case, a batch
# containing a candidate that makes a second attempt (rescue OR confirmation)
# costs 2 * REVIEW_PREFLIGHT_TIMEOUT_SECONDS (base + second attempt,
# sequential within that one candidate's own thread), not
# REVIEW_PREFLIGHT_TIMEOUT_SECONDS. Crucially, this per-batch bound holds
# regardless of HOW MANY candidates in that one batch make a second attempt
# (concurrency means the batch's wall time is its slowest member, never a
# sum of every member), and therefore holds regardless of either second-
# attempt budget's specific cap -- REVIEW_PREFLIGHT_MAX_CONFIRMATIONS below
# deliberately has a much larger cap than this one without changing this
# arithmetic at all. With REVIEW_PREFLIGHT_MAX_TOTAL_ROUTES=24 candidates in
# batches of REVIEW_PREFLIGHT_BATCH_SIZE=4, that is ceil(24/4)=6 batches, so
# the worst case is 6 * 2 * 10 = 120s (REVIEW_PREFLIGHT_WORST_CASE_SECONDS
# below) -- already the fully pessimistic case of every batch needing its
# worst case, true independent of either budget's cap value. See
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
# REVIEW_STARTUP_WATCHDOG_SECONDS below) is larger than that. discover_all_models()
# makes up to REVIEW_DISCOVERY_MAX_SEQUENTIAL_HTTP_CALLS sequential-call-
# equivalents against the pinned contextual-orchestrator revision, each up to
# REVIEW_DISCOVERY_TIMEOUT_SECONDS -- see that constant's own comment below
# for the full, itemized enumeration (shared Models.dev fetch, per-source
# retries, OpenRouter's extra calls, and two trailing global calls) verified
# directly against ORCHESTRATOR_PIN_SHA; do not restate the count here, to
# avoid a second "verified" claim silently drifting from the real one below.
# contextual_orchestrator_review_sidecar.sh imports REVIEW_STARTUP_WATCHDOG_SECONDS
# from this module (a stdlib-only,
# dependency-free import) as its watchdog loop bound -- a single source of
# truth so a future change to either phase's constants cannot silently
# desynchronize the two budgets again. #1454 (a base-probe *success* never
# confirms the candidate at the real serving budget, REVIEW_MAX_OUTPUT_TOKENS)
# was FIXED (Devin Review, "Serving-incompatible routes pass startup"): a
# base-probe success now always draws one confirming attempt at
# REVIEW_PREFLIGHT_ESCALATED_TOKENS before being admitted, exactly like a
# base-probe failure's existing rescue attempt.
#
# FIXED (ContextualWisdomLab/.github#1415, Devin Review finding "Later
# healthy routes cannot start"): that #1454 fix originally drew the
# confirmation attempt from this SAME counter, exactly like a base-probe
# failure's rescue attempt. That was wrong: this counter is sized (4) for
# the RARE rescue case, but every single successful base probe now needs a
# confirmation -- the COMMON case, not the rare one. As few as
# REVIEW_PREFLIGHT_MAX_ESCALATIONS candidates in the very first batch(es)
# each succeeding their base probe could reserve every slot for their own
# confirmations, permanently denying every later candidate's confirmation
# regardless of merit -- defeating the entire point of batching up to
# REVIEW_PREFLIGHT_MAX_TOTAL_ROUTES candidates to find one usable route.
# Confirmation now draws from its own separate
# REVIEW_PREFLIGHT_MAX_CONFIRMATIONS budget (see below); this counter keeps
# its original, narrower rescue-only purpose and its original cap. Per-
# candidate worst case stays at most one base + one second attempt either
# way (confirmation OR rescue, never both on the same candidate), so the
# REVIEW_PREFLIGHT_WORST_CASE_SECONDS/REVIEW_STARTUP_WATCHDOG_SECONDS
# arithmetic derived below is unchanged by either fix -- see this comment's
# opening paragraph for why the formula never depended on either budget's
# specific cap value in the first place.
REVIEW_PREFLIGHT_MAX_ESCALATIONS = 4

# FIXED (ContextualWisdomLab/.github#1415, Devin Review "Later healthy
# routes cannot start"): the mandatory serving-budget CONFIRMATION of an
# already-successful base probe (see REVIEW_PREFLIGHT_MAX_ESCALATIONS above
# for the full incident) needs its own budget, separate from that counter's
# original, narrow "rescue a failed base probe" purpose. Since confirmation
# runs for EVERY successful base probe -- the common case, not a rare one --
# this budget is sized to REVIEW_PREFLIGHT_MAX_TOTAL_ROUTES: the maximum
# number of candidates this preflight run can ever probe across BOTH stages
# combined (the primary catalog and, when it runs, the priced-fallback
# catalog -- see _preflight_with_fallback, which shares one instance of this
# budget across both stages exactly like it already does for
# REVIEW_PREFLIGHT_MAX_ESCALATIONS). That size guarantees even the fully
# pessimistic case -- every candidate ever probed in this run succeeds its
# base probe -- still gets its required confirmation shot; this is not an
# unbounded allowance, it is bounded by the same total-route cap this
# preflight can never exceed regardless of how this constant is set. As
# reasoned above, sizing this budget larger than
# REVIEW_PREFLIGHT_MAX_ESCALATIONS does not change
# REVIEW_PREFLIGHT_WORST_CASE_SECONDS: each batch's wall time is bounded by
# its slowest candidate (at most one base + one second attempt), regardless
# of how many candidates in that batch actually make a second attempt or
# which of the two budgets backs it.
REVIEW_PREFLIGHT_MAX_CONFIRMATIONS = REVIEW_PREFLIGHT_MAX_TOTAL_ROUTES

# Mirrors contextual_orchestrator.model_discovery.DISCOVERY_TIMEOUT_SECONDS at
# ORCHESTRATOR_PIN_SHA (contextual_orchestrator_review_sidecar.sh) exactly. Not
# imported directly: that module's own dependency tree is only installed after
# the sidecar's vendoring step, while this constant must be readable earlier
# (this module's top-level imports are deliberately stdlib-only). Re-verify
# this mirror whenever ORCHESTRATOR_PIN_SHA moves.
REVIEW_DISCOVERY_TIMEOUT_SECONDS = 15.0
# FIXED (ContextualWisdomLab/.github#1415, Devin Review finding "Discovery-
# time budget undercounts known retries"): the previous count of 7 verified
# only that discover_all_models() makes one call per registered source plus
# one unconditional extra -- it never checked whether any of those calls can
# themselves retry, or whether the pinned revision makes calls beyond that
# simple per-source loop. Re-verified line-by-line against the vendored
# contextual_orchestrator.model_discovery source at ORCHESTRATOR_PIN_SHA
# (fetched and read at that exact commit, not assumed from an older or newer
# revision), counting every sequential HTTP call discover_all_models() can
# make in its real worst case, with every one of the sidecar's five
# bootstrapped credentials present (openai, openrouter, nvidia_nim,
# nvidia_nim_sub, bytez -- opencode_zen's OPENCODE_ZEN_API_KEY is never one of
# the five secrets the sidecar registers, so it always short-circuits with
# zero calls):
#
# Named sub-budgets below (rather than one opaque literal) so a test can
# reconstruct and re-justify each piece of this enumeration independently --
# see test_contextual_orchestrator_review_runtime_preflight.py's
# test_startup_watchdog_covers_a_retry_heavy_discovery_reconstruction.
#
#   (a) Shared Models.dev fetch (_fetch_models_dev_metadata, triggered once
#       because openai/nvidia_nim/nvidia_nim_sub declare
#       models_dev_provider_id and are credentialed): up to
#       _MODELS_DEV_FETCH_ATTEMPTS = 3 sequential attempts, not the 1 the old
#       count assumed -- a lone transient failure (this endpoint is known to
#       reject urllib's default user agent, see that constant's own
#       docstring) is retried up to twice more.
REVIEW_DISCOVERY_MODELS_DEV_MAX_ATTEMPTS = 3
#   (b) Each of the five credentialed sources' own primary model-list fetch
#       (discover_provider_models): up to 2 attempts each -- a full
#       REVIEW_DISCOVERY_TIMEOUT_SECONDS primary attempt PLUS one
#       _DISCOVERY_RETRY_TIMEOUT_SECONDS=5.0s retry on a transient failure
#       (is_transient_error), not the unretried single attempt the old count
#       assumed. Five sources: openai, openrouter, nvidia_nim,
#       nvidia_nim_sub, bytez -- opencode_zen's OPENCODE_ZEN_API_KEY is never
#       one of the five secrets the sidecar registers, so it always short-
#       circuits with zero calls and is excluded from this count.
REVIEW_DISCOVERY_CREDENTIALED_SOURCE_COUNT = 5
REVIEW_DISCOVERY_SOURCE_MAX_ATTEMPTS = 2
#   (c) OpenRouter-only extra calls inside discover_provider_models, beyond
#       its own primary listing call already counted in (b): one ZDR-
#       endpoints fetch (_OPENROUTER_ZDR_ENDPOINTS_URL, no retry -- the old
#       count's "unconditional ZDR fetch" line item, kept here) + one
#       provider-policies fetch (_OPENROUTER_PROVIDER_POLICIES_URL, no
#       retry, entirely missing from the old count).
REVIEW_DISCOVERY_OPENROUTER_SINGLE_EXTRA_CALLS = 2
#       Plus one concurrent (ThreadPoolExecutor, <=8 workers) endpoint-feed
#       fetch per currently zero-priced OpenRouter model
#       (_openrouter_free_model_endpoints, also entirely missing from the
#       old count): wall-clock bounded by ceil(free_model_count / 8) rounds,
#       each up to REVIEW_DISCOVERY_TIMEOUT_SECONDS. Verified live against
#       OpenRouter's public /api/v1/models catalog (2026-08-31): 21 models
#       currently report zero prompt AND completion price (ceil(21/8) = 3
#       rounds today). The pinned code itself does not bound this count, so
#       rather than hand-waving it as "1 more call" (the old count's mistake
#       for a different item) or leaving it fully unbounded, this budgets 5
#       call-equivalent rounds -- headroom for up to 40 free models, close
#       to double today's observed count -- as an explicit, documented
#       assumption, not a code-enforced bound; re-verify this headroom if
#       OpenRouter's free-tier catalog grows materially past that.
REVIEW_DISCOVERY_OPENROUTER_FREE_ENDPOINT_ROUND_CAP = 5
#   (d) Two trailing global calls discover_all_models() itself makes once
#       per run, strictly after every source's loop above, entirely absent
#       from the old count: _openrouter_zdr_model_ids() (a SEPARATE fetch of
#       the same _OPENROUTER_ZDR_ENDPOINTS_URL as (c) -- not a cache hit;
#       this one runs unconditionally, even with no OpenRouter credential
#       registered) + openrouter_paid_inference_available() (the credits
#       check, gated on an OpenRouter credential being registered, true in
#       this worst case). Neither has a retry.
REVIEW_DISCOVERY_TRAILING_GLOBAL_CALLS = 2
# FIXED (ContextualWisdomLab/.github#1415, Devin Review finding "Discovery-
# time budget undercounts known retries"): the previous count of 7 verified
# only that discover_all_models() makes one call per registered source plus
# one unconditional extra -- it never checked whether any of those calls can
# themselves retry, or whether the pinned revision makes calls beyond that
# simple per-source loop. Re-verified line-by-line against the vendored
# contextual_orchestrator.model_discovery source at ORCHESTRATOR_PIN_SHA
# (fetched and read at that exact commit, not assumed from an older or newer
# revision) -- see (a)-(d) above for the full itemized enumeration. Total:
# 3 + 5*2 + 2 + 5 + 2 = 22 sequential-call-equivalents, each independently
# bounded by REVIEW_DISCOVERY_TIMEOUT_SECONDS.
REVIEW_DISCOVERY_MAX_SEQUENTIAL_HTTP_CALLS = (
    REVIEW_DISCOVERY_MODELS_DEV_MAX_ATTEMPTS
    + REVIEW_DISCOVERY_CREDENTIALED_SOURCE_COUNT * REVIEW_DISCOVERY_SOURCE_MAX_ATTEMPTS
    + REVIEW_DISCOVERY_OPENROUTER_SINGLE_EXTRA_CALLS
    + REVIEW_DISCOVERY_OPENROUTER_FREE_ENDPOINT_ROUND_CAP
    + REVIEW_DISCOVERY_TRAILING_GLOBAL_CALLS
)
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


def _without_excluded_agents(
    agents: list[dict[str, object]], excluded_ids: frozenset[str]
) -> list[dict[str, object]]:
    """Remove prior attempts before batched preflight chooses where to stop."""
    return [
        agent
        for agent in agents
        if str(agent.get("id") or agent.get("agent_id") or "") not in excluded_ids
    ]


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
    confirmations_used: int = 0,
    confirmation_budget: "_EscalationBudget | None" = None,
) -> tuple[list[object], dict[str, object]]:
    """Probe each route with the runtime request contract and keep ready routes.

    ADR-0005: a single fixed ``max_tokens`` cannot fit every model in a
    heterogeneous pool. Each candidate gets one cheap base-budget probe
    (``REVIEW_PREFLIGHT_BASE_TOKENS``). Admission always requires a SECOND,
    confirming probe at the real serving budget
    (``REVIEW_PREFLIGHT_ESCALATED_TOKENS``, equal to the ``REVIEW_MAX_OUTPUT_TOKENS``
    ``main()``'s ``ModelClient`` actually requests during review traffic) --
    fixed as `ContextualWisdomLab/.github#1454` (Devin Review, "Serving-
    incompatible routes pass startup"): the base probe alone previously
    admitted a candidate having proven nothing beyond
    ``REVIEW_PREFLIGHT_BASE_TOKENS``, so a candidate whose real completion
    ceiling sat strictly between the base and serving budgets passed startup
    and only failed once real review traffic began. There are exactly two
    ways a candidate reaches that confirming probe, and each draws from its
    OWN, separately-purposed budget (`ContextualWisdomLab/.github#1415`,
    Devin Review "Later healthy routes cannot start" -- see the two
    constants' own module-level comments for the full incident and sizing
    rationale):

    1. **The base probe already returned usable text.** This is the
       ordinary, most common case; the second probe exists purely to CONFIRM
       that same candidate also serves the real budget, not to diagnose a
       failure. This draws from ``confirmation_budget``
       (``REVIEW_PREFLIGHT_MAX_CONFIRMATIONS``). Success marks
       ``confirmed_at_serving_budget`` (not ``escalated``) on the row -- the
       base attempt already worked, this second attempt only re-proves it at
       the real budget.
    2. **The base probe's response was empty for a "budget too small" reason**
       -- either ``choices[0].finish_reason == "length"`` (OpenAI's
       documented signature), or the vendored
       ``ModelClient._response_content``'s own broader signature (a populated
       ``message.reasoning`` with no string ``content``, which a reasoning
       model can hit under a different ``finish_reason`` -- provider
       ``finish_reason`` semantics for this case are not verified as uniform
       across the pool, and this is the exact original failure mode PR #1436
       responded to). This draws from ``escalation_budget``
       (``REVIEW_PREFLIGHT_MAX_ESCALATIONS``). Success marks ``escalated`` on
       the row -- the base attempt failed and this second attempt is what
       actually rescued it.

    Either way, the SAME candidate gets at most one additional attempt (never
    a third, and never both a confirmation AND an escalation). Each of the
    two budgets' ``*_used`` argument carries forward across calls (not per
    candidate, and not reset per call): a caller that probes two stages of
    the same preflight run (e.g. ``_preflight_with_fallback``'s primary and
    fallback stages) must pass each previous stage's ending count back in
    here so the two stages share one pair of budgets instead of each getting
    its own -- otherwise the computed worst-case bound these counters exist
    to enforce silently doubles. A base response that is empty for any OTHER
    reason (no budget-too-small signature) is not retried at all: a
    genuinely-down candidate never reaches the second-attempt path, so it
    cannot produce a false "healthy" read, and a candidate denied its second
    attempt by its own (exhausted) budget is recorded
    ``confirmation_budget_exhausted`` or ``escalation_budget_exhausted``
    (matching which of the two paths it took) and not admitted -- fails
    closed, exactly like a base failure that never got its own second-attempt
    slot. Exhaustion of ONE budget never blocks a candidate whose path draws
    from the OTHER budget -- the exact cross-purpose interaction that made a
    confirmation-only path spend a rescue-only allowance is the bug this
    separation fixes.
    An exception on the second attempt (transport failure, auth failure,
    rate limit, server error, or a genuine budget rejection) is recorded via
    ``_record_provider_exception`` -- the SAME sanitized classification the
    base probe uses, regardless of attempt or which path it came from. An
    HTTP status alone does not distinguish "this candidate's real ceiling is
    below the escalated budget" from any other cause (401/429/5xx are not
    budget evidence); this codebase has no validated signal today that does,
    so it does not invent one via an over-specific label.

    The report deliberately records only stable route identity, a bounded
    exception class name, an optional numeric HTTP status, attempt count, and
    a bounded ``finish_reason``. Provider response bodies, exception
    messages, URLs, prompts, and credentials are never copied into evidence.
    ``finish_reason`` and ``reasoning_without_content`` are populated on
    every response-bearing outcome -- success included, not just
    failure/escalation, so future tuning has a real "normal" baseline to
    compare against -- and always describe the same, most recent attempt for
    a route (the base attempt when only one was made; the second attempt
    when one was made) -- never a mix of the two attempts' state. When
    the second attempt raises an exception instead of returning a
    response, both fields are absent entirely (there is no response to
    describe) rather than silently retaining the base attempt's values.

    Batched concurrent probing (``_preflight_review_agent_batches``) calls
    this function once per candidate, concurrently, from several threads at
    once within one batch. A plain ``escalations_used``/``confirmations_used``
    int passed by value cannot coordinate admission safely once multiple
    threads can observe and spend the same budget concurrently, so callers
    that need cross-thread coordination pass a shared ``escalation_budget``/
    ``confirmation_budget`` instead; a caller that only ever probes
    sequentially (every direct call in this module's own test suite, and any
    single, unbatched invocation) can keep passing plain
    ``escalations_used``/``confirmations_used`` ints, each wrapped in a
    private, single-owner budget for the duration of this one call --
    identical external behavior to before this thread-safety addition.

    Args:
        agents: Selected zero-cost model agents.
        client: Vendored ``ModelClient``-compatible transport.
        escalations_used: Rescue escalations already spent earlier in this
            same preflight run (e.g. by a prior stage), so the shared rescue
            budget is honored across calls rather than restarted at zero.
            Ignored when ``escalation_budget`` is given.
        escalation_budget: A shared, thread-safe budget bounding rescue
            attempts (a FAILED base probe) to coordinate admission across
            concurrent callers. When omitted, a private budget seeded from
            ``escalations_used`` is used instead.
        confirmations_used: Confirmations already spent earlier in this same
            preflight run, mirroring ``escalations_used`` for the separate
            confirmation budget. Ignored when ``confirmation_budget`` is
            given.
        confirmation_budget: A shared, thread-safe budget bounding
            confirmation attempts (a SUCCESSFUL base probe) -- deliberately
            separate from ``escalation_budget`` (see
            ``REVIEW_PREFLIGHT_MAX_CONFIRMATIONS``'s module-level comment for
            why). When omitted, a private budget seeded from
            ``confirmations_used`` is used instead.

    Returns:
        A pair of viable agents and a sanitized preflight report. The
        report's ``escalations_used``/``confirmations_used`` are each the
        running total including that argument's starting value, so a caller
        chaining another stage can pass them straight back in.

    Raises:
        ReviewPreflightError: If no provider route returns usable text.
    """
    budget = escalation_budget or _EscalationBudget(
        REVIEW_PREFLIGHT_MAX_ESCALATIONS, escalations_used
    )
    confirm_budget = confirmation_budget or _EscalationBudget(
        REVIEW_PREFLIGHT_MAX_CONFIRMATIONS, confirmations_used
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

        base_has_text = _chat_response_has_text(response)
        finish_reason = _response_finish_reason(response)
        # Populated on every response-bearing outcome, including an
        # eventually-superseded base attempt -- not just failure/escalation
        # -- so future tuning has a real "normal" baseline to compare
        # against. Overwritten below if a second attempt is made (see the
        # docstring: both fields always describe the same, most recent
        # attempt, never a mix of the two).
        row["finish_reason"] = finish_reason or "unknown"
        reasoning_without_content = _response_has_reasoning_without_content(response)
        row["reasoning_without_content"] = reasoning_without_content

        if not base_has_text:
            budget_signature = finish_reason == "length" or reasoning_without_content
            if not budget_signature:
                # Genuinely down (or an unrelated malformed reply): no
                # signature suggests a bigger budget would help, so this
                # candidate never reaches the second-attempt path -- it
                # cannot produce a false "healthy" read.
                row["status"] = "rejected"
                row["error_type"] = "invalid_chat_response"
                routes.append(row)
                continue
        # Either the base probe already has usable text (fix for
        # ContextualWisdomLab/.github#1454: admission still requires
        # confirming that text holds at the real serving budget, not just
        # REVIEW_PREFLIGHT_BASE_TOKENS) or it matched a "budget too small"
        # signature above and needs the existing escalation retry.
        #
        # FIXED (ContextualWisdomLab/.github#1415, Devin Review "Later
        # healthy routes cannot start"): these two cases now draw from TWO
        # SEPARATE budgets, not one shared one -- see
        # REVIEW_PREFLIGHT_MAX_ESCALATIONS/REVIEW_PREFLIGHT_MAX_CONFIRMATIONS'
        # module-level comments for the full incident. Confirming an
        # already-successful base probe is the common case (every successful
        # candidate needs it); rescuing a failed one is the rare case. A
        # scarce rescue budget consumed by a burst of ordinary confirmations
        # (or vice versa) must never deny a DIFFERENT candidate's unrelated
        # second attempt.
        second_attempt_budget = confirm_budget if base_has_text else budget
        second_attempt_exhausted_error = (
            "confirmation_budget_exhausted" if base_has_text else "escalation_budget_exhausted"
        )
        #
        # KNOWN, ACCEPTED, TRACKED LIMITATION on the try_reserve() branch
        # below, ContextualWisdomLab/.github#1458 (originally documented on
        # ADR-0005, docs/adr/0005-sidecar-preflight-token-budget.md): each
        # budget is still first-come-first-served in catalog order
        # (build_zdr_prioritized_catalog's (cost_evidence_rank,
        # zdr_attested_rank, provider, model) sort, not random). A
        # later-sorting candidate needing a rescue can still be denied its
        # own escalation attempt purely because
        # REVIEW_PREFLIGHT_MAX_ESCALATIONS earlier-sorting candidates already
        # claimed that (deliberately scarce) rescue budget, even if it would
        # have succeeded at REVIEW_PREFLIGHT_ESCALATED_TOKENS -- unchanged by
        # this fix, and unrelated to it: REVIEW_PREFLIGHT_MAX_CONFIRMATIONS
        # is sized to REVIEW_PREFLIGHT_MAX_TOTAL_ROUTES precisely so the same
        # exhaustion can never happen on the confirmation path (see that
        # constant's own comment). Deliberately not reordered
        # (round-robin/random): a fixed-size shared budget smaller than the
        # candidate pool always has to deny someone a second attempt, so
        # reordering only changes who, and picking a specific policy without
        # real telemetry on which candidates actually need it would itself be
        # the kind of unjustified heuristic this design rejects elsewhere.
        if not second_attempt_budget.try_reserve():
            row["status"] = "rejected"
            row["error_type"] = second_attempt_exhausted_error
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
            # validated signal to actually support. This also applies to a
            # candidate whose base probe already had text: a rejection here
            # is exactly the ContextualWisdomLab/.github#1454 scenario --
            # usable at the base budget, rejected outright at the real
            # serving budget -- and it must not be admitted just because an
            # earlier, smaller attempt happened to succeed.
            _record_provider_exception(row, exc)
            routes.append(row)
            continue
        if _chat_response_has_text(escalated_response):
            row["status"] = "ready"
            if base_has_text:
                # The base attempt already had usable text; this second
                # attempt only confirms that same candidate also serves the
                # real budget -- distinct from `escalated`, which means the
                # base attempt FAILED and this second attempt is what
                # rescued it.
                row["confirmed_at_serving_budget"] = True
            else:
                row["escalated"] = True
            # Overwrite the base attempt's stale diagnostic fields with the
            # escalated (successful, final) attempt's own state -- otherwise
            # a ready route's evidence would still show the base attempt's
            # signature, describing a response this route no longer produced.
            row["finish_reason"] = _response_finish_reason(escalated_response) or "unknown"
            row["reasoning_without_content"] = _response_has_reasoning_without_content(
                escalated_response
            )
            routes.append(row)
            viable.append(agent)
            continue
        # ContextualWisdomLab/.github#1454's exact failure mode when
        # base_has_text is True: usable at REVIEW_PREFLIGHT_BASE_TOKENS,
        # empty at the real REVIEW_PREFLIGHT_ESCALATED_TOKENS serving budget
        # -- never admitted, regardless of the earlier, smaller success.
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
        "confirmations_used": confirm_budget.used,
        "confirmation_budget": REVIEW_PREFLIGHT_MAX_CONFIRMATIONS,
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
    confirmation_budget: "_EscalationBudget | None" = None,
) -> tuple[list[object], dict[str, object]]:
    """Probe bounded concurrent batches until one batch contains a ready route.

    Candidates are probed ``REVIEW_PREFLIGHT_BATCH_SIZE`` at a time, each in
    its own thread, so a full ``REVIEW_PREFLIGHT_MAX_TOTAL_ROUTES``-candidate
    catalog stays within the sidecar's readiness budget: batch wall time is
    the slowest candidate in that batch, not the sum of all of them. Batches
    themselves still run one after another, and probing stops as soon as one
    batch yields at least one ready route -- a later, unprobed batch can
    never "hide" a route this run already found usable.

    Two separate run-wide budgets bound the two distinct second-attempt
    purposes (``ContextualWisdomLab/.github#1415``, Devin Review "Later
    healthy routes cannot start" -- see ``REVIEW_PREFLIGHT_MAX_ESCALATIONS``/
    ``REVIEW_PREFLIGHT_MAX_CONFIRMATIONS``'s own module-level comments for
    the full incident and sizing rationale): ``escalation_budget`` for
    rescuing a FAILED base probe (deliberately scarce), and
    ``confirmation_budget`` for confirming a SUCCESSFUL one (sized to never
    starve a genuinely healthy candidate). Neither is one-per-batch or
    one-per-candidate; since several candidates in the same batch can reach
    either decision concurrently, admission is coordinated through each
    ``_EscalationBudget``'s own lock rather than a plain int, so neither cap
    is ever exceeded under concurrency. One consequence of that concurrency:
    ADR-0005's "first-come-first-served in catalog order" framing holds
    strictly only ACROSS batches (which stay sequential); WITHIN one batch,
    whichever candidate's thread reaches a given reservation first wins it.
    This changes at most which candidate among a few concurrently-probed
    ones claims a scarce slot -- each cap itself is a hard, lock-enforced
    invariant regardless of scheduling.

    Args:
        agents: Selected zero-cost model agents, probed in catalog order.
        client: Vendored ``ModelClient``-compatible transport.
        escalation_budget: A shared budget to coordinate rescue-attempt
            admission with another stage (see ``_preflight_with_fallback``).
            A fresh, run-local budget is created when omitted.
        confirmation_budget: A shared budget to coordinate confirmation-
            attempt admission with another stage, separate from
            ``escalation_budget``. A fresh, run-local budget is created when
            omitted.

    Returns:
        A pair of viable agents (from the first batch with any) and a
        sanitized, aggregated preflight report across every batch attempted.

    Raises:
        ReviewPreflightError: If every batch is exhausted with no viable
            route.
    """
    budget = escalation_budget or _EscalationBudget(REVIEW_PREFLIGHT_MAX_ESCALATIONS)
    confirm_budget = confirmation_budget or _EscalationBudget(
        REVIEW_PREFLIGHT_MAX_CONFIRMATIONS
    )
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
                    confirmation_budget=confirm_budget,
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
                "confirmations_used": confirm_budget.used,
                "confirmation_budget": REVIEW_PREFLIGHT_MAX_CONFIRMATIONS,
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
        "confirmations_used": confirm_budget.used,
        "confirmation_budget": REVIEW_PREFLIGHT_MAX_CONFIRMATIONS,
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
    ONE pair of run-wide budgets for the whole preflight run, not one pair
    each: one ``_EscalationBudget`` for rescue attempts
    (``REVIEW_PREFLIGHT_MAX_ESCALATIONS``) and a separate one for confirmation
    attempts (``REVIEW_PREFLIGHT_MAX_CONFIRMATIONS``,
    ``ContextualWisdomLab/.github#1415``) are each created here and passed
    into both stages, so a run that rejects all primary routes and then
    probes the fallback catalog still spends at most each budget's own cap
    in total across both stages combined -- otherwise the computed worst-case
    bound these counters exist to enforce would silently double. Both
    stages' reports remain in the result: the fallback (or sole) stage's
    report carries the run's final, cumulative ``escalations_used``/
    ``confirmations_used``, and ``primary_attempt`` nests the primary
    stage's own report -- including its own ``escalations_used``/
    ``confirmations_used`` -- whenever a fallback stage ran at all.
    """
    budget = _EscalationBudget(REVIEW_PREFLIGHT_MAX_ESCALATIONS)
    confirm_budget = _EscalationBudget(REVIEW_PREFLIGHT_MAX_CONFIRMATIONS)
    try:
        viable, report = _preflight_review_agent_batches(
            primary_agents,
            client=client,
            escalation_budget=budget,
            confirmation_budget=confirm_budget,
        )
        return viable, report, False
    except ReviewPreflightError as primary_error:
        if not fallback_agents:
            raise
        try:
            viable, report = _preflight_review_agent_batches(
                fallback_agents,
                client=client,
                escalation_budget=budget,
                confirmation_budget=confirm_budget,
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


def _catalog_account_cap(default: int) -> int:
    """Return the configured per-account catalog admission cap.

    ``default`` must be ``scripts.ci.contextual_orchestrator_review_policy``'s
    own ``DEFAULT_ACCOUNT_CAP`` -- the single source of truth for how many
    routes one credential account may contribute to the bounded preflight
    budget. A caller must never substitute a total-routes-scale constant
    (e.g. ``REVIEW_PREFLIGHT_MAX_TOTAL_ROUTES``) here: doing so silently
    disables per-account diversification and lets one rate-limited account
    consume the entire preflight budget. That is not a hypothetical failure
    mode -- an earlier revision of this helper (under a different name)
    defaulted to exactly ``REVIEW_PREFLIGHT_MAX_TOTAL_ROUTES`` and, in a live
    production run, let two NVIDIA NIM credentials sharing one rate-limited
    upstream jointly occupy 12/12 preflight slots, of which 10 were then
    rejected with 429/404/timeout (see ContextualWisdomLab/.github#1415 and
    the "빈 깡통 경로" report it responds to). Routing the default through the
    caller-supplied ``policy.DEFAULT_ACCOUNT_CAP`` (rather than hand-typing a
    literal here) keeps this module's cap from silently drifting out of sync
    with the policy module's own declared intent. `main` PR #1487 landed the
    identical fix independently, converging on this exact name and shape;
    this is the single canonical implementation.

    Args:
        default: The cap to use when ``ORCHESTRATOR_CATALOG_ACCOUNT_CAP`` is
            unset, always ``policy.DEFAULT_ACCOUNT_CAP``.

    Returns:
        The per-account cap to pass to ``build_zdr_prioritized_catalog``.
    """
    return int(os.environ.get("ORCHESTRATOR_CATALOG_ACCOUNT_CAP", str(default)))


def _with_discovery_counts(
    report: dict[str, object],
    rows: list[dict[str, Any]],
    *,
    provider_account: Any,
) -> dict[str, object]:
    """Copy a stage report while restoring full discovery-tier counts.

    ``free_account_diversity`` is recomputed here from the full discovery-wide
    ``rows``, not trusted from the stage report: the primary ``auto``-pool
    stage may have selected only ZDR-admitted free rows (undercounting
    diversity whenever ``--require-zdr`` excludes some free routes) and the
    priced-fallback stage selects only priced rows (so its own internally
    computed diversity is always zero) -- either stage report's
    ``free_account_diversity``, as returned by ``build_zdr_prioritized_catalog``
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
            "free_account_diversity": len(
                {
                    provider_account(str(row["provider"]))
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
    parser.add_argument(
        "--single-candidate-attempt",
        action="store_true",
        help="Disable the redundant same-agent retry when job-level failover is active",
    )
    parser.add_argument(
        "--exclude-candidate-id",
        action="append",
        default=[],
        help="Exclude a previously attempted agent id before runtime preflight",
    )
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
        DEFAULT_ACCOUNT_CAP,
        PolicyError,
        _load_zdr_endpoints,
        build_zdr_prioritized_catalog,
        is_zdr_model,
        parse_discovery_report,
        provider_account,
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
        account_cap=_catalog_account_cap(DEFAULT_ACCOUNT_CAP),
        zdr_endpoints=zdr_endpoints,
        require_zdr=args.require_zdr,
        pool=args.pool,
    )
    excluded_candidate_ids = frozenset(args.exclude_candidate_id)
    result["agents"] = _without_excluded_agents(
        result["agents"], excluded_candidate_ids
    )
    if not result["agents"]:
        raise SystemExit("review sidecar has no candidate after exclusions")
    result["report"] = _with_discovery_counts(
        result["report"], normalized_rows, provider_account=provider_account
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
                account_cap=_catalog_account_cap(DEFAULT_ACCOUNT_CAP),
                zdr_endpoints=zdr_endpoints,
                require_zdr=args.require_zdr,
                pool="auto",
            )
            fallback_result["agents"] = _without_excluded_agents(
                fallback_result["agents"], excluded_candidate_ids
            )
        except PolicyError:
            fallback_result = None
        if fallback_result is not None:
            fallback_result["report"] = _with_discovery_counts(
                fallback_result["report"], normalized_rows, provider_account=provider_account
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
    # realtime_judge is not just a future-routing
    # quality-ledger signal -- route_once() uses it to gate acceptance of the
    # *current* answer and to fail over to the next measured candidate on
    # rejection (see route_once/_realtime_route_judge in
    # contextual_orchestrator/orchestrator.py); disabling it let a
    # judge-rejected, low-quality answer reach Noema instead of another ready
    # route. Normal callers retain TaskOrchestrator's defaults. The explicit
    # single-candidate job mode removes only its redundant same-agent retry;
    # cross-candidate failover happens in the next workflow job, while the
    # realtime judge remains enabled by its unchanged default.
    #
    # Sliced to REVIEW_SERVING_MAX_CANDIDATES (see that constant's own
    # comment): serving the full preflight-admitted pool made the honest
    # worst case exceed this job's own timeout-minutes ceiling. `agents` is
    # already preflight's own ranked, verified-ready ordering, so this keeps
    # the top-ranked candidates and only trims serving-time failover depth
    # among routes preflight already proved could serve a real request.
    attempt_options = {"tool_retry_attempts": 0} if args.single_candidate_attempt else {}
    orchestrator = TaskOrchestrator(
        agents[:REVIEW_SERVING_MAX_CANDIDATES], client=client, **attempt_options
    )
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
