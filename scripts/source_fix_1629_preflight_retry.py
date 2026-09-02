#!/usr/bin/env python3
"""One-shot repair for the central review preflight retry heuristic."""

from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one exact replacement, found {count}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def append_once(path: str, marker: str, addition: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if marker in text:
        return
    target.write_text(text.rstrip() + "\n\n" + addition.strip() + "\n", encoding="utf-8")


launcher = "scripts/ci/contextual_orchestrator_review_launcher.py"
replace_once(
    launcher,
    '''# Startup probes are idempotent and route-local. Reuse the orchestrator's
# transient classifier and jittered backoff for one recovery attempt; do not
# turn preflight into an unbounded retry loop or duplicate provider status
# policy in this central launcher.
REVIEW_PREFLIGHT_TRANSIENT_RETRIES = 1
''',
    '''# Startup probes do not allocate an automatic transport retry. RFC 9110
# constrains when replay can be safe but does not identify a retry count; absent
# an independently governed retry policy, central CI fails closed after one send.
''',
)
replace_once(
    launcher,
    '''def _send_preflight_request(
    client: Any, agent: object, payload: dict[str, object]
) -> object:
    """Use the client's bounded transient-retry path for an idempotent probe.

    The vendored ``ModelClient`` exposes retry policy through ``proxy_send``.
    The one-shot fallback exists only for deterministic compatibility clients
    and legacy test doubles that predate that seam; production review clients
    always take the retry-enabled branch.
    """
    retrying_send = getattr(client, "proxy_send", None)
    if callable(retrying_send):
        return retrying_send(agent, "chat/completions", payload)
    return client.proxy_send_once(agent, "chat/completions", payload)
''',
    '''def _send_preflight_request(
    client: Any, agent: object, payload: dict[str, object]
) -> object:
    """Make exactly one provider send for one semantic preflight payload.

    Provider failure taxonomy remains evidence for the rejection report. It does
    not manufacture a second model call when no retry allocation has been
    independently identified.
    """
    return client.proxy_send_once(agent, "chat/completions", payload)
''',
)
replace_once(
    launcher,
    '''    """Probe one route using bounded transport retry and token escalation.

    ``attempts`` counts distinct semantic payloads (base budget and, only when
    evidenced, one larger token budget). Transient HTTP retries stay inside
    ``ModelClient.proxy_send`` and are reported separately through
    ``transport_retry_budget`` so the two recovery mechanisms are never
    conflated.
    """
''',
    '''    """Probe one route with one transport send per semantic payload.

    ``attempts`` counts distinct semantic payloads. Provider transport failures
    are recorded and fail closed for that payload; no repository-authored retry
    budget is synthesized from status or provider identity.
    """
''',
)
replace_once(
    launcher,
    '''        "model": str(getattr(agent, "model", "")),
        "attempts": 1,
        "transport_retry_budget": REVIEW_PREFLIGHT_TRANSIENT_RETRIES,
''',
    '''        "model": str(getattr(agent, "model", "")),
        "attempts": 1,
''',
)
replace_once(
    launcher,
    '''        max_output_tokens=REVIEW_MAX_OUTPUT_TOKENS,
        max_retries=REVIEW_PREFLIGHT_TRANSIENT_RETRIES,
        temperature=REVIEW_TEMPERATURE,
''',
    '''        max_output_tokens=REVIEW_MAX_OUTPUT_TOKENS,
        max_retries=0,
        temperature=REVIEW_TEMPERATURE,
''',
)
# The serving client must not inherit a historical vendored default either.
replace_once(
    launcher,
    '''    client = ModelClient(
        timeout=None,
        max_output_tokens=REVIEW_MAX_OUTPUT_TOKENS,
        temperature=REVIEW_TEMPERATURE,
    )
''',
    '''    client = ModelClient(
        timeout=None,
        max_output_tokens=REVIEW_MAX_OUTPUT_TOKENS,
        max_retries=0,
        temperature=REVIEW_TEMPERATURE,
    )
''',
)

append_once(
    "docs/adr/0003-contextual-orchestrator-vendored-free-zdr.md",
    "2026-09-02 amendment: central review allocates no implicit transport retry",
    '''- **2026-09-02 amendment: central review allocates no implicit transport retry.**
  The review launcher previously assigned one same-route retry to transient
  provider failures. RFC 9110 section 9.2.2 constrains automatic replay by
  idempotency but does not prescribe a retry count, and NIST SP 800-204 does
  not identify a numeric retry budget for this workload. No Fugu, Conductor,
  or TRINITY contract establishes one either. Central CI therefore configures
  both preflight and serving `ModelClient` instances with `max_retries=0` and
  calls the one-shot passthrough seam for preflight. Typed provider failures
  remain audit evidence and may drive a later independently governed policy;
  they cannot by themselves allocate another model invocation. This is
  provider/model/capability neutral and fails closed rather than replacing the
  retired value with another guessed count.''',
)

append_once(
    "docs/product-technical-gap-baseline.md",
    "## 2026-09-02 — central preflight retry-budget heuristic removal",
    '''## 2026-09-02 — central preflight retry-budget heuristic removal

**RCA.** PR #1629 introduced `REVIEW_PREFLIGHT_TRANSIENT_RETRIES = 1` and
constructed preflight `ModelClient(max_retries=1)`. The HTTP failure taxonomy
was evidence for *failure type*, not evidence identifying one additional model
call. The cited RFC/NIST resilience sources do not supply that number. The
causal owner is the central review launcher because it allocated the extra call.

**Repair.** Preflight now uses `proxy_send_once`; both preflight and serving
clients explicitly use `max_retries=0` so an older vendored orchestrator default
cannot reintroduce an implicit retry. Failure classification is preserved in the
sanitized route report. No provider/model/reasoning identity can change the
transport attempt allocation. A future retry mechanism requires independently
governed executable provenance rather than another local constant.

**Verification.** `tests/test_contextual_orchestrator_no_heuristic_preflight_retry.py`
must be RED before this repair, GREEN after it, and the one-shot source-fix
workflow must self-remove before publication. Exact-head required workflows and
reviews remain authoritative.''',
)

changelog = Path("CHANGELOG.md")
text = changelog.read_text(encoding="utf-8")
entry = (
    "- Remove the central review preflight's hand-selected one-retry transport budget; "
    "preflight and serving now explicitly allocate zero automatic provider retries and "
    "preserve typed failure evidence for separately governed policy.\n"
)
if entry not in text:
    if "## [Unreleased]" in text:
        text = text.replace("## [Unreleased]\n", "## [Unreleased]\n" + entry, 1)
    elif "## Unreleased" in text:
        text = text.replace("## Unreleased\n", "## Unreleased\n" + entry, 1)
    else:
        text = entry + "\n" + text
    changelog.write_text(text, encoding="utf-8")

print("source-fix-1629: heuristic preflight retry budget removed")
