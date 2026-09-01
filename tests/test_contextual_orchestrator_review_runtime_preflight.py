"""Regression tests for the Strix contextual-orchestrator runtime boundary."""

from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
import os
import re
import runpy
from pathlib import Path
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from scripts.ci import contextual_orchestrator_review_policy as policy

_REPO_ROOT = Path(__file__).resolve().parents[1]
_LAUNCHER = _REPO_ROOT / "scripts/ci/contextual_orchestrator_review_launcher.py"
_SIDECAR = _REPO_ROOT / "scripts/ci/contextual_orchestrator_review_sidecar.sh"
_SANITIZER = (
    _REPO_ROOT / "scripts/ci/sanitize_contextual_orchestrator_sidecar_stream.py"
)


class _ProbeClient:
    """Return deterministic per-agent outcomes for runtime preflight tests."""

    def __init__(self, outcomes: dict[str, object]) -> None:
        self.outcomes = outcomes
        self.calls: list[tuple[object, str, dict[str, object]]] = []

    def proxy_send_once(
        self, agent: object, endpoint: str, payload: dict[str, object]
    ) -> dict[str, object]:
        """Capture one request and return or raise the configured outcome."""
        self.calls.append((agent, endpoint, payload))
        outcome = self.outcomes[str(getattr(agent, "id"))]
        if isinstance(outcome, BaseException):
            raise outcome
        assert isinstance(outcome, dict)
        return outcome


class _SequencedClient:
    """Return one outcome per call, in order, ignoring which agent asked.

    Used for ADR-0005 escalation tests where the same candidate is called
    twice (base probe, then escalated retry) and each call must see a
    different, explicitly ordered outcome -- unlike ``_ProbeClient``, whose
    per-agent dict lookup always returns the same outcome for repeat calls.
    """

    def __init__(self, outcomes: list[object]) -> None:
        self._outcomes = iter(outcomes)
        self.calls: list[tuple[object, str, dict[str, object]]] = []

    def proxy_send_once(
        self, agent: object, endpoint: str, payload: dict[str, object]
    ) -> dict[str, object]:
        """Capture one request and return or raise the next configured outcome."""
        self.calls.append((agent, endpoint, payload))
        outcome = next(self._outcomes)
        if isinstance(outcome, BaseException):
            raise outcome
        assert isinstance(outcome, dict)
        return outcome


def _load_launcher() -> dict[str, object]:
    """Execute the dependency-lazy launcher and return its module namespace."""
    return runpy.run_path(str(_LAUNCHER))


def _load_sanitizer() -> dict[str, object]:
    """Execute the sidecar stream sanitizer and return its module namespace."""
    return runpy.run_path(str(_SANITIZER))


def _openai_text(content: str) -> dict[str, object]:
    """Build the minimal OpenAI chat response shape accepted by preflight."""
    return {"choices": [{"message": {"content": content}}]}


def test_routable_discovered_models_excludes_evidence_only_rows() -> None:
    """Evidence-only rows (e.g. OpenRouter) must never enter live selection."""
    namespace = _load_launcher()
    routable = namespace.get("_routable_discovered_models")
    assert callable(routable), "launcher must expose an evidence-only discovery filter"

    evidence_only_model = SimpleNamespace(
        id="openrouter_evidence_only",
        provider_name="openrouter",
        model_id="some/model",
        evidence_only=True,
    )
    live_model = SimpleNamespace(
        id="nvidia_ready",
        provider_name="nvidia_nim",
        model_id="ready/free",
        evidence_only=False,
    )
    no_flag_model = SimpleNamespace(
        id="bytez_untagged", provider_name="bytez", model_id="untagged/free"
    )

    assert routable([evidence_only_model, live_model, no_flag_model]) == [
        live_model,
        no_flag_model,
    ]
    assert routable(None) == []
    assert routable([]) == []


def test_fallback_exclusion_reaches_a_later_healthy_preflight_batch() -> None:
    namespace = _load_launcher()
    exclude = namespace["_without_excluded_agents"]
    preflight = namespace["_preflight_review_agent_batches"]
    batch_size = namespace["REVIEW_PREFLIGHT_BATCH_SIZE"]
    catalog = [{"id": "attempted"}] + [
        {"id": f"failed-{index}"} for index in range(batch_size)
    ] + [{"id": "later-healthy"}]
    filtered = exclude(catalog, frozenset({"attempted"}))
    agents = [SimpleNamespace(id=row["id"], provider_name="openrouter", model="x/free") for row in filtered]
    outcomes = {agent.id: RuntimeError("unavailable") for agent in agents}
    outcomes["later-healthy"] = _openai_text("ready")

    viable, report = preflight(agents, client=_ProbeClient(outcomes))

    assert [agent.id for agent in viable] == ["later-healthy"]
    assert report["probed_count"] == batch_size + 1
    assert all(route["agent_id"] != "attempted" for route in report["routes"])


def test_log_discovery_errors_prints_one_bounded_line_per_provider_failure(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A discarded discovery error must become a visible, sanitizer-safe diagnostic."""
    namespace = _load_launcher()
    log_discovery_errors = namespace.get("_log_discovery_errors")
    assert callable(log_discovery_errors), "launcher must expose a discovery-error logger"

    errors = [
        SimpleNamespace(provider_name="bytez", error_code="http_status_401"),
        SimpleNamespace(provider_name="openai", error_code="timeout"),
    ]

    log_discovery_errors(errors)

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.splitlines() == [
        "provider_discovery_failed provider=bytez code=http_status_401",
        "provider_discovery_failed provider=openai code=timeout",
        "discovery_diagnostics_complete",
    ]


def test_log_discovery_errors_emits_only_the_sentinel_on_a_clean_discovery(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """No providers failed -> just the completion sentinel, no warning lines."""
    namespace = _load_launcher()
    log_discovery_errors = namespace.get("_log_discovery_errors")
    assert callable(log_discovery_errors)

    log_discovery_errors([])

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "discovery_diagnostics_complete\n"


def test_log_discovery_errors_sentinel_matches_the_sidecar_scripts_constant() -> None:
    """The sidecar shell script's poll target must equal this exact literal."""
    namespace = _load_launcher()
    sentinel = namespace.get("_DISCOVERY_DIAGNOSTICS_COMPLETE_SENTINEL")
    assert sentinel == "discovery_diagnostics_complete"
    sidecar_text = _SIDECAR.read_text(encoding="utf-8")
    assert f'SIDECAR_DISCOVERY_DIAGNOSTICS_SENTINEL="{sentinel}"' in sidecar_text


def test_reasoning_without_content_requires_content_to_actually_be_absent() -> None:
    """Regression for Devin Review's successful-replies-report-missing-content
    finding: ``_response_has_reasoning_without_content`` previously checked
    ONLY whether ``message.reasoning`` was truthy, never whether
    ``message.content`` was actually empty/absent -- so a normal, complete
    answer that also discloses a reasoning trace alongside real, non-empty
    content would be wrongly flagged as "starved." Both conditions (populated
    reasoning AND no usable content) must hold together.
    """
    namespace = _load_launcher()
    has_reasoning_without_content = namespace["_response_has_reasoning_without_content"]

    # The exact bug: reasoning present AND content present -- must be False.
    assert (
        has_reasoning_without_content(
            {
                "choices": [
                    {
                        "message": {
                            "reasoning": "the user asked X, so the answer is Y",
                            "content": "Y",
                        }
                    }
                ]
            }
        )
        is False
    )
    # Reasoning present, content genuinely empty string -- the real signature.
    assert (
        has_reasoning_without_content(
            {"choices": [{"message": {"reasoning": "still thinking", "content": ""}}]}
        )
        is True
    )
    # Reasoning present, content key entirely absent -- also the real signature.
    assert (
        has_reasoning_without_content({"choices": [{"message": {"reasoning": "still thinking"}}]})
        is True
    )
    # No reasoning at all -- never flagged regardless of content.
    assert (
        has_reasoning_without_content({"choices": [{"message": {"content": "a normal reply"}}]})
        is False
    )


def test_preflight_mirrors_runtime_request_and_keeps_only_compatible_routes() -> None:
    """Reject provider errors/malformed replies before the sidecar becomes ready."""
    namespace = _load_launcher()
    preflight = namespace.get("_preflight_review_agents")
    assert callable(preflight), "launcher must preflight every selected provider route"

    rejected = SimpleNamespace(
        id="openrouter_rejected", provider_name="openrouter", model="rejected/free"
    )
    malformed = SimpleNamespace(
        id="openrouter_malformed", provider_name="openrouter", model="malformed/free"
    )
    ready = SimpleNamespace(
        id="nvidia_ready", provider_name="nvidia_nim", model="ready/free"
    )
    secret = "sk-secret-must-not-enter-evidence"
    client = _ProbeClient(
        {
            rejected.id: RuntimeError(f"upstream rejected {secret}"),
            malformed.id: {"choices": []},
            ready.id: _openai_text("OK"),
        }
    )

    viable, report = preflight([rejected, malformed, ready], client=client)

    assert viable == [ready]
    assert report["probed_count"] == 3
    assert report["ready_count"] == 1
    assert report["rejected_count"] == 2
    assert [row["status"] for row in report["routes"]] == [
        "rejected",
        "rejected",
        "ready",
    ]
    assert report["routes"][0]["error_type"] == "RuntimeError"
    assert report["routes"][1]["error_type"] == "invalid_chat_response"
    assert secret not in repr(report)

    # Regression for Devin Review's successful-probes-omit-diagnostics
    # finding: the ordinary, most-common outcome (a base-probe success,
    # confirmed at the real serving budget -- see below) must still populate
    # finish_reason and reasoning_without_content -- not just
    # failure/escalation outcomes -- so there is a real "normal" baseline to
    # compare future telemetry against.
    ready_row = report["routes"][2]
    assert ready_row["status"] == "ready"
    assert ready_row["attempts"] == 2
    # ContextualWisdomLab/.github#1454 fix: a base-probe success alone is not
    # admission -- it must also be confirmed at the real serving budget
    # (REVIEW_PREFLIGHT_ESCALATED_TOKENS) before this route is marked ready.
    assert ready_row["confirmed_at_serving_budget"] is True
    assert "escalated" not in ready_row
    assert ready_row["finish_reason"] == "unknown"
    assert ready_row["reasoning_without_content"] is False

    for agent, endpoint, payload in client.calls:
        assert endpoint == "chat/completions"
        assert payload["model"] == agent.model
        assert payload["stream"] is False
        assert payload["temperature"] == 1.0
        assert payload["messages"] == [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Reply with just 'OK'."},
        ]
        assert "tools" not in payload

    # The rejected and malformed routes each make exactly one call (base
    # budget); the ready route makes two -- its base probe, then the
    # mandatory confirmation at the real serving budget.
    assert [payload["max_tokens"] for _, _, payload in client.calls] == [
        namespace["REVIEW_PREFLIGHT_BASE_TOKENS"],
        namespace["REVIEW_PREFLIGHT_BASE_TOKENS"],
        namespace["REVIEW_PREFLIGHT_BASE_TOKENS"],
        namespace["REVIEW_PREFLIGHT_ESCALATED_TOKENS"],
    ]


def test_log_preflight_rejections_prints_bounded_summary_to_stderr(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A ReviewPreflightError's report must reach the job log, not just the artifact.

    Regression coverage for the gap that made the launcher's own internal
    preflight (distinct from the sidecar script's external curl-based gateway
    preflight) fail with only "review sidecar preflight failed" visible and
    the real per-route rejection reasons hidden behind
    omitted_unstructured_lines in the sanitized stream.
    """
    namespace = _load_launcher()
    log_preflight_rejections = namespace.get("_log_preflight_rejections")
    assert callable(log_preflight_rejections)

    secret = "sk-secret-must-not-enter-evidence"
    report = {
        "routes": [
            {
                "agent_id": "nim_nano_free",
                "provider": "nvidia_nim",
                "model": "nvidia/nemotron-3-nano-30b-a3b",
                "status": "rejected",
                "error_type": "ProviderUpstreamError",
                "http_status": 429,
            },
            {
                "agent_id": "or_ds_r1",
                "provider": "openrouter",
                "model": "deepseek/deepseek-r1:free",
                "status": "rejected",
                "error_type": f"RuntimeError {secret}",
            },
            {
                "agent_id": "ready_one",
                "provider": "openai",
                "model": "gpt-4o-mini",
                "status": "ready",
            },
        ],
    }
    log_preflight_rejections(report)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert secret not in captured.err
    assert (
        "preflight_route_rejected provider=nvidia_nim "
        "error_type=ProviderUpstreamError http_status=429"
    ) in captured.err
    # The openrouter route's error_type ("RuntimeError <secret>") is not a
    # Python identifier, so _log_preflight_rejections' own isidentifier()
    # guard replaces it with the bounded placeholder "UnknownError" rather
    # than printing it as-is -- this helper is itself the bound that keeps
    # an unexpected, non-identifier error_type (and anything embedded in it,
    # such as the secret above) out of the job log.
    assert "preflight_route_rejected provider=openrouter error_type=UnknownError" in captured.err
    assert "RuntimeError" not in captured.err
    assert "ready_one" not in captured.err


def test_log_preflight_rejections_covers_nested_primary_attempt(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A fallback-pool failure must also surface the primary pool's rejections."""
    namespace = _load_launcher()
    log_preflight_rejections = namespace.get("_log_preflight_rejections")
    assert callable(log_preflight_rejections)

    report = {
        "routes": [
            {
                "provider": "openai",
                "status": "rejected",
                "error_type": "ProviderUpstreamError",
                "http_status": 503,
            },
        ],
        "primary_attempt": {
            "routes": [
                {
                    "provider": "bytez",
                    "status": "rejected",
                    "error_type": "InvalidChatResponse",
                },
            ],
        },
    }
    log_preflight_rejections(report)
    captured = capsys.readouterr()
    assert "preflight_route_rejected provider=bytez error_type=InvalidChatResponse" in captured.err
    assert (
        "preflight_route_rejected provider=openai error_type=ProviderUpstreamError http_status=503"
        in captured.err
    )


def test_log_preflight_rejections_ignores_malformed_report(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A report missing the expected shape must not raise or print anything."""
    namespace = _load_launcher()
    log_preflight_rejections = namespace.get("_log_preflight_rejections")
    assert callable(log_preflight_rejections)

    log_preflight_rejections({})
    log_preflight_rejections({"routes": "not-a-list"})
    log_preflight_rejections({"routes": ["not-a-dict"]})
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_gateway_preflight_max_tokens_is_synchronized_with_the_routing_probe() -> None:
    """The bash script's end-to-end gateway check must use the same real
    serving budget the routing probe's ESCALATED attempt uses.

    Regression for the 2026-08-30 sidecar-preflight-max-tokens incident,
    predating ADR-0005: back then the routing probe used a single fixed
    `REVIEW_MAX_OUTPUT_TOKENS` for every attempt and correctly marked a
    reasoning-capable nvidia_nim route "ready" at that budget, while the
    separate end-to-end gateway check in
    ``contextual_orchestrator_review_sidecar.sh`` hardcoded
    ``"max_tokens":16`` for that same virtual-model request -- far too small
    for a reasoning model to emit any answer content after its internal
    reasoning tokens, so the gateway rejected a route its own routing probe
    had just proven healthy.

    Since ADR-0005 (this PR), most routes first prove liveness at the much
    cheaper ``REVIEW_PREFLIGHT_BASE_TOKENS`` (16) -- `4096` is then used by
    the routing probe's second attempt for every admitted route, always: to
    rescue a candidate that failed the cheap probe with a budget-too-small
    signature, AND (fixed as `ContextualWisdomLab/.github#1454`, Devin
    Review, "Serving-incompatible routes pass startup") to confirm a
    candidate whose cheap probe already succeeded, before that route is ever
    marked ready -- and, always, by the real serving `ModelClient` for actual
    review traffic. This test's own assertion is unaffected by that: Layer 2
    never escalates (ADR-0005 Decision SS1) and always uses the real serving
    budget, so its literal must still equal `REVIEW_MAX_OUTPUT_TOKENS`
    exactly, for the same reason as before -- a smaller Layer 2 budget can
    still reject a route the routing probe (which now confirms every
    admitted route at this same real serving budget) already proved ready.
    """
    namespace = _load_launcher()
    review_max_output_tokens = namespace["REVIEW_MAX_OUTPUT_TOKENS"]
    sidecar = _SIDECAR.read_text(encoding="utf-8")

    match = re.search(
        r'gateway_virtual_model.*?"max_tokens":(\d+)', sidecar, re.DOTALL
    )
    assert match, "sidecar must send one JSON gateway preflight request with an explicit max_tokens"
    gateway_preflight_max_tokens = int(match.group(1))

    assert gateway_preflight_max_tokens == review_max_output_tokens, (
        "gateway preflight max_tokens "
        f"({gateway_preflight_max_tokens}) must equal the routing probe's "
        f"REVIEW_MAX_OUTPUT_TOKENS ({review_max_output_tokens}); a smaller "
        "budget here can reject a route the routing probe already proved "
        "ready"
    )


def test_gateway_preflight_uses_hour_bound_instead_of_120_seconds() -> None:
    """Each attempt must permit reasoning latency without defeating retries."""
    sidecar = _SIDECAR.read_text(encoding="utf-8")

    command = re.search(r"curl -sS .*?\n\s*-o \"\$gateway_preflight_response\"", sidecar)
    assert command
    assert "--connect-timeout 10" in command.group(0)
    assert "--max-time 3600" in command.group(0)
    assert "--max-time 120" not in command.group(0)
    assert 'launcher_attempt_args[*]:-}" = "--single-candidate-attempt"' in sidecar
    assert 'REVIEW_PREFLIGHT_GATEWAY_MAX_ATTEMPTS:-1' in sidecar


def test_gateway_preflight_retries_transport_failures_up_to_a_bounded_attempt_count() -> None:
    """ADR-0005 Decision SS1/SS3: Layer 2 retries only on Trigger A (no usable
    response), up to an explicit, bounded attempt count -- not on Trigger B
    (empty content with a budget-too-small signature), which the gateway's
    own routing may have already recorded as a "successful" attempt.

    Regression for Devin Review's 4th-round finding on this ADR (a live
    reproduction on ContextualWisdomLab/.github#1449, job 99253418179,
    hung the full 120s with zero bytes -- Trigger A -- and the pre-fix
    script had no recovery path at all).
    """
    sidecar = _SIDECAR.read_text(encoding="utf-8")

    assert 'REVIEW_PREFLIGHT_GATEWAY_MAX_ATTEMPTS="${REVIEW_PREFLIGHT_GATEWAY_MAX_ATTEMPTS:-3}"' in sidecar
    assert "gateway_attempt=1" in sidecar
    assert 'if [ "$gateway_http_status" = "200" ]; then' in sidecar
    assert 'if [ "$gateway_attempt" -ge "$REVIEW_PREFLIGHT_GATEWAY_MAX_ATTEMPTS" ]; then' in sidecar
    assert "gateway_attempt=$((gateway_attempt + 1))" in sidecar
    # Trigger A retries are distinguishable from a first-attempt rejection --
    # the virtual pool's routing is not pinned across separate HTTP calls, so
    # a rejection on a retry is never described as candidate-ceiling evidence.
    assert '"gateway_retry_rejected" if attempts > 1 else "gateway_rejected"' in sidecar
    # Trigger B (a response was received) is a terminal outcome here, not
    # retried, with its budget-too-small signature preserved for diagnosis.
    assert "reasoning_without_content" in sidecar
    assert "gateway preflight returned unusable chat content" in sidecar


_GATEWAY_RETRY_BLOCK_START = 'gateway_virtual_model="orchestrator/${orchestrator_pool}"'
_GATEWAY_RETRY_BLOCK_END = (
    'log "gateway chat/completions preflight confirmed '
    '(attempt ${gateway_attempt}/${REVIEW_PREFLIGHT_GATEWAY_MAX_ATTEMPTS})"'
)

# A minimal stand-in for curl: it never touches the network. Each invocation
# consumes the next numbered plan file in $FAKE_CURL_PLAN_DIR (a fixed,
# test-controlled queue of outcomes, one per expected attempt) so a test can
# script an exact multi-attempt sequence -- transport failure, non-2xx,
# success -- without a real gateway process. A plan file's first line is one
# of:
#   "FAIL"          -- curl exits non-zero, exactly like a real timeout with
#                      zero bytes received.
#   "NOFILE:<code>" -- curl "succeeds" (exits 0, prints <code>) but never
#                      writes the -o response file at all, exactly like a
#                      real curl invocation that got a status line but the
#                      transfer was interrupted before any body arrived.
#   "<code>"        -- an HTTP status code (written verbatim to stdout,
#                      mirroring `-w '%{http_code}'`); any remaining plan
#                      lines become the -o response body, exactly like a
#                      real curl would write one (including deliberately
#                      malformed/non-JSON bodies, for a status-200-but-
#                      unparseable-body scenario).
_FAKE_CURL_SCRIPT = """#!/usr/bin/env bash
set -euo pipefail
plan_dir="$FAKE_CURL_PLAN_DIR"
counter_file="$plan_dir/.count"
count=0
if [ -f "$counter_file" ]; then
  count="$(cat "$counter_file")"
fi
count=$((count + 1))
printf '%s' "$count" > "$counter_file"
plan_file="$plan_dir/$count"
output_file=""
prev=""
for arg in "$@"; do
  if [ "$prev" = "-o" ]; then
    output_file="$arg"
  fi
  prev="$arg"
done
if [ ! -f "$plan_file" ]; then
  printf 'fake curl: no plan queued for call %s\\n' "$count" >&2
  exit 2
fi
status_line="$(head -n 1 "$plan_file")"
if [ "$status_line" = "FAIL" ]; then
  exit 28
fi
case "$status_line" in
  NOFILE:*)
    printf '%s' "${status_line#NOFILE:}"
    exit 0
    ;;
esac
if [ -n "$output_file" ]; then
  tail -n +2 "$plan_file" > "$output_file"
fi
printf '%s' "$status_line"
"""


def _run_gateway_retry_loop(
    tmp_path: Path,
    *,
    max_attempts: int | str,
    plan: list[str],
) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
    """Execute the sidecar's real gateway curl retry loop against a fake curl.

    Extracts the exact, current source of the retry loop from the tracked
    sidecar script (rather than a hand-copied duplicate in this test file)
    so a future edit to that loop is automatically exercised here instead of
    silently drifting from a second, untested copy -- the same drift this
    org's conventions flag repository-local workflow copies for elsewhere.

    Args:
        tmp_path: Pytest's per-test scratch directory.
        max_attempts: Value for ``REVIEW_PREFLIGHT_GATEWAY_MAX_ATTEMPTS``,
            including deliberately malformed strings for the config-guard
            regression test.
        plan: One entry per expected curl call, each either ``"FAIL"`` (a
            transport failure) or ``"<status>\\n<response body>"``.

    Returns:
        The completed harness process and the resulting preflight report
        (``{}`` when the loop never wrote to it).
    """
    sidecar_text = _SIDECAR.read_text(encoding="utf-8")
    start = sidecar_text.index(_GATEWAY_RETRY_BLOCK_START)
    end = sidecar_text.index(_GATEWAY_RETRY_BLOCK_END, start) + len(_GATEWAY_RETRY_BLOCK_END)
    retry_block = sidecar_text[start:end]

    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    fake_curl = fake_bin / "curl"
    fake_curl.write_text(_FAKE_CURL_SCRIPT, encoding="utf-8")
    fake_curl.chmod(0o755)

    plan_dir = tmp_path / "curl-plan"
    plan_dir.mkdir()
    for index, outcome in enumerate(plan, start=1):
        (plan_dir / str(index)).write_text(outcome, encoding="utf-8")

    work_dir = tmp_path / "work"
    work_dir.mkdir()
    gateway_preflight_request = work_dir / "gateway-preflight-request.json"
    gateway_preflight_request.write_text("{}", encoding="utf-8")
    gateway_preflight_response = work_dir / "gateway-preflight.json"
    preflight_report = work_dir / "preflight.json"
    preflight_report.write_text("{}", encoding="utf-8")

    harness = tmp_path / "harness.sh"
    harness.write_text(
        "set -euo pipefail\n"
        "log() { printf '[test-sidecar] %s\\n' \"$*\"; }\n"
        'fail() { log "error: $*" >&2; exit 1; }\n'
        'orchestrator_pool="free"\n'
        'ORCHESTRATOR_TOKEN="synthetic-test-bearer"\n'
        'ORCHESTRATOR_HOST="127.0.0.1"\n'
        'ORCHESTRATOR_PORT="18080"\n'
        'sidecar_python="$(command -v python3)"\n'
        f'gateway_preflight_request="{gateway_preflight_request}"\n'
        f'gateway_preflight_response="{gateway_preflight_response}"\n'
        f'preflight_report="{preflight_report}"\n'
        + retry_block
        + "\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        ["bash", str(harness)],
        env={
            **os.environ,
            "PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}",
            "REVIEW_PREFLIGHT_GATEWAY_MAX_ATTEMPTS": str(max_attempts),
            "FAKE_CURL_PLAN_DIR": str(plan_dir),
        },
        text=True,
        capture_output=True,
        check=False,
    )
    report: dict[str, object] = {}
    try:
        report = json.loads(preflight_report.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        report = {}
    return result, report


@pytest.mark.parametrize("malformed_value", ["not-a-number", "0", "-1", "3.5"])
def test_gateway_retry_loop_rejects_a_malformed_attempt_limit_before_any_curl_call(
    tmp_path: Path, malformed_value: str
) -> None:
    """Regression for Devin Review's malformed-retry-limit-removes-bound
    finding: a non-numeric (or zero, or negative) override used to make the
    integer comparison `[ "$gateway_attempt" -ge "$REVIEW_PREFLIGHT_GATEWAY_MAX_ATTEMPTS" ]`
    fail on every iteration -- which evaluates as "not yet at the limit," so
    the loop would retry forever instead of failing closed on bad config.
    (An empty override is not exercised here: ``${VAR:-3}`` already treats
    unset-or-empty as "use the default," so it never reaches the guard --
    the guard's own ``''`` pattern is defense in depth for a future change to
    that assignment, not a reachable case today.)

    The plan is deliberately empty: if the fix regresses and the loop reaches
    curl at all, the fake curl exits 2 with a distinct "no plan queued"
    message, which the assertions below would not match -- proving this
    fails closed on the config check itself, never even attempting a call.
    """
    result, report = _run_gateway_retry_loop(
        tmp_path, max_attempts=malformed_value, plan=[]
    )

    assert result.returncode == 1
    assert "REVIEW_PREFLIGHT_GATEWAY_MAX_ATTEMPTS must be a positive integer" in result.stderr
    assert report == {}


def test_gateway_retry_loop_rejects_an_oversized_attempt_limit_before_any_curl_call(
    tmp_path: Path,
) -> None:
    """Regression for a follow-up Devin Review finding on the malformed-limit
    fix: an all-digit value is not automatically safe -- `[ -ge ]` errors the
    identical way once the value overflows the shell's integer range (a
    55-digit all-digit string reproduces "integer expression expected",
    exactly like a non-numeric one), so the digit-only guard alone is
    insufficient. This asserts a value that passes the digit-only check but
    is absurdly long is still rejected, closed, before any curl call.
    """
    result, report = _run_gateway_retry_loop(
        tmp_path,
        max_attempts="9" * 55,
        plan=[],
    )

    assert result.returncode == 1
    assert "REVIEW_PREFLIGHT_GATEWAY_MAX_ATTEMPTS must be at most 9999" in result.stderr
    assert report == {}


def test_gateway_retry_loop_accepts_the_maximum_allowed_attempt_limit(tmp_path: Path) -> None:
    """The digit-count cap's boundary (9999) itself must still be accepted --
    proving the guard rejects on length, not by rejecting every large-looking
    value indiscriminately.
    """
    success_body = json.dumps({"choices": [{"message": {"content": "OK"}}]})
    result, report = _run_gateway_retry_loop(
        tmp_path, max_attempts="9999", plan=[f"200\n{success_body}"]
    )

    assert result.returncode == 0, result.stderr
    assert report["gateway"]["status"] == "ready"


def test_gateway_retry_loop_succeeds_on_the_first_attempt(tmp_path: Path) -> None:
    """A clean 200 on the very first curl call needs no retry at all.

    Also covers Devin Review's successful-probes-omit-diagnostics finding:
    ``finish_reason``/``reasoning_without_content`` must be populated on
    success too, not just on rejection -- so a real "normal" response is
    recorded here, not just left absent.
    """
    success_body = json.dumps(
        {"choices": [{"finish_reason": "stop", "message": {"content": "OK"}}]}
    )
    result, report = _run_gateway_retry_loop(
        tmp_path, max_attempts=3, plan=[f"200\n{success_body}"]
    )

    assert result.returncode == 0, result.stderr
    assert "confirmed (attempt 1/3)" in result.stdout
    assert report["gateway"] == {
        "endpoint": "chat/completions",
        "status": "ready",
        "attempts": 1,
        "finish_reason": "stop",
        "reasoning_without_content": False,
    }


def test_gateway_retry_loop_recovers_from_one_transport_failure(tmp_path: Path) -> None:
    """ADR-0005 Trigger A: a timeout with zero bytes is retried, not fatal.

    Regression for the live ContextualWisdomLab/.github#1449 reproduction
    (job 99253418179): a curl timeout with no response used to abort the
    sidecar outright with no recovery path at all.
    """
    success_body = json.dumps(
        {"choices": [{"finish_reason": "stop", "message": {"content": "OK"}}]}
    )
    result, report = _run_gateway_retry_loop(
        tmp_path, max_attempts=3, plan=["FAIL", f"200\n{success_body}"]
    )

    assert result.returncode == 0, result.stderr
    assert "did not reach the sidecar cleanly (status=unreachable); retrying" in result.stdout
    assert "confirmed (attempt 2/3)" in result.stdout
    assert report["gateway"] == {
        "endpoint": "chat/completions",
        "status": "ready",
        "attempts": 2,
        "finish_reason": "stop",
        "reasoning_without_content": False,
    }


def test_gateway_retry_loop_records_a_non2xx_rejection_after_exhausting_attempts(
    tmp_path: Path,
) -> None:
    """A non-2xx status on every attempt fails closed with retry-aware evidence.

    The second (retry) attempt's rejection is recorded as
    ``gateway_retry_rejected``, distinct from a first-attempt rejection,
    since the virtual pool's routing is not pinned across separate calls.
    """
    error_body = json.dumps({"error": {"code": "invalid_structured_output"}})
    result, report = _run_gateway_retry_loop(
        tmp_path,
        max_attempts=2,
        plan=[f"500\n{error_body}", f"500\n{error_body}"],
    )

    assert result.returncode == 1
    assert "gateway preflight returned HTTP 500 after 2 attempts" in result.stderr
    assert report["gateway"] == {
        "endpoint": "chat/completions",
        "error_type": "gateway_retry_rejected",
        "error_code": "invalid_structured_output",
        "http_status": 500,
        "attempts": 2,
        "status": "rejected",
    }


def test_gateway_retry_loop_records_transport_exhaustion_evidence_before_failing(
    tmp_path: Path,
) -> None:
    """Regression for Devin Review's transport-exhaustion-loses-evidence
    finding: exhausting every attempt on repeated transport failures (never
    receiving one usable HTTP response) used to fail closed with the
    preflight report untouched -- exactly the failure case telemetry matters
    most for left zero trace of attempt count or trigger. Must now record a
    bounded classification before ``fail`` exits.
    """
    result, report = _run_gateway_retry_loop(
        tmp_path, max_attempts=2, plan=["FAIL", "FAIL"]
    )

    assert result.returncode == 1
    assert (
        "gateway preflight request could not reach the local sidecar after 2 attempts"
        in result.stderr
    )
    assert report["gateway"] == {
        "endpoint": "chat/completions",
        "error_type": "gateway_transport_exhausted",
        "attempts": 2,
        "status": "rejected",
    }


def test_gateway_retry_loop_classifies_a_transport_then_http_exhaustion_by_the_final_attempt(
    tmp_path: Path,
) -> None:
    """Regression for Devin Review's mixed-retry-outcomes-lack-coverage
    finding: the failure type can change between attempts (a transport
    failure retried into an HTTP rejection, or the reverse), and the final
    evidence must reflect the LAST attempt's actual outcome, not the first.
    Here attempt 1 times out (no response at all) and attempt 2 gets a
    non-2xx response -- exhaustion must classify as the non-2xx path
    (`http_status` present, `gateway_retry_rejected` since this is a retry),
    not the transport-exhaustion path.
    """
    error_body = json.dumps({"error": {"code": "invalid_structured_output"}})
    result, report = _run_gateway_retry_loop(
        tmp_path, max_attempts=2, plan=["FAIL", f"500\n{error_body}"]
    )

    assert result.returncode == 1
    assert "gateway preflight returned HTTP 500 after 2 attempts" in result.stderr
    assert report["gateway"] == {
        "endpoint": "chat/completions",
        "error_type": "gateway_retry_rejected",
        "error_code": "invalid_structured_output",
        "http_status": 500,
        "attempts": 2,
        "status": "rejected",
    }


def test_gateway_retry_loop_classifies_an_http_then_transport_exhaustion_by_the_final_attempt(
    tmp_path: Path,
) -> None:
    """The reverse mixed sequence: attempt 1 gets a non-2xx response, attempt
    2 times out with no response at all. Exhaustion must classify as the
    transport-exhaustion path (no `http_status`), matching what actually
    happened on the final, decisive attempt.
    """
    error_body = json.dumps({"error": {"code": "invalid_structured_output"}})
    result, report = _run_gateway_retry_loop(
        tmp_path, max_attempts=2, plan=[f"500\n{error_body}", "FAIL"]
    )

    assert result.returncode == 1
    assert (
        "gateway preflight request could not reach the local sidecar after 2 attempts"
        in result.stderr
    )
    assert report["gateway"] == {
        "endpoint": "chat/completions",
        "error_type": "gateway_transport_exhausted",
        "attempts": 2,
        "status": "rejected",
    }


def test_gateway_retry_loop_records_evidence_for_a_malformed_200_response_body(
    tmp_path: Path,
) -> None:
    """Regression for Devin Review's malformed-gateway-replies-lose-evidence
    finding: an HTTP 200 whose body is not parseable JSON at all (garbled or
    truncated) used to hit the bare ``except (OSError, json.JSONDecodeError,
    ...): pass`` fallback and write nothing to the gateway evidence report --
    the same evidence-loss pattern as transport exhaustion, a different
    trigger. Must now record a bounded ``gateway_invalid_response``
    classification (attempt count, rejected status, no raw body copied)
    before failing closed, via the same atomic-write pattern used elsewhere.
    """
    result, report = _run_gateway_retry_loop(
        tmp_path, max_attempts=1, plan=["200\nthis is not valid JSON {{{"]
    )

    assert result.returncode == 1
    assert "gateway preflight returned unusable chat content" in result.stderr
    assert report["gateway"] == {
        "endpoint": "chat/completions",
        "status": "rejected",
        "error_type": "gateway_invalid_response",
        "attempts": 1,
    }


def test_gateway_retry_loop_records_evidence_when_the_response_file_is_missing(
    tmp_path: Path,
) -> None:
    """The same regression as above, for the sibling trigger: curl reports a
    200 status but the response file itself was never written (a transfer
    interrupted after the status line but before any body arrived). Reading
    a missing file raises ``OSError``, caught by the same fallback -- must
    also record evidence rather than leaving the report untouched.
    """
    result, report = _run_gateway_retry_loop(tmp_path, max_attempts=1, plan=["NOFILE:200"])

    assert result.returncode == 1
    assert "gateway preflight returned unusable chat content" in result.stderr
    assert report["gateway"] == {
        "endpoint": "chat/completions",
        "status": "rejected",
        "error_type": "gateway_invalid_response",
        "attempts": 1,
    }


@pytest.mark.parametrize("wrong_shaped_body", ["[]", "null", '"just a string"', "42"])
def test_gateway_retry_loop_records_evidence_for_a_valid_json_wrong_top_level_type(
    tmp_path: Path, wrong_shaped_body: str
) -> None:
    """Regression for a follow-up Devin Review finding on the malformed-
    gateway-reply fix: ``json.loads`` legally parses a top-level JSON array,
    ``null``, a bare string, or a number -- not just an object -- and
    ``response.get("choices")`` assumes a dict, raising ``AttributeError``
    for any of these, which was NOT in the caught exception tuple. That
    uncaught exception still failed the script closed overall (a non-zero
    Python exit), but skipped writing evidence entirely -- the same
    evidence-loss bug as the unparseable-JSON/missing-file cases, just for
    a body that IS valid JSON with the wrong top-level shape. Must now
    record the same bounded ``gateway_invalid_response`` classification.
    """
    result, report = _run_gateway_retry_loop(
        tmp_path, max_attempts=1, plan=[f"200\n{wrong_shaped_body}"]
    )

    assert result.returncode == 1
    assert "gateway preflight returned unusable chat content" in result.stderr
    assert report["gateway"] == {
        "endpoint": "chat/completions",
        "status": "rejected",
        "error_type": "gateway_invalid_response",
        "attempts": 1,
    }


def test_reasoning_without_content_escalates_then_still_fails_closed_if_unresolved() -> None:
    """ADR-0005 round 5 (Devin Review): escalation must key off the vendored
    ``ModelClient._response_content``'s own "reasoning, no content" signature,
    not only ``finish_reason == "length"`` -- a reasoning model can exhaust its
    budget under a different (or absent) ``finish_reason``, and this is the
    exact original failure mode PR #1436 responded to. This response has no
    ``finish_reason`` at all, so it would NOT have escalated under the
    finish_reason-only predicate; it must escalate here because
    ``message.reasoning`` is populated with empty ``content``.

    Negative control for the same incident: raising the budget must never be
    mistaken for making every response acceptable. The escalated attempt
    reproduces the identical reasoning-only shape here, so the route must
    still end up "rejected", never reclassified as healthy just because an
    escalation was attempted.
    """
    namespace = _load_launcher()
    preflight = namespace["_preflight_review_agents"]

    reasoning_only = SimpleNamespace(
        id="nvidia_nim_reasoning_only", provider_name="nvidia_nim", model="reasoning/free"
    )
    client = _ProbeClient(
        {
            reasoning_only.id: {
                "choices": [
                    {"message": {"content": "", "reasoning": "internal reasoning tokens only"}}
                ]
            }
        }
    )

    with pytest.raises(namespace["ReviewPreflightError"], match="no provider route passed") as failure:
        preflight([reasoning_only], client=client)

    assert [call[2]["max_tokens"] for call in client.calls] == [
        namespace["REVIEW_PREFLIGHT_BASE_TOKENS"],
        namespace["REVIEW_PREFLIGHT_ESCALATED_TOKENS"],
    ]
    row = failure.value.report["routes"][0]
    assert row["attempts"] == 2
    assert row["reasoning_without_content"] is True
    assert row["finish_reason"] == "unknown"
    assert failure.value.report["escalations_used"] == 1


def test_base_probe_success_with_reasoning_and_content_is_never_flagged_as_starved() -> None:
    """End-to-end regression for Devin Review's successful-replies-report-
    missing-content finding: a genuinely healthy, complete first-attempt
    response that ALSO discloses a reasoning trace alongside real content
    must never be recorded as ``reasoning_without_content: True`` -- that
    would falsely pollute the evidence this preflight exists to produce, on
    the single most common outcome (a base-probe success, confirmed at the
    real serving budget per the ContextualWisdomLab/.github#1454 fix).
    """
    namespace = _load_launcher()
    preflight = namespace["_preflight_review_agents"]

    transparent_reasoner = SimpleNamespace(
        id="openai_transparent_reasoner", provider_name="openai", model="reasoner/free"
    )
    client = _ProbeClient(
        {
            transparent_reasoner.id: {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "reasoning": "the user asked for a greeting, so respond with one",
                            "content": "Hello!",
                        },
                    }
                ]
            }
        }
    )

    viable, report = preflight([transparent_reasoner], client=client)

    assert viable == [transparent_reasoner]
    row = report["routes"][0]
    assert row["status"] == "ready"
    # Two attempts: the base probe (16 tokens) plus the mandatory
    # confirmation at the real serving budget (ContextualWisdomLab/.github#1454).
    assert row["attempts"] == 2
    assert row["confirmed_at_serving_budget"] is True
    assert "escalated" not in row
    assert row["finish_reason"] == "stop"
    assert row["reasoning_without_content"] is False
    assert [call[2]["max_tokens"] for call in client.calls] == [
        namespace["REVIEW_PREFLIGHT_BASE_TOKENS"],
        namespace["REVIEW_PREFLIGHT_ESCALATED_TOKENS"],
    ]


def test_finish_reason_length_escalates_and_can_succeed() -> None:
    """The OpenAI-documented ``finish_reason == "length"`` signature also
    escalates, independent of the ``reasoning`` field, and a candidate that
    only needed a bigger budget is correctly marked ready on the retry.

    Also a regression for Devin Review's successful-escalations-keep-stale-
    telemetry finding: the escalated (successful, final) response here
    deliberately carries a DIFFERENT ``finish_reason`` (``"stop"``) than the
    base attempt's ``"length"``, so a stale, unrefreshed field would be
    caught -- the row must describe the response that actually made this
    route ready, not the earlier one that didn't.
    """
    namespace = _load_launcher()
    preflight = namespace["_preflight_review_agents"]

    slow_starter = SimpleNamespace(
        id="openrouter_slow_starter", provider_name="openrouter", model="slow/free"
    )
    client = _SequencedClient(
        [
            {"choices": [{"finish_reason": "length", "message": {"content": ""}}]},
            {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": "OK, here is the answer."},
                    }
                ]
            },
        ]
    )

    viable, report = preflight([slow_starter], client=client)

    assert viable == [slow_starter]
    assert [call[2]["max_tokens"] for call in client.calls] == [
        namespace["REVIEW_PREFLIGHT_BASE_TOKENS"],
        namespace["REVIEW_PREFLIGHT_ESCALATED_TOKENS"],
    ]
    row = report["routes"][0]
    assert row["status"] == "ready"
    assert row["attempts"] == 2
    assert row["escalated"] is True
    # Describes the escalated (final) attempt, not the stale base one.
    assert row["finish_reason"] == "stop"
    assert row["reasoning_without_content"] is False
    assert report["escalations_used"] == 1


def test_base_probe_success_not_admitted_when_serving_budget_probe_returns_empty() -> None:
    """Regression for Devin Review's "Serving-incompatible routes pass
    startup" finding (`ContextualWisdomLab/.github#1454`): a route that
    succeeds at the cheap `REVIEW_PREFLIGHT_BASE_TOKENS` probe but returns
    empty content at the real `REVIEW_PREFLIGHT_ESCALATED_TOKENS` serving
    budget must NOT be marked ready -- admission requires success at the
    actual serving-equivalent token budget, not merely at the escalation
    sequence's first rung. Before this fix, `_build_model_client` would go
    on to serve real reviews at `REVIEW_MAX_OUTPUT_TOKENS` against a route
    this preflight had already (wrongly) admitted.
    """
    namespace = _load_launcher()
    preflight = namespace["_preflight_review_agents"]

    serving_incompatible = SimpleNamespace(
        id="nvidia_nim_serving_incompatible", provider_name="nvidia_nim", model="narrow/free"
    )
    client = _SequencedClient(
        [
            _openai_text("OK"),
            {"choices": [{"finish_reason": "length", "message": {"content": ""}}]},
        ]
    )

    with pytest.raises(namespace["ReviewPreflightError"], match="no provider route passed"):
        preflight([serving_incompatible], client=client)

    assert [call[2]["max_tokens"] for call in client.calls] == [
        namespace["REVIEW_PREFLIGHT_BASE_TOKENS"],
        namespace["REVIEW_PREFLIGHT_ESCALATED_TOKENS"],
    ]


def test_base_probe_success_not_admitted_when_serving_budget_probe_raises() -> None:
    """The sibling shape of the same Devin Review finding: the route's
    confirming probe at the real serving budget doesn't just come back
    empty, it is rejected outright (a provider whose real completion-token
    ceiling sits strictly between the base and serving budgets, exactly the
    axis ADR-0005's own Research already documented). Must still fail
    closed, not admit the route on the strength of the earlier, smaller
    success.
    """
    namespace = _load_launcher()
    preflight = namespace["_preflight_review_agents"]

    narrow_ceiling = SimpleNamespace(
        id="nvidia_nim_narrow_ceiling", provider_name="nvidia_nim", model="narrow/free"
    )
    client = _SequencedClient(
        [
            _openai_text("OK"),
            RuntimeError("provider rejected the request: max_tokens exceeds model ceiling"),
        ]
    )

    with pytest.raises(namespace["ReviewPreflightError"]) as failure:
        preflight([narrow_ceiling], client=client)

    row = failure.value.report["routes"][0]
    assert row["status"] == "rejected"
    assert row["error_type"] == "RuntimeError"
    assert row["attempts"] == 2
    assert "escalated" not in row
    assert "confirmed_at_serving_budget" not in row


def test_base_probe_success_confirmation_has_its_own_dedicated_budget() -> None:
    """Regression for Devin Review's "Later healthy routes cannot start"
    finding (`ContextualWisdomLab/.github#1415`): a base-probe success's
    mandatory confirmation used to draw from the SAME shared
    ``REVIEW_PREFLIGHT_MAX_ESCALATIONS`` counter a budget-too-small
    escalation would -- a counter sized (4) for the RARE rescue case, not
    the common "confirm every success" case. Confirmation now draws from its
    own separate ``REVIEW_PREFLIGHT_MAX_CONFIRMATIONS`` budget, so
    exhausting the (still small, still bounded) escalation budget on
    genuinely failed candidates must never deny a later, unrelated
    candidate's confirmation.
    """
    namespace = _load_launcher()
    preflight = namespace["_preflight_review_agents"]
    max_escalations = namespace["REVIEW_PREFLIGHT_MAX_ESCALATIONS"]
    max_confirmations = namespace["REVIEW_PREFLIGHT_MAX_CONFIRMATIONS"]
    assert max_confirmations > max_escalations, (
        "the confirmation budget must be dedicated and large enough to cover "
        "every candidate this preflight run can ever probe -- not merely "
        "equal to the small, deliberately scarce rescue budget"
    )

    # Exhaust the ESCALATION (rescue) budget entirely on candidates that
    # fail their base probe with a "budget too small" signature and then
    # (deliberately, in this test) fail their rescue attempt too, the same
    # way every time -- these never touch the confirmation budget at all,
    # they only need to fully spend the escalation budget's slots.
    length_response = {"choices": [{"finish_reason": "length", "message": {"content": ""}}]}
    escalation_budget_users = [
        SimpleNamespace(id=f"escalation_user_{index}", provider_name="openrouter", model="x/free")
        for index in range(max_escalations)
    ]
    # A base-probe SUCCESS needing only confirmation -- must not be blocked
    # by the escalation budget above being fully spent.
    confirmed = SimpleNamespace(
        id="confirmed_despite_escalation_exhaustion",
        provider_name="openrouter",
        model="x/free",
    )
    client = _ProbeClient(
        {agent.id: dict(length_response) for agent in escalation_budget_users}
        | {confirmed.id: _openai_text("OK")}
    )

    viable, report = preflight([*escalation_budget_users, confirmed], client=client)

    assert viable == [confirmed]
    assert report["escalations_used"] == max_escalations
    assert report["confirmations_used"] == 1
    for row in report["routes"][:-1]:
        assert row["status"] == "rejected"
        assert row["error_type"] == "invalid_chat_response"
    confirmed_row = report["routes"][-1]
    assert confirmed_row["status"] == "ready"
    assert confirmed_row["confirmed_at_serving_budget"] is True


def test_confirmation_budget_is_bounded_not_unbounded() -> None:
    """The confirmation budget is dedicated, not shared -- but it is still a
    real, finite cap (``REVIEW_PREFLIGHT_MAX_CONFIRMATIONS``), never an
    unbounded allowance that would reintroduce an uncomputed worst case.
    Exhausting it is recorded with its own distinct
    ``confirmation_budget_exhausted`` classification, never conflated with
    the separate ``escalation_budget_exhausted`` outcome.
    """
    namespace = _load_launcher()
    preflight = namespace["_preflight_review_agents"]
    max_confirmations = namespace["REVIEW_PREFLIGHT_MAX_CONFIRMATIONS"]

    agents = [
        SimpleNamespace(id=f"confirmed_{index}", provider_name="openrouter", model="x/free")
        for index in range(max_confirmations)
    ]
    exhausted = SimpleNamespace(
        id="confirmation_exhausted", provider_name="openrouter", model="x/free"
    )
    client = _ProbeClient(
        {agent.id: _openai_text("OK") for agent in agents}
        | {exhausted.id: _openai_text("OK")}
    )

    viable, report = preflight([*agents, exhausted], client=client)

    assert viable == agents
    exhausted_row = report["routes"][-1]
    assert exhausted_row["status"] == "rejected"
    assert exhausted_row["error_type"] == "confirmation_budget_exhausted"
    assert exhausted_row["attempts"] == 1
    assert report["confirmations_used"] == max_confirmations
    assert report["escalations_used"] == 0
    assert len(client.calls) == max_confirmations * 2 + 1


def test_escalation_budget_is_shared_and_bounded_across_candidates() -> None:
    """Once ``REVIEW_PREFLIGHT_MAX_ESCALATIONS`` is spent, a further candidate
    that would otherwise qualify is rejected immediately, without a second
    call -- the shared budget is per-run, not per-candidate.
    """
    namespace = _load_launcher()
    preflight = namespace["_preflight_review_agents"]
    max_escalations = namespace["REVIEW_PREFLIGHT_MAX_ESCALATIONS"]

    length_response = {"choices": [{"finish_reason": "length", "message": {"content": ""}}]}
    agents = [
        SimpleNamespace(id=f"budget_user_{index}", provider_name="openrouter", model="x/free")
        for index in range(max_escalations)
    ]
    exhausted = SimpleNamespace(
        id="budget_exhausted", provider_name="openrouter", model="x/free"
    )
    client = _ProbeClient(
        {agent.id: dict(length_response) for agent in agents}
        | {exhausted.id: dict(length_response)}
    )

    with pytest.raises(namespace["ReviewPreflightError"]) as failure:
        preflight([*agents, exhausted], client=client)

    exhausted_row = failure.value.report["routes"][-1]
    assert exhausted_row["attempts"] == 1
    assert exhausted_row["error_type"] == "escalation_budget_exhausted"
    assert failure.value.report["escalations_used"] == max_escalations
    assert len(client.calls) == max_escalations * 2 + 1


@pytest.mark.parametrize(
    ("http_status", "exception_type_name"),
    [
        (401, "_UnauthorizedError"),
        (429, "_ThrottledError"),
        (500, "_ServerError"),
        (503, "_UnavailableError"),
    ],
)
def test_escalated_probe_http_rejection_never_overclaims_budget_attribution(
    http_status: int, exception_type_name: str
) -> None:
    """Regression for Devin Review's HTTP-failures-receive-false-diagnosis
    finding: an escalated-attempt HTTP rejection previously became the
    blanket ``escalated_probe_rejected`` label for ANY status code, wrongly
    implying every one of these (auth failure, rate limit, server error) was
    evidence the token budget specifically was too large. None of these
    statuses is budget evidence -- only that some request failed. The
    escalated attempt now gets the exact same sanitized classification the
    base probe already uses for any exception, with no special budget-
    specific label invented from a status code alone.
    """
    namespace = _load_launcher()
    preflight = namespace["_preflight_review_agents"]

    exception_type = type(exception_type_name, (RuntimeError,), {"code": http_status})
    flaky = SimpleNamespace(
        id="nvidia_nim_low_ceiling", provider_name="nvidia_nim", model="low/free"
    )
    client = _SequencedClient(
        [
            {"choices": [{"finish_reason": "length", "message": {"content": ""}}]},
            exception_type("provider rejected the request"),
        ]
    )

    with pytest.raises(namespace["ReviewPreflightError"]) as failure:
        preflight([flaky], client=client)

    assert len(client.calls) == 2
    row = failure.value.report["routes"][0]
    assert row["error_type"] == exception_type_name
    assert row["http_status"] == http_status
    assert row["attempts"] == 2


def test_escalated_probe_transport_failure_is_not_mislabeled_as_a_rejection() -> None:
    """A transport failure (no HTTP status at all) on the escalated attempt
    gets the same sanitized exception-type recording the base probe uses --
    no HTTP status means even less basis for any budget-specific label.
    """
    namespace = _load_launcher()
    preflight = namespace["_preflight_review_agents"]

    flaky = SimpleNamespace(
        id="openrouter_flaky", provider_name="openrouter", model="flaky/free"
    )
    client = _SequencedClient(
        [
            {"choices": [{"finish_reason": "length", "message": {"content": ""}}]},
            TimeoutError("connection timed out with zero bytes received"),
        ]
    )

    with pytest.raises(namespace["ReviewPreflightError"]) as failure:
        preflight([flaky], client=client)

    row = failure.value.report["routes"][0]
    assert row["error_type"] == "TimeoutError"
    assert "http_status" not in row
    assert row["attempts"] == 2


def test_escalated_probe_transport_failure_sanitizes_an_unsafe_exception_name() -> None:
    """An escalated-attempt exception whose type name is unsafe to log
    verbatim (not a plain identifier, or implausibly long) still falls back
    to the same bounded ``provider_error`` placeholder the base probe uses,
    rather than ever copying raw exception state into evidence.
    """
    namespace = _load_launcher()
    preflight = namespace["_preflight_review_agents"]

    unsafe_exception_type = type("Not An Identifier", (RuntimeError,), {})

    flaky = SimpleNamespace(
        id="openrouter_unsafe_exception", provider_name="openrouter", model="flaky/free"
    )
    client = _SequencedClient(
        [
            {"choices": [{"finish_reason": "length", "message": {"content": ""}}]},
            unsafe_exception_type("unsafe"),
        ]
    )

    with pytest.raises(namespace["ReviewPreflightError"]) as failure:
        preflight([flaky], client=client)

    row = failure.value.report["routes"][0]
    assert row["error_type"] == "provider_error"
    assert "http_status" not in row


def test_escalated_probe_transport_exception_clears_stale_base_attempt_diagnostics() -> None:
    """Regression for Devin Review's escalation-failures-retain-stale-
    diagnostics finding: when the escalated attempt raises an exception (no
    response object at all for that attempt), ``finish_reason`` and
    ``reasoning_without_content`` must not silently keep the BASE attempt's
    values -- the same mixed-attempt-telemetry bug class already fixed for
    the escalated-empty and escalated-success outcomes, here closed for the
    escalated-exception outcome too. This variant is a bare transport
    failure (no HTTP status at all).
    """
    namespace = _load_launcher()
    preflight = namespace["_preflight_review_agents"]

    flaky = SimpleNamespace(
        id="nvidia_nim_flaky_transport", provider_name="nvidia_nim", model="flaky/free"
    )
    client = _SequencedClient(
        [
            {"choices": [{"finish_reason": "length", "message": {"content": ""}}]},
            TimeoutError("connection timed out with zero bytes received"),
        ]
    )

    with pytest.raises(namespace["ReviewPreflightError"]) as failure:
        preflight([flaky], client=client)

    row = failure.value.report["routes"][0]
    assert row["attempts"] == 2
    assert row["error_type"] == "TimeoutError"
    assert "http_status" not in row
    # The base attempt's finish_reason=="length"/reasoning_without_content
    # must not linger: there is no response for THIS (escalated) attempt to
    # describe, so both fields are simply absent.
    assert "finish_reason" not in row
    assert "reasoning_without_content" not in row


def test_escalated_probe_http_exception_clears_stale_base_attempt_diagnostics() -> None:
    """The same regression as above, for a genuine HTTP rejection (an HTTP
    status is present) rather than a bare transport failure -- either way,
    the base attempt's stale diagnostic fields must not survive.
    """
    namespace = _load_launcher()
    preflight = namespace["_preflight_review_agents"]

    class _HttpError(RuntimeError):
        """A synthetic exception carrying an HTTP status, like a real client's."""

        code = 500

    flaky = SimpleNamespace(
        id="nvidia_nim_flaky_http", provider_name="nvidia_nim", model="flaky/free"
    )
    client = _SequencedClient(
        [
            {"choices": [{"finish_reason": "length", "message": {"content": ""}}]},
            _HttpError("provider rejected the request"),
        ]
    )

    with pytest.raises(namespace["ReviewPreflightError"]) as failure:
        preflight([flaky], client=client)

    row = failure.value.report["routes"][0]
    assert row["attempts"] == 2
    assert row["error_type"] == "_HttpError"
    assert row["http_status"] == 500
    assert "finish_reason" not in row
    assert "reasoning_without_content" not in row


def test_escalated_empty_response_updates_both_telemetry_fields_together() -> None:
    """``finish_reason`` and ``reasoning_without_content`` must describe the
    SAME (final) attempt -- regression for Devin Review's mixed-attempt
    telemetry finding. The base attempt matches Trigger B via
    ``finish_reason == "length"`` (``reasoning_without_content`` is False);
    the escalated attempt comes back with a completely different signature
    (no ``finish_reason`` at all, but a populated ``reasoning`` field with no
    content). Both fields must end up describing attempt 2, not a stale mix
    of attempt 1's ``reasoning_without_content`` with attempt 2's
    ``finish_reason``.
    """
    namespace = _load_launcher()
    preflight = namespace["_preflight_review_agents"]

    still_starved = SimpleNamespace(
        id="nvidia_nim_still_starved", provider_name="nvidia_nim", model="starved/free"
    )
    client = _SequencedClient(
        [
            {"choices": [{"finish_reason": "length", "message": {"content": ""}}]},
            {
                "choices": [
                    {"message": {"content": "", "reasoning": "still reasoning, no answer yet"}}
                ]
            },
        ]
    )

    with pytest.raises(namespace["ReviewPreflightError"]) as failure:
        preflight([still_starved], client=client)

    row = failure.value.report["routes"][0]
    assert row["attempts"] == 2
    # Both fields reflect the escalated (final) attempt, not the base one.
    assert row["finish_reason"] == "unknown"
    assert row["reasoning_without_content"] is True


def test_preflight_fails_closed_when_every_route_rejects() -> None:
    """A healthy HTTP process is not review-ready without one live LLM route."""
    namespace = _load_launcher()
    preflight = namespace.get("_preflight_review_agents")
    error_type = namespace.get("ReviewPreflightError")
    assert callable(preflight), "launcher must expose provider-route preflight"
    assert isinstance(error_type, type), (
        "launcher must expose a typed preflight failure"
    )

    agent = SimpleNamespace(
        id="openrouter_rejected", provider_name="openrouter", model="rejected/free"
    )
    client = _ProbeClient({agent.id: TimeoutError("provider timed out")})

    with pytest.raises(error_type, match="no provider route passed"):
        preflight([agent], client=client)


def test_preflight_uses_priced_fallback_only_after_primary_routes_reject() -> None:
    """A live primary route wins; priced fallback is evidence-triggered only."""
    namespace = _load_launcher()
    preflight = namespace["_preflight_with_fallback"]
    primary = SimpleNamespace(
        id="openrouter_free", provider_name="openrouter", model="free/model"
    )
    fallback = SimpleNamespace(
        id="openrouter_priced", provider_name="openrouter", model="priced/model"
    )
    client = _ProbeClient(
        {primary.id: TimeoutError("unavailable"), fallback.id: _openai_text("OK")}
    )

    viable, report, fallback_used = preflight([primary], [fallback], client=client)

    assert viable == [fallback]
    assert fallback_used is True
    assert report["fallback_reason"] == "primary_routes_unavailable"
    assert report["primary_attempt"]["ready_count"] == 0
    # The fallback route's base probe succeeds and is then confirmed at the
    # real serving budget (ContextualWisdomLab/.github#1454) before being
    # admitted, so it makes two calls.
    assert [call[0] for call in client.calls] == [primary, fallback, fallback]

    ready_client = _ProbeClient(
        {primary.id: _openai_text("OK"), fallback.id: _openai_text("unused")}
    )
    viable, report, fallback_used = preflight(
        [primary], [fallback], client=ready_client
    )
    assert viable == [primary]
    assert fallback_used is False
    assert "fallback_reason" not in report
    # Likewise, the primary route's base-probe success is confirmed at the
    # real serving budget before admission -- two calls, both to primary.
    assert [call[0] for call in ready_client.calls] == [primary, primary]

    failing_client = _ProbeClient(
        {primary.id: TimeoutError("unavailable"), fallback.id: RuntimeError("rejected")}
    )
    with pytest.raises(namespace["ReviewPreflightError"]) as failure:
        preflight([primary], [fallback], client=failing_client)
    assert failure.value.report["ready_count"] == 0
    assert failure.value.report["primary_attempt"]["ready_count"] == 0


def test_preflight_advances_to_next_bounded_batch() -> None:
    """Rejected first-batch routes do not hide a later discovered live route."""
    namespace = _load_launcher()
    preflight = namespace["_preflight_review_agent_batches"]
    batch_size = namespace["REVIEW_PREFLIGHT_BATCH_SIZE"]
    agents = [
        SimpleNamespace(
            id=f"route_{index}", provider_name="openrouter", model=f"model/{index}"
        )
        for index in range(batch_size + 1)
    ]
    outcomes = {agent.id: TimeoutError("unavailable") for agent in agents[:-1]}
    outcomes[agents[-1].id] = _openai_text("OK")
    client = _ProbeClient(outcomes)

    viable, report = preflight(agents, client=client)

    assert viable == [agents[-1]]
    assert report["probed_count"] == batch_size + 1
    assert report["ready_count"] == 1
    assert report["batch_size"] == batch_size
    assert {call[0].id for call in client.calls[:batch_size]} == {
        agent.id for agent in agents[:batch_size]
    }
    assert client.calls[-1][0] == agents[-1]


class _PerAgentSequencedClient:
    """Return each agent's OWN configured attempt sequence, thread-safely.

    Unlike ``_SequencedClient`` (a single global sequence consumed strictly
    in call order -- unsuitable once several agents' calls can interleave
    unpredictably across concurrent batch threads), this looks up the next
    outcome by (agent id, that agent's own call count), tracked per agent id
    under a lock, so each candidate's own base-then-second-attempt sequence
    stays deterministic regardless of how batch threads happen to interleave.
    """

    def __init__(self, outcomes: dict[str, list[object]]) -> None:
        self._outcomes = outcomes
        self._counts: dict[str, int] = {}
        self._lock = threading.Lock()
        self.calls: list[tuple[object, str, dict[str, object]]] = []

    def proxy_send_once(
        self, agent: object, endpoint: str, payload: dict[str, object]
    ) -> dict[str, object]:
        """Capture one request and return that agent's next configured outcome."""
        agent_id = str(getattr(agent, "id"))
        with self._lock:
            index = self._counts.get(agent_id, 0)
            self._counts[agent_id] = index + 1
        self.calls.append((agent, endpoint, payload))
        outcome = self._outcomes[agent_id][index]
        if isinstance(outcome, BaseException):
            raise outcome
        assert isinstance(outcome, dict)
        return outcome


def test_batched_preflight_first_batch_confirmations_do_not_starve_a_later_healthy_route() -> None:
    """Regression for Devin Review's "Later healthy routes cannot start"
    finding (`ContextualWisdomLab/.github#1415`) on the batched preflight
    entry point ``_preflight_review_agent_batches`` -- the exact scenario
    described in the finding, reproduced end to end.

    The first ``REVIEW_PREFLIGHT_BATCH_SIZE`` candidates (batch 1) each
    succeed their cheap base probe -- so each needs a mandatory confirmation
    at the real serving budget -- but each then genuinely FAILS that
    confirmation (a real "usable at 16 tokens, unusable at 4096" route,
    correctly not admitted). A fifth candidate (batch 2) also succeeds its
    base probe AND would succeed its confirmation too, if it ever got the
    chance.

    Under the pre-fix code, all four batch-1 candidates' confirmations drew
    from the SAME shared ``_EscalationBudget`` capped at
    ``REVIEW_PREFLIGHT_MAX_ESCALATIONS`` (4) -- exactly enough for four
    candidates to each reserve one slot before failing confirmation on
    their own merits, permanently exhausting that shared counter. The fifth
    candidate's later, unrelated confirmation request was then denied
    purely by ``_EscalationBudget.try_reserve()`` returning ``False`` --
    ``escalation_budget_exhausted`` -- never even making its confirmation
    call, regardless of the fact that it would have passed. With a budget
    dedicated to confirmations specifically (this fix), the fifth candidate
    is unaffected by batch 1's unrelated confirmation attempts and is
    correctly admitted.
    """
    namespace = _load_launcher()
    preflight = namespace["_preflight_review_agent_batches"]
    batch_size = namespace["REVIEW_PREFLIGHT_BATCH_SIZE"]
    max_escalations = namespace["REVIEW_PREFLIGHT_MAX_ESCALATIONS"]
    assert batch_size == max_escalations, (
        "this regression specifically needs one batch's worth of candidates "
        "to exactly exhaust the (old, shared) escalation budget"
    )

    ok = _openai_text("OK")
    # Genuinely fails its confirmation: usable at the base budget, empty (no
    # budget-too-small signature) at the real serving budget -- correctly
    # never admitted, regardless of which budget backed the attempt.
    fails_confirmation = {"choices": [{"message": {"content": ""}}]}

    batch_one_serving_incompatible = [
        SimpleNamespace(id=f"batch1_narrow_{index}", provider_name="openrouter", model="x/free")
        for index in range(batch_size)
    ]
    later_healthy_route = SimpleNamespace(
        id="batch2_genuinely_healthy", provider_name="nvidia_nim", model="healthy/free"
    )
    client = _PerAgentSequencedClient(
        {agent.id: [ok, fails_confirmation] for agent in batch_one_serving_incompatible}
        | {later_healthy_route.id: [ok, ok]}
    )

    viable, report = preflight(
        [*batch_one_serving_incompatible, later_healthy_route], client=client
    )

    # The fifth candidate -- genuinely healthy at both budgets -- must be
    # admitted. It must NOT be recorded as denied by escalation-budget
    # exhaustion caused by four entirely different candidates' confirmations.
    assert viable == [later_healthy_route]
    later_route_row = next(
        row for row in report["routes"] if row["agent_id"] == later_healthy_route.id
    )
    assert later_route_row["status"] == "ready"
    assert later_route_row["confirmed_at_serving_budget"] is True
    assert "error_type" not in later_route_row

    # The four batch-1 candidates are correctly NOT admitted -- on their own
    # merits (a real confirmation failure), never on budget exhaustion.
    batch_one_rows = [
        row for row in report["routes"] if row["agent_id"] != later_healthy_route.id
    ]
    assert len(batch_one_rows) == batch_size
    for row in batch_one_rows:
        assert row["status"] == "rejected"
        assert row["error_type"] == "invalid_chat_response"

    # The escalation (rescue) budget was never touched at all -- none of
    # these candidates ever failed their base probe.
    assert report["escalations_used"] == 0
    # Confirmation budget evidence: five candidates each made exactly one
    # confirmation attempt.
    assert report["confirmations_used"] == batch_size + 1


def test_fallback_escalation_budget_is_shared_with_primary_and_bounds_worst_case() -> None:
    """Regression for Devin Review's fallback-retries-exceed-startup-deadline
    finding: ``_preflight_review_agents`` used to start ``escalations_used``
    fresh on every call, so ``_preflight_with_fallback`` calling it twice
    could spend the full ``REVIEW_PREFLIGHT_MAX_ESCALATIONS`` budget in EACH
    stage -- blowing past the preflight phase's own worst-case budget and
    contradicting the ADR's own claimed worst case.

    This drives every primary and fallback route (the exact
    ``REVIEW_PREFLIGHT_MAX_TOTAL_ROUTES`` split) through a response that
    always qualifies for escalation and never resolves, so every one of them
    *would* escalate if the budget were not shared. Asserts the run spends at
    most ``REVIEW_PREFLIGHT_MAX_ESCALATIONS`` escalations in total (not per
    stage), and that the resulting worst case stays within
    ``REVIEW_PREFLIGHT_WORST_CASE_SECONDS`` -- the preflight phase's own
    coordinated budget, which the sidecar's startup watchdog now composes
    with discovery's own worst case rather than treating as the whole startup
    budget (see ``test_startup_watchdog_covers_discovery_plus_preflight_with_headroom``
    for that composition) -- both stages' escalation counts are visible in
    the returned evidence.

    The worst-case *formula* (not the shared-budget invariant it measures)
    differs from this test's pre-batching original: routes are now probed in
    concurrent batches of ``REVIEW_PREFLIGHT_BATCH_SIZE``, so a batch's own
    wall time is bounded by its slowest candidate, not the sum of every
    candidate in it -- raw attempt count is no longer directly proportional
    to wall-clock time the way a purely sequential loop's was.
    """
    namespace = _load_launcher()
    preflight = namespace["_preflight_with_fallback"]
    max_escalations = namespace["REVIEW_PREFLIGHT_MAX_ESCALATIONS"]
    timeout_seconds = namespace["REVIEW_PREFLIGHT_TIMEOUT_SECONDS"]
    batch_size = namespace["REVIEW_PREFLIGHT_BATCH_SIZE"]
    primary_limit = namespace["REVIEW_PREFLIGHT_PRIMARY_ROUTE_LIMIT"]
    total_route_limit = namespace["REVIEW_PREFLIGHT_MAX_TOTAL_ROUTES"]
    fallback_limit = total_route_limit - primary_limit

    budget_starved_response = {
        "choices": [{"finish_reason": "length", "message": {"content": ""}}]
    }
    primary_agents = [
        SimpleNamespace(id=f"primary_{index}", provider_name="openrouter", model="x/free")
        for index in range(primary_limit)
    ]
    fallback_agents = [
        SimpleNamespace(id=f"fallback_{index}", provider_name="openrouter", model="y/priced")
        for index in range(fallback_limit)
    ]
    client = _ProbeClient(
        {agent.id: dict(budget_starved_response) for agent in [*primary_agents, *fallback_agents]}
    )

    with pytest.raises(namespace["ReviewPreflightError"]) as failure:
        preflight(primary_agents, fallback_agents, client=client)

    report = failure.value.report
    assert report["escalations_used"] == max_escalations
    assert report["primary_attempt"]["escalations_used"] == max_escalations

    total_attempts = len(client.calls)
    # Exactly the ADR's own worst-case arithmetic, batching-independent: one
    # base attempt per candidate across both stages, plus the shared
    # escalation cap.
    assert total_attempts == total_route_limit + max_escalations

    # Batched, concurrent worst case: candidates run REVIEW_PREFLIGHT_BATCH_SIZE
    # at a time, so a batch's wall time is bounded by its slowest candidate.
    # In the fully pessimistic case every batch contains an escalating
    # candidate (base attempt + escalated attempt, sequential within that one
    # candidate's own thread) -- 2 * timeout_seconds per batch -- even though
    # at most max_escalations of the batches actually can.
    num_batches = -(-total_route_limit // batch_size)  # ceil division
    worst_case_seconds = num_batches * 2 * timeout_seconds
    assert worst_case_seconds == namespace["REVIEW_PREFLIGHT_WORST_CASE_SECONDS"], (
        f"observed worst-case preflight time ({worst_case_seconds}s across "
        f"{num_batches} batches) must match the launcher's own declared "
        "REVIEW_PREFLIGHT_WORST_CASE_SECONDS -- a mismatch means that "
        "constant no longer reflects this module's real batching behavior, "
        "which would desynchronize it from the sidecar's derived startup "
        "watchdog (REVIEW_STARTUP_WATCHDOG_SECONDS)"
    )


def test_startup_watchdog_covers_discovery_plus_preflight_with_headroom() -> None:
    """Regression for Devin Review's "Startup watchdog preempts valid preflight"
    finding: the sidecar's startup watchdog used to be a bare, uncoordinated
    180s shell constant that only happened to exceed the *probing-only* worst
    case (120s) by coincidence, while never accounting for discovery's own
    worst case (which runs first, in the SAME process, before ``/healthz`` can
    respond) at all -- a fully correct, on-budget run of ~330s discovery +
    ~120s probing = ~450s could be, and was (at the smaller, undercounted
    105s discovery figure this test used to pin), killed by too small a
    watchdog before it ever reported a result.

    This is a purely static consistency check (no timing simulation, no real
    sleeps -- CI-safe and non-flaky) that recomputes both worst cases
    independently from the launcher's own primitive constants and asserts
    ``REVIEW_STARTUP_WATCHDOG_SECONDS`` -- the single source of truth the
    shell sidecar now imports rather than hard-coding its own number --
    actually covers their sum, with non-negative explicit headroom. It also
    locks in the real, literal current numbers as a regression: any future
    change to a budget constant that silently desynchronizes the derived
    watchdog fails this test immediately, rather than only failing much later
    in a live CI run that happens to hit the worst case. See
    ``test_startup_watchdog_covers_a_retry_heavy_discovery_reconstruction``
    below for the companion test that independently reconstructs the 330s
    discovery figure from the real, enumerated request structure rather than
    trusting this module's own arithmetic -- exactly what Devin Review's
    follow-up finding says a verbatim-constant test alone cannot catch.
    """
    namespace = _load_launcher()

    discovery_calls = namespace["REVIEW_DISCOVERY_MAX_SEQUENTIAL_HTTP_CALLS"]
    discovery_timeout = namespace["REVIEW_DISCOVERY_TIMEOUT_SECONDS"]
    recomputed_discovery_worst_case = discovery_calls * discovery_timeout
    assert recomputed_discovery_worst_case == namespace["REVIEW_DISCOVERY_WORST_CASE_SECONDS"]
    # Verified directly against the vendored contextual_orchestrator.model_discovery
    # source at ORCHESTRATOR_PIN_SHA (see the launcher's own module-level
    # comment for the full call-by-call derivation): 22 sequential-call-
    # equivalents at up to 15.0s each.
    assert recomputed_discovery_worst_case == 330.0

    total_routes = namespace["REVIEW_PREFLIGHT_MAX_TOTAL_ROUTES"]
    batch_size = namespace["REVIEW_PREFLIGHT_BATCH_SIZE"]
    preflight_timeout = namespace["REVIEW_PREFLIGHT_TIMEOUT_SECONDS"]
    num_batches = -(-total_routes // batch_size)  # ceil division
    recomputed_preflight_worst_case = num_batches * 2 * preflight_timeout
    assert recomputed_preflight_worst_case == namespace["REVIEW_PREFLIGHT_WORST_CASE_SECONDS"]
    assert recomputed_preflight_worst_case == 120

    headroom = namespace["REVIEW_STARTUP_HEADROOM_SECONDS"]
    assert headroom >= 0, "headroom must never be negative -- that would silently under-cover"

    combined_worst_case = recomputed_discovery_worst_case + recomputed_preflight_worst_case
    watchdog = namespace["REVIEW_STARTUP_WATCHDOG_SECONDS"]
    assert isinstance(watchdog, int)
    assert watchdog == int(combined_worst_case + headroom)
    # The core invariant Devin Review's finding is about: the watchdog must
    # cover the full combined worst case, not just one phase of it.
    assert watchdog >= combined_worst_case
    # Locks in the real current total (450s combined + 30s headroom), not a
    # loosely-fitting range, so a future change to any input constant is a
    # deliberate, visible edit to this test rather than a silent drift.
    assert watchdog == 480


def test_startup_watchdog_covers_a_retry_heavy_discovery_reconstruction() -> None:
    """Independently rebuild the worst-case call count from the real request
    structure and assert the derived watchdog still covers its time budget.

    Regression for Devin Review's exact follow-up finding on the discovery
    budget ("Recompute the startup watchdog from the actual bounded request
    structure ... extend tests with retry-heavy discovery timing rather than
    asserting the current constant verbatim"): a test that only pins
    ``REVIEW_DISCOVERY_MAX_SEQUENTIAL_HTTP_CALLS == 22`` (as
    ``test_startup_watchdog_covers_discovery_plus_preflight_with_headroom``
    above does) would pass just as happily if that constant were still wrong
    in the same direction the original ``7`` was -- it re-encodes whatever
    the module currently claims, it does not check the claim against the
    real, enumerated request structure. This test instead reconstructs the
    worst case from first principles (each sub-count independently justified
    against the vendored ``contextual_orchestrator.model_discovery`` source
    at ``ORCHESTRATOR_PIN_SHA`` in the launcher module's own comment) and
    proves the *reconstructed* time budget -- not just the module's own
    arithmetic on its own constants -- is what the watchdog actually covers.
    """
    namespace = _load_launcher()
    discovery_timeout = namespace["REVIEW_DISCOVERY_TIMEOUT_SECONDS"]

    # (a) The shared Models.dev fetch retries transient failures up to
    # _MODELS_DEV_FETCH_ATTEMPTS=3 times in the pinned source -- a retry-
    # heavy scenario is exactly a run where every one of those attempts is a
    # transient failure (timeout/connection reset) before the caller finally
    # gives up and returns None (still a valid, non-raising outcome).
    models_dev_attempts = 3
    assert models_dev_attempts == namespace["REVIEW_DISCOVERY_MODELS_DEV_MAX_ATTEMPTS"]

    # (b) Every one of the sidecar's five bootstrapped credentials
    # (openai, openrouter, nvidia_nim, nvidia_nim_sub, bytez) gets its own
    # primary-fetch attempt plus one retry attempt in a retry-heavy run.
    credentialed_sources = ("openai", "openrouter", "nvidia_nim", "nvidia_nim_sub", "bytez")
    attempts_per_source = 2  # base attempt + one transient-failure retry
    assert len(credentialed_sources) == namespace["REVIEW_DISCOVERY_CREDENTIALED_SOURCE_COUNT"]
    assert attempts_per_source == namespace["REVIEW_DISCOVERY_SOURCE_MAX_ATTEMPTS"]

    # (c) OpenRouter alone makes two further single-attempt calls (ZDR
    # endpoints, provider policies) beyond its own primary fetch already
    # counted in (b), plus one concurrent endpoint-feed round per <=8
    # currently free-priced models. A retry-heavy scenario does not add
    # retries to these three (none of them retry in the pinned source), but
    # it does mean discovery cannot skip them by finishing early.
    openrouter_single_extra_calls = 2
    free_endpoint_round_cap = 5
    assert openrouter_single_extra_calls == namespace[
        "REVIEW_DISCOVERY_OPENROUTER_SINGLE_EXTRA_CALLS"
    ]
    assert free_endpoint_round_cap == namespace[
        "REVIEW_DISCOVERY_OPENROUTER_FREE_ENDPOINT_ROUND_CAP"
    ]

    # (d) Two trailing global calls run once, after every source above, with
    # an OpenRouter credential registered: the (separate, non-cached)
    # _openrouter_zdr_model_ids() fetch and the credits check.
    trailing_global_calls = 2
    assert trailing_global_calls == namespace["REVIEW_DISCOVERY_TRAILING_GLOBAL_CALLS"]

    reconstructed_call_count = (
        models_dev_attempts
        + len(credentialed_sources) * attempts_per_source
        + openrouter_single_extra_calls
        + free_endpoint_round_cap
        + trailing_global_calls
    )
    assert reconstructed_call_count == 22
    assert reconstructed_call_count == namespace["REVIEW_DISCOVERY_MAX_SEQUENTIAL_HTTP_CALLS"]

    reconstructed_discovery_seconds = reconstructed_call_count * discovery_timeout
    reconstructed_combined_seconds = (
        reconstructed_discovery_seconds + namespace["REVIEW_PREFLIGHT_WORST_CASE_SECONDS"]
    )
    watchdog = namespace["REVIEW_STARTUP_WATCHDOG_SECONDS"]
    # The core assertion: the derived watchdog must cover a genuinely
    # independently-reconstructed retry-heavy worst case, not merely the
    # module's own (possibly still wrong) restatement of it.
    assert watchdog >= reconstructed_combined_seconds


def test_sidecar_derives_its_watchdog_from_the_launcher_single_source_of_truth() -> None:
    """The shell watchdog must import, not hard-code, the coordinated deadline.

    Guards against the exact regression class this fix addresses: a future
    edit that changes a launcher timing constant (discovery calls, batch
    size, escalation timeout, ...) must automatically change the sidecar's
    watchdog too, with no second place to remember to update by hand.
    """
    namespace = _load_launcher()
    sidecar_text = _SIDECAR.read_text(encoding="utf-8")

    assert (
        "from scripts.ci.contextual_orchestrator_review_launcher "
        "import REVIEW_STARTUP_WATCHDOG_SECONDS" in sidecar_text
    )
    assert 'sidecar_startup_watchdog_seconds="$(' in sidecar_text
    assert '[ "$SECONDS" -ge "$sidecar_startup_watchdog_seconds" ]' in sidecar_text
    # The old, uncoordinated hard-coded bound must be gone from the watchdog
    # comparison -- not just supplemented by the new derived one.
    assert '[ "$i" -ge 180 ]' not in sidecar_text
    assert "-ge 180" not in sidecar_text
    # Regression for Devin Review's "Startup watchdog counts polls, not
    # seconds" finding (ContextualWisdomLab/.github#1415): the comparison
    # must read bash's real wall-clock $SECONDS builtin, not a hand-rolled
    # poll counter incremented once per loop iteration regardless of how
    # long that iteration's own curl call took.
    assert '[ "$i" -ge "$sidecar_startup_watchdog_seconds" ]' not in sidecar_text

    # Exercise the exact derivation command the sidecar script runs, proving
    # it truly needs no vendored dependency yet at that point in the script
    # (the launcher module's top-level imports are deliberately stdlib-only).
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from scripts.ci.contextual_orchestrator_review_launcher import "
                "REVIEW_STARTUP_WATCHDOG_SECONDS; print(REVIEW_STARTUP_WATCHDOG_SECONDS)"
            ),
        ],
        cwd=str(_REPO_ROOT),
        env={**os.environ, "PYTHONPATH": str(_REPO_ROOT)},
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == str(namespace["REVIEW_STARTUP_WATCHDOG_SECONDS"])


_HEALTHZ_WAIT_BLOCK_START = "SECONDS=0\nuntil curl -fsSL --max-time 2 "
_HEALTHZ_WAIT_BLOCK_END = "\n  sleep 1\ndone"


def _run_healthz_wait_loop(
    tmp_path: Path,
    *,
    watchdog_seconds: int,
    curl_delay_seconds: float,
) -> tuple[subprocess.CompletedProcess[str], float]:
    """Execute the sidecar's real healthz-wait loop against a fake, always-failing curl.

    Extracts the exact, current source of the loop from the tracked sidecar
    script (the same technique ``_run_gateway_retry_loop`` uses above) so a
    future edit to the loop is automatically exercised here instead of
    silently drifting from a second, hand-copied duplicate.

    Args:
        tmp_path: Pytest's per-test scratch directory.
        watchdog_seconds: Value for ``sidecar_startup_watchdog_seconds``.
        curl_delay_seconds: How long the fake ``curl`` sleeps before failing,
            simulating a slow-but-still-under-its-own-``--max-time`` health
            probe.

    Returns:
        The completed harness process and the measured real wall-clock time
        the loop took to fail, as observed from outside the subprocess.
    """
    sidecar_text = _SIDECAR.read_text(encoding="utf-8")
    start = sidecar_text.index(_HEALTHZ_WAIT_BLOCK_START)
    end = sidecar_text.index(_HEALTHZ_WAIT_BLOCK_END, start) + len(_HEALTHZ_WAIT_BLOCK_END)
    loop_block = sidecar_text[start:end]

    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    fake_curl = fake_bin / "curl"
    fake_curl.write_text(
        f"#!/usr/bin/env bash\nsleep {curl_delay_seconds}\nexit 1\n",
        encoding="utf-8",
    )
    fake_curl.chmod(0o755)

    sidecar_stderr = tmp_path / "sidecar-stderr.txt"
    sidecar_stderr.write_text("", encoding="utf-8")
    preflight_report = tmp_path / "preflight.json"
    preflight_report.write_text("{}", encoding="utf-8")

    harness = tmp_path / "harness.sh"
    harness.write_text(
        "set -euo pipefail\n"
        "log() { printf '[test-sidecar] %s\\n' \"$*\"; }\n"
        'fail() { log "error: $*" >&2; exit 1; }\n'
        # The real loop's "sidecar exited early" branch calls `kill -0
        # "$sidecar_pid"` to tell a dead sidecar apart from one still
        # starting; stub it so this harness exercises only the watchdog
        # deadline comparison, never that other branch.
        "kill() { return 0; }\n"
        "wait_for_sidecar_sanitizers() { :; }\n"
        "sidecar_pid=$$\n"
        'ORCHESTRATOR_HOST="127.0.0.1"\n'
        'ORCHESTRATOR_PORT="18080"\n'
        f"sidecar_startup_watchdog_seconds={watchdog_seconds}\n"
        f'sidecar_stderr="{sidecar_stderr}"\n'
        f'preflight_report="{preflight_report}"\n'
        + loop_block
        + "\n",
        encoding="utf-8",
    )

    start_time = time.monotonic()
    result = subprocess.run(
        ["bash", str(harness)],
        env={
            **os.environ,
            "PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}",
        },
        text=True,
        capture_output=True,
        check=False,
    )
    elapsed = time.monotonic() - start_time
    return result, elapsed


def test_healthz_wait_loop_fires_near_the_wall_clock_deadline_not_a_poll_count(
    tmp_path: Path,
) -> None:
    """Regression for Devin Review's "Startup watchdog counts polls, not
    seconds" finding (ContextualWisdomLab/.github#1415).

    Before the fix, the loop incremented a plain poll counter ``i`` once per
    iteration and compared *that* to ``sidecar_startup_watchdog_seconds`` --
    even though a single iteration's real cost is the curl call's own
    duration (up to its ``--max-time``) plus the trailing ``sleep 1``. With a
    health probe that itself takes close to its full timeout, that made the
    watchdog run roughly 3x longer than its configured bound (255s
    configured, ~765s observed worst case).

    This drives the sidecar's real, tracked healthz-wait loop (extracted
    verbatim, not a hand-copied duplicate) against a fake ``curl`` that
    always fails after a deliberately slow ``curl_delay_seconds``, with a
    small configured watchdog. It asserts the loop fails close to the
    *configured* wall-clock seconds (allowing headroom for the cadence of
    one in-flight curl call plus one ``sleep 1``), and, crucially, well
    under 3x that bound -- the exact regression class this test guards
    against.
    """
    watchdog_seconds = 3
    curl_delay_seconds = 2.0

    result, elapsed = _run_healthz_wait_loop(
        tmp_path,
        watchdog_seconds=watchdog_seconds,
        curl_delay_seconds=curl_delay_seconds,
    )

    assert result.returncode == 1, result.stderr
    assert (
        f"sidecar did not become healthy within {watchdog_seconds}s" in result.stderr
    )
    # The old, buggy poll-counting comparison would need
    # `watchdog_seconds` full iterations -- each costing
    # curl_delay_seconds + 1s of sleep -- before firing: roughly
    # watchdog_seconds * (curl_delay_seconds + 1) = 9s here. The fixed,
    # real-wall-clock comparison fires as soon as accumulated curl time
    # alone crosses the deadline: roughly one extra curl call past the
    # bound, ~5s here. Assert comfortably between the two, strictly below
    # the poll-counting bound -- proving this is not that regression.
    poll_counting_bound = watchdog_seconds * (curl_delay_seconds + 1)
    assert elapsed < poll_counting_bound - 1, (
        f"loop took {elapsed:.1f}s to fail, at or beyond the poll-counting "
        f"bound of {poll_counting_bound:.1f}s that this fix removes -- the "
        "watchdog is counting polls again, not real wall-clock seconds"
    )
    # A lower bound too: the loop cannot legitimately fail before at least
    # one curl call has run (the deadline is only checked after a curl
    # attempt), so it must take at least curl_delay_seconds.
    assert elapsed >= curl_delay_seconds


def test_healthz_wait_loop_reports_wall_clock_seconds_not_a_poll_count(
    tmp_path: Path,
) -> None:
    """The failure message's own reported bound must not silently change.

    A narrower companion to the timing test above: even independent of how
    long the loop actually took, the fixed loop's fail() message must still
    name the *configured* ``sidecar_startup_watchdog_seconds`` -- proving
    the message-formatting side of the fix (``$SECONDS`` swapped in for
    ``$i`` in both the comparison and the two places it is interpolated)
    did not regress independently of the timing behavior.
    """
    result, _elapsed = _run_healthz_wait_loop(
        tmp_path, watchdog_seconds=2, curl_delay_seconds=1.5
    )

    assert result.returncode == 1, result.stderr
    assert "sidecar did not become healthy within 2s" in result.stderr


def test_preflight_stage_limits_share_one_startup_budget() -> None:
    """Free-first and priced-fallback probes share one bounded route budget."""
    namespace = _load_launcher()
    primary = namespace["_bounded_primary_catalog_limit"](
        99, pool="auto", has_free_rows=True
    )
    fallback = namespace["_bounded_fallback_catalog_limit"](99, primary_count=primary)
    assert (primary, fallback) == (8, 16)
    assert primary + fallback == namespace["REVIEW_PREFLIGHT_MAX_TOTAL_ROUTES"]


def test_production_defaults_expose_the_complete_bounded_catalog() -> None:
    """Launcher and shell defaults must not silently restore the old 12-route cap."""
    launcher = _LAUNCHER.read_text(encoding="utf-8")
    sidecar = _SIDECAR.read_text(encoding="utf-8")

    assert 'ORCHESTRATOR_CATALOG_LIMIT", "24"' in launcher
    assert 'CATALOG_LIMIT="${ORCHESTRATOR_CATALOG_LIMIT:-24}"' in sidecar
    assert "REVIEW_PREFLIGHT_MAX_TOTAL_ROUTES = 24" in launcher
    # Regression for ContextualWisdomLab/.github#1415's Devin follow-up
    # finding: the shell used to always export a hard-coded literal `8`
    # default for ORCHESTRATOR_CATALOG_ACCOUNT_CAP, which bypassed the
    # launcher's own _catalog_account_cap(DEFAULT_ACCOUNT_CAP)=4 fallback in
    # every real run (os.environ.get only falls back when the key is
    # ABSENT). The shell must no longer materialize that literal and must
    # instead derive the same policy.DEFAULT_ACCOUNT_CAP the launcher does.
    assert 'CATALOG_ACCOUNT_CAP="${ORCHESTRATOR_CATALOG_ACCOUNT_CAP:-8}"' not in sidecar
    assert (
        "from scripts.ci.contextual_orchestrator_review_policy import "
        "DEFAULT_ACCOUNT_CAP; print(DEFAULT_ACCOUNT_CAP)"
    ) in sidecar


def test_catalog_account_cap_defaults_to_the_caller_supplied_policy_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The per-account cap falls back to ``policy.DEFAULT_ACCOUNT_CAP``, not the total budget.

    Regression for a real, observed failure mode
    (ContextualWisdomLab/.github#1415, reported as "빈 깡통 경로 너무 많다"): this
    module's ``_catalog_family_cap()`` helper (since renamed and fixed here --
    `main` PR #1487 landed the identical fix independently under the same
    final name) fell back to ``REVIEW_PREFLIGHT_MAX_TOTAL_ROUTES`` -- the
    *total* preflight budget -- instead of the intended per-account cap
    whenever its env var was unset. That silently disabled per-account
    diversification: in a live production run, two NVIDIA NIM credentials
    sharing one rate-limited upstream jointly consumed all 12 preflight
    slots, of which 10 (83%) were then rejected via 429/404/timeout. This
    helper must never resolve to the same value as the total-routes budget
    when given the real ``policy.DEFAULT_ACCOUNT_CAP``, which is strictly
    smaller.
    """
    namespace = _load_launcher()
    account_cap = namespace["_catalog_account_cap"]
    assert callable(account_cap)

    monkeypatch.delenv("ORCHESTRATOR_CATALOG_ACCOUNT_CAP", raising=False)
    cap = account_cap(policy.DEFAULT_ACCOUNT_CAP)
    assert cap == policy.DEFAULT_ACCOUNT_CAP
    assert cap != namespace["REVIEW_PREFLIGHT_MAX_TOTAL_ROUTES"]
    assert cap < namespace["REVIEW_PREFLIGHT_MAX_TOTAL_ROUTES"]

    # Reproduces the live evidence directly: 12 free routes split across just
    # two credential accounts (nvidia_nim / nvidia_nim_sub) sharing one
    # rate-limited upstream. At the default cap, neither account may absorb
    # more than its share of the bounded preflight budget.
    rows = [
        {
            "provider": "nvidia_nim" if index % 2 == 0 else "nvidia_nim_sub",
            "model": f"model{index}",
            "agent_id": f"nim_a{index}",
            "is_free": True,
            "prompt_price_per_1k": 0.0,
            "completion_price_per_1k": 0.0,
            "currency_code": "USD",
        }
        for index in range(12)
    ]
    catalog = policy.build_zdr_prioritized_catalog(
        policy.parse_discovery_report({"models": rows}),
        limit=12,
        account_cap=cap,
    )
    per_account: dict[str, int] = {}
    for agent in catalog["agents"]:
        account = policy.provider_account(agent["provider_name"])
        per_account[account] = per_account.get(account, 0) + 1
    assert per_account
    assert max(per_account.values()) <= policy.DEFAULT_ACCOUNT_CAP
    assert len(catalog["agents"]) <= 2 * policy.DEFAULT_ACCOUNT_CAP


def test_catalog_account_cap_honors_an_explicit_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An operator-set ``ORCHESTRATOR_CATALOG_ACCOUNT_CAP`` still takes effect."""
    namespace = _load_launcher()
    monkeypatch.setenv("ORCHESTRATOR_CATALOG_ACCOUNT_CAP", "6")
    assert namespace["_catalog_account_cap"](policy.DEFAULT_ACCOUNT_CAP) == 6


_CATALOG_ACCOUNT_CAP_BLOCK_START = (
    'if [ -n "${ORCHESTRATOR_CATALOG_ACCOUNT_CAP:-}" ]; then'
)


def _run_catalog_account_cap_derivation(
    *, override: str | None
) -> subprocess.CompletedProcess[str]:
    """Execute the sidecar's real per-account-cap derivation block in bash.

    Extracts the exact, current source of the derivation from the tracked
    sidecar script (the same technique
    ``test_sidecar_derives_its_watchdog_from_the_launcher_single_source_of_truth``
    and ``_run_healthz_wait_loop`` use above) so a future edit to the block
    is automatically exercised here instead of silently drifting from a
    second, hand-copied duplicate. Regression for
    ContextualWisdomLab/.github#1415's Devin follow-up finding: proves the
    shell itself -- not just the Python ``_catalog_account_cap`` helper in
    isolation -- resolves to ``policy.DEFAULT_ACCOUNT_CAP`` when no operator
    override is set, and to the override's exact value when one is.

    Args:
        override: Value to set ``ORCHESTRATOR_CATALOG_ACCOUNT_CAP`` to before
            running the block, or ``None`` to leave it genuinely unset.

    Returns:
        The completed harness process; ``stdout`` carries ``RESULT=<cap>``
        on success.
    """
    sidecar_text = _SIDECAR.read_text(encoding="utf-8")
    start = sidecar_text.index(_CATALOG_ACCOUNT_CAP_BLOCK_START)
    end = sidecar_text.index("esac\n", start) + len("esac\n")
    block = sidecar_text[start:end]
    assert "CATALOG_ACCOUNT_CAP" in block

    harness = (
        "set -euo pipefail\n"
        "log() { printf '[test-sidecar] %s\\n' \"$*\"; }\n"
        'fail() { log "error: $*" >&2; exit 1; }\n'
        f'ORG_REPO_ROOT="{_REPO_ROOT}"\n'
        f'sidecar_python="{sys.executable}"\n'
        + block
        + '\nprintf "RESULT=%s\\n" "$CATALOG_ACCOUNT_CAP"\n'
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(_REPO_ROOT)
    if override is None:
        env.pop("ORCHESTRATOR_CATALOG_ACCOUNT_CAP", None)
    else:
        env["ORCHESTRATOR_CATALOG_ACCOUNT_CAP"] = override
    return subprocess.run(
        ["bash", "-c", harness],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_sidecar_shell_derives_the_account_cap_default_from_policy_when_unset() -> None:
    """With no operator override, the SHELL (not just the Python helper) gets 4.

    This is the exact regression the just-landed
    ``_catalog_account_cap(DEFAULT_ACCOUNT_CAP)`` fix could not close on its
    own: that helper's env-unset fallback only runs if the shell genuinely
    never set the env var. Before this fix the shell always exported a
    literal ``8`` first, so this end-to-end path -- not the Python unit
    tested above -- is what previously stayed silently broken in production.
    """
    result = _run_catalog_account_cap_derivation(override=None)
    assert result.returncode == 0, result.stderr
    assert f"RESULT={policy.DEFAULT_ACCOUNT_CAP}" in result.stdout


def test_sidecar_shell_honors_an_explicit_account_cap_override() -> None:
    """An operator-set ``ORCHESTRATOR_CATALOG_ACCOUNT_CAP`` still wins in the shell."""
    result = _run_catalog_account_cap_derivation(override="6")
    assert result.returncode == 0, result.stderr
    assert "RESULT=6" in result.stdout


@pytest.mark.parametrize("bad_value", ["0", "-1", "abc"])
def test_sidecar_shell_rejects_an_invalid_account_cap_override(bad_value: str) -> None:
    """A malformed override must fail closed, matching the file's other digit checks."""
    result = _run_catalog_account_cap_derivation(override=bad_value)
    assert result.returncode == 1
    assert "ORCHESTRATOR_CATALOG_ACCOUNT_CAP must be a positive integer" in result.stderr


def test_sidecar_shell_treats_an_empty_override_as_unset() -> None:
    """``ORCHESTRATOR_CATALOG_ACCOUNT_CAP=""`` matches bash's own ``:-`` semantics.

    An explicitly empty override is indistinguishable from unset under the
    ``${VAR:-default}`` expansion this block (and the rest of this script)
    already relies on elsewhere -- e.g. the provider-secret presence loop's
    ``[ -n "${!secret_name:-}" ]`` -- so it must fall back to the derived
    policy default rather than reaching the digit-format check with an empty
    string.
    """
    result = _run_catalog_account_cap_derivation(override="")
    assert result.returncode == 0, result.stderr
    assert f"RESULT={policy.DEFAULT_ACCOUNT_CAP}" in result.stdout


def test_main_sources_the_account_cap_default_from_policy_not_a_magic_number() -> None:
    """``main()`` must wire the cap default from ``policy.DEFAULT_ACCOUNT_CAP``.

    A hand-typed literal (or, worse, a total-routes-scale constant) can
    silently drift out of sync with ``policy.DEFAULT_ACCOUNT_CAP`` with no
    test catching it -- the exact drift that produced
    ContextualWisdomLab/.github#1415's real preflight-budget waste. This
    source-level contract test pins both ``build_zdr_prioritized_catalog``
    call sites in ``main()`` to the single source of truth and forbids the
    old family-cap naming and the old total-routes fallback from reappearing.
    """
    source = _LAUNCHER.read_text(encoding="utf-8")
    assert source.count("account_cap=_catalog_account_cap(DEFAULT_ACCOUNT_CAP)") == 2
    assert "ORCHESTRATOR_CATALOG_FAMILY_CAP" not in source
    assert "_catalog_family_cap" not in source
    assert 'os.environ.get("ORCHESTRATOR_CATALOG_ACCOUNT_CAP", "4")' not in source


def test_zdr_admission_selects_priced_tier_when_free_routes_are_not_private() -> None:
    """Privacy admission precedes the free-first tier decision."""
    namespace = _load_launcher()
    admit = namespace["_zdr_admitted_rows"]
    rows = [
        {"provider": "openrouter", "model": "free/non-private"},
        {"provider": "openrouter", "model": "priced/private"},
    ]

    def checker(provider: str, *, model: str, zdr_endpoints: frozenset[str]) -> bool:
        return f"{provider}:{model}" in zdr_endpoints

    admitted = admit(
        rows,
        require_zdr=True,
        zdr_endpoints=frozenset({"openrouter:priced/private"}),
        checker=checker,
    )
    assert admitted == [rows[1]]


def test_discovery_counts_survive_stage_specific_policy_reports() -> None:
    """Fallback selection preserves full discovery cost-tier evidence."""
    namespace = _load_launcher()
    base = {"selected_count": 1, "selected": [{"model": "priced/model"}]}
    rows = [
        {"cost_evidence": "free", "provider": "nvidia_nim"},
        {"cost_evidence": "priced", "provider": "openai"},
        {"cost_evidence": "priced", "provider": "openai"},
        {"cost_evidence": "unknown", "provider": "bytez"},
    ]
    enriched = namespace["_with_discovery_counts"](
        base, rows, provider_account=policy.provider_account
    )
    assert base == {"selected_count": 1, "selected": [{"model": "priced/model"}]}
    assert [enriched[key] for key in (
        "total_routes", "total_free_routes", "total_priced_routes", "total_unknown_routes"
    )] == [4, 1, 2, 1]
    assert enriched["free_account_diversity"] == 1


def test_discovery_counts_recompute_diversity_from_full_discovery_not_the_stage() -> None:
    """A stage report's own narrower free-route set must not be trusted.

    Regression for a real bug: the ``auto``-pool primary stage only sees
    ZDR-admitted free rows, and the priced-fallback stage sees no free rows
    at all, so either stage's internally computed ``free_account_diversity``
    (whatever ``build_zdr_prioritized_catalog`` returned from its own
    narrower input) would undercount or read zero even when the full
    discovery has multiple credential accounts with free routes.
    """
    namespace = _load_launcher()
    stage_report_from_priced_only_rows = {"free_account_diversity": 0}
    full_discovery_rows = [
        {"cost_evidence": "free", "provider": "nvidia_nim"},
        {"cost_evidence": "free", "provider": "openrouter"},
        {"cost_evidence": "priced", "provider": "openai"},
    ]
    enriched = namespace["_with_discovery_counts"](
        stage_report_from_priced_only_rows,
        full_discovery_rows,
        provider_account=policy.provider_account,
    )
    assert enriched["free_account_diversity"] == 2


def test_temporary_fallback_catalog_is_removed_after_loading(tmp_path: Path) -> None:
    """The price-only handoff file is removed after success and failure."""
    helper = _load_launcher()["_load_temporary_agents"]
    path = tmp_path / "review-catalog.json.priced"
    agents = [{"id": "priced_route"}]

    def loader(value: str) -> list[object]:
        assert json.loads(Path(value).read_text(encoding="utf-8")) == {"agents": agents}
        return [SimpleNamespace(id="priced_route")]

    assert [agent.id for agent in helper(str(path), agents, loader=loader)] == [
        "priced_route"
    ]
    assert not path.exists()

    def failing_loader(value: str) -> list[object]:
        assert Path(value).exists()
        raise RuntimeError("loader rejected catalog")

    with pytest.raises(RuntimeError, match="loader rejected catalog"):
        helper(str(path), agents, loader=failing_loader)
    assert not path.exists()


def test_preflight_transport_is_bounded_and_provider_neutral() -> None:
    """Startup probes stay short while serving gets the Noema review budget."""
    namespace = _load_launcher()

    class CaptureClient:
        instances: list[dict[str, object]] = []

        def __init__(self, **kwargs: object) -> None:
            self.__class__.instances.append(kwargs)

    build_client = namespace["_build_model_client"]
    build_client(
        CaptureClient, timeout=namespace["REVIEW_PREFLIGHT_TIMEOUT_SECONDS"]
    )
    build_client(CaptureClient, timeout=namespace["REVIEW_SERVING_TIMEOUT_SECONDS"])

    preflight, serving = CaptureClient.instances

    assert preflight["timeout"] == 10
    assert serving["timeout"] == 9000
    assert preflight["timeout"] != serving["timeout"]
    assert preflight["max_output_tokens"] == serving["max_output_tokens"] == 4096
    assert preflight["max_retries"] == serving["max_retries"] == 0
    assert preflight["temperature"] == serving["temperature"] == 1.0


def test_sidecar_preserves_diagnostics_and_probes_the_real_gateway() -> None:
    """Artifacts retain safe evidence and readiness exercises the exact HTTP path."""
    launcher = _LAUNCHER.read_text(encoding="utf-8")
    sidecar = _SIDECAR.read_text(encoding="utf-8")

    assert "_preflight_with_fallback(" in launcher
    assert "preflight-out" in launcher
    assert "max_output_tokens=REVIEW_MAX_OUTPUT_TOKENS" in launcher
    assert "REVIEW_SERVING_TIMEOUT_SECONDS = 9000" in launcher
    assert "timeout=REVIEW_PREFLIGHT_TIMEOUT_SECONDS" in launcher
    assert "timeout=REVIEW_SERVING_TIMEOUT_SECONDS" in launcher
    assert launcher.count("max_retries=0") == 1
    assert "temperature=REVIEW_TEMPERATURE" in launcher

    assert (
        'STRIX_EVIDENCE_DIR="${GITHUB_WORKSPACE:-$ORCHESTRATOR_WORK}/strix_runs"'
        in sidecar
    )
    assert (
        'sidecar_stdout="$STRIX_EVIDENCE_DIR/contextual-orchestrator-sidecar.stdout.log"'
        in sidecar
    )
    assert (
        'sidecar_stderr="$STRIX_EVIDENCE_DIR/contextual-orchestrator-sidecar.stderr.log"'
        in sidecar
    )
    assert (
        'preflight_report="$STRIX_EVIDENCE_DIR/contextual-orchestrator-preflight.json"'
        in sidecar
    )
    assert '--preflight-out "$preflight_report"' in sidecar
    # ADR-0005's bounded gateway retry loop (see the dedicated
    # test_gateway_preflight_retries_transport_failures_up_to_a_bounded_attempt_count
    # and test_gateway_retry_loop_* tests below for its full behavioral
    # contract) replaces the single-shot transport_timeout/transport_error
    # classification this test previously asserted here.
    assert 'REVIEW_PREFLIGHT_GATEWAY_MAX_ATTEMPTS="${REVIEW_PREFLIGHT_GATEWAY_MAX_ATTEMPTS:-3}"' in sidecar
    assert "gateway preflight request could not reach the local sidecar after" in sidecar
    assert (
        'gateway_preflight_response="$ORCHESTRATOR_WORK/gateway-preflight.json"'
        in sidecar
    )
    assert (
        '"http://${ORCHESTRATOR_HOST}:${ORCHESTRATOR_PORT}/v1/chat/completions"'
        in sidecar
    )
    assert "Authorization: Bearer ${ORCHESTRATOR_TOKEN}" in sidecar
    assert 'orchestrator_pool="${CONTEXTUAL_ORCHESTRATOR_POOL:-free}"' in sidecar
    assert 'gateway_virtual_model="orchestrator/${orchestrator_pool}"' in sidecar
    assert '"model":"%s"' in sidecar
    assert '"orchestration":"route"' in sidecar
    assert '"$gateway_virtual_model" > "$gateway_preflight_request"' in sidecar
    assert '"model":"orchestrator/free"' not in sidecar
    assert "gateway preflight returned unusable chat content" in sidecar
    assert (
        'SIDECAR_LOG_SANITIZER="$ORG_REPO_ROOT/scripts/ci/sanitize_contextual_orchestrator_sidecar_stream.py"'
        in sidecar
    )
    assert "contextlib.redirect_stderr(expected_rejection_log)" in sidecar
    assert (
        '"$sidecar_python" -u "$SIDECAR_LOG_SANITIZER" > "$sidecar_stdout"' in sidecar
    )
    assert (
        '"$sidecar_python" -u "$SIDECAR_LOG_SANITIZER" > "$sidecar_stderr"' in sidecar
    )
    assert '> "$sidecar_stdout" 2> "$sidecar_stderr" &' not in sidecar


def test_gateway_preflight_rejection_prints_bounded_evidence_to_the_job_log() -> None:
    """A rejected gateway preflight must surface error_code/http_status directly.

    Before this, the bounded ``error_code``/``http_status`` pair was written
    only into the ``CONTEXTUAL_ORCHESTRATOR_PREFLIGHT_EVIDENCE`` artifact
    file, invisible in the job log a CI operator reads first -- exactly the
    gap that made a real "every free route rejected" failure look identical
    to an opaque "gateway preflight returned HTTP 502" in normal CI output.
    """
    sidecar = _SIDECAR.read_text(encoding="utf-8")

    assert (
        'print(f"[contextual-orchestrator-sidecar] gateway preflight rejected: '
        'error_code={code} http_status={status}")'
    ) in sidecar
    # This print is not routed through the sanitizer, so its inputs must stay
    # bounded: code is regex-validated and status is a plain int, never raw
    # provider response text.
    assert (
        'if not isinstance(code, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", code):'
        in sidecar
    )


def test_sidecar_stream_sanitizer_allowlists_only_bounded_diagnostics() -> None:
    """Provider bodies, exception messages, URLs, and secrets never reach artifacts."""
    namespace = _load_sanitizer()
    sanitize_line = namespace["sanitize_line"]

    assert (
        sanitize_line(
            "request_failed status=500 code=internal_error upstream sk-secret"
        )
        == "request_failed status=500 code=internal_error"
    )
    assert sanitize_line("client_disconnected") == "client_disconnected"
    assert sanitize_line("discovery_diagnostics_complete") == "discovery_diagnostics_complete"
    assert sanitize_line(
        "review sidecar preflight failed: upstream sk-secret"
    ) == "review sidecar preflight failed"
    assert sanitize_line(
        "review sidecar discovery failed: https://provider.invalid/?key=sk-secret"
    ) == "review sidecar discovery failed"
    assert sanitize_line(
        "review sidecar discovered no eligible models; orchestrator/free would fail closed"
    ) == "review sidecar discovered no eligible models"
    assert sanitize_line(
        "review sidecar requires an explicit --auth-token or the KV credential "
        "'CONTEXTUAL_ORCHESTRATOR_TOKEN'"
    ) == "review sidecar auth token unavailable"
    assert sanitize_line(
        "review sidecar requires at least one provider credential in the KV"
    ) == "review sidecar requires at least one provider credential in the KV"
    assert sanitize_line(
        "provider_discovery_failed provider=bytez code=http_status_401"
    ) == "provider_discovery_failed provider=bytez code=http_status_401"
    assert sanitize_line(
        "preflight_route_rejected provider=nvidia_nim error_type=ProviderUpstreamError "
        "http_status=429 upstream body sk-secret"
    ) == "preflight_route_rejected provider=nvidia_nim error_type=ProviderUpstreamError http_status=429"
    assert sanitize_line(
        "preflight_route_rejected provider=bytez error_type=InvalidChatResponse"
    ) == "preflight_route_rejected provider=bytez error_type=InvalidChatResponse"
    assert sanitize_line("provider response sk-secret") is None


def test_sidecar_stream_sanitizer_summarizes_unstructured_and_traceback_lines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The streaming entrypoint flushes safe summaries without echoing raw input."""
    namespace = _load_sanitizer()
    main = namespace["main"]
    secret = "sk-secret-must-not-enter-artifact"
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(
            "request_failed status=500 code=internal_error provider body "
            f"{secret}\n"
            "Traceback (most recent call last):\n"
            f"  File provider.py, token={secret}\n"
            "Traceback (nested):\n"
            f"review sidecar preflight failed: {secret}\n"
            "client_disconnected\n"
        ),
    )
    output = io.StringIO()

    with redirect_stdout(output):
        assert main() == 0

    rendered = output.getvalue()
    assert rendered.splitlines() == [
        "request_failed status=500 code=internal_error",
        "sidecar emitted an unexpected exception",
        "review sidecar preflight failed",
        "client_disconnected",
        "omitted_unstructured_lines=1",
    ]
    assert secret not in rendered


def test_sidecar_stream_sanitizer_omits_no_summary_for_fully_safe_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fully allowlisted stream does not manufacture an omission warning."""
    namespace = _load_sanitizer()
    main = namespace["main"]
    monkeypatch.setattr(sys, "stdin", io.StringIO("client_disconnected\n"))
    output = io.StringIO()

    with redirect_stdout(output):
        assert main() == 0

    assert output.getvalue() == "client_disconnected\n"
