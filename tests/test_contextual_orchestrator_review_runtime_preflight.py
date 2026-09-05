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
from types import SimpleNamespace

import pytest

from scripts.ci import contextual_orchestrator_review_policy as policy

_REPO_ROOT = Path(__file__).resolve().parents[1]
_LAUNCHER = _REPO_ROOT / "scripts/ci/contextual_orchestrator_review_launcher.py"
_SIDECAR = _REPO_ROOT / "scripts/ci/contextual_orchestrator_review_sidecar.sh"
_SANITIZER = _REPO_ROOT / "scripts/ci/sanitize_contextual_orchestrator_sidecar_stream.py"


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
    # finding: the ordinary, most-common outcome (an immediate base-probe
    # success, no escalation needed) must still populate finish_reason and
    # reasoning_without_content -- not just failure/escalation outcomes --
    # so there is a real "normal" baseline to compare future telemetry
    # against.
    ready_row = report["routes"][2]
    assert ready_row["status"] == "ready"
    assert ready_row["finish_reason"] == "unknown"
    assert ready_row["reasoning_without_content"] is False

    for agent, endpoint, payload in client.calls:
        assert endpoint == "chat/completions"
        assert payload["model"] == agent.model
        assert payload["stream"] is False
        assert payload["max_tokens"] == 16
        assert payload["temperature"] == 1.0
        assert payload["messages"] == [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Reply with just 'OK'."},
        ]
        assert "tools" not in payload


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

    Since ADR-0005 (this PR), most routes now prove readiness at the much
    cheaper ``REVIEW_PREFLIGHT_BASE_TOKENS`` (16) instead -- `4096` is used
    by the routing probe only on the ESCALATED retry (a candidate that
    failed the cheap probe with a budget-too-small signature) and, always,
    by the real serving `ModelClient` for actual review traffic (see
    `ContextualWisdomLab/.github#1454` for the resulting known gap: an
    ordinary base-probe success is never itself confirmed at this budget).
    This test's own assertion is unaffected by that: Layer 2 never
    escalates (ADR-0005 Decision SS1) and always uses the real serving
    budget, so its literal must still equal `REVIEW_MAX_OUTPUT_TOKENS`
    exactly, for the same reason as before -- a smaller Layer 2 budget can
    still reject a route the routing probe (at either of its own budgets)
    already proved ready.
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


def test_gateway_preflight_has_no_inference_timeout() -> None:
    """The end-to-end gateway check must not cap real completion latency.

    Regression for the 2026-08-30 gateway-preflight-timeout incident: exact-
    evidence reproduction (Strix run 33306775025 on
    ContextualWisdomLab/contextual-orchestrator#921, job 99244624298) showed
    the routing probe marking a DeepSeek NIM route "ready" in 18s, then the
    identical gateway request against that same healthy route being cut off
    at exactly curl's configured bound -- "gateway preflight request could
    not reach the local sidecar" was that timeout, not a real connectivity
    failure. The request therefore has no wall-clock bound.
    """
    sidecar = _SIDECAR.read_text(encoding="utf-8")

    request_block = sidecar.rsplit("curl -sS", 1)[1].split(
        '"http://${ORCHESTRATOR_HOST}:${ORCHESTRATOR_PORT}/v1/chat/completions"', 1
    )[0]
    assert "--max-time" not in request_block


def test_sidecar_discovery_and_health_have_no_wall_clock_timeout() -> None:
    sidecar = _SIDECAR.read_text(encoding="utf-8")

    lines = sidecar.splitlines()

    def curl_command(url: str) -> tuple[str, int]:
        index = next(index for index, line in enumerate(lines) if url in line)
        start = index
        while start and lines[start - 1].rstrip().endswith("\\"):
            start -= 1
        end = index
        while lines[end].rstrip().endswith("\\"):
            end += 1
        command = " ".join(line.strip().removesuffix("\\") for line in lines[start : end + 1])
        assert re.search(r"\bcurl\b", command)
        return command, end

    timeout_option = re.compile(
        r"(?:^|\s)(?:-m(?:\s|$)|--[a-z-]*(?:time|timeout)[a-z-]*(?:=|\s|$))"
    )
    zdr_command, _ = curl_command("https://openrouter.ai/api/v1/endpoints/zdr")
    health_command, health_command_end = curl_command(
        'http://${ORCHESTRATOR_HOST}:${ORCHESTRATOR_PORT}/healthz'
    )
    for command in (zdr_command, health_command):
        assert timeout_option.search(command) is None
        assert re.search(r"(?:^|\s)timeout(?:\s|$)", command) is None

    health_loop = "\n".join(lines[health_command_end + 1 :]).split("\ndone", 1)[0]
    assert 'kill -0 "$sidecar_pid"' in health_loop
    assert health_loop.count("fail ") == 1
    assert health_loop.index('kill -0 "$sidecar_pid"') < health_loop.index("fail ")
    assert not re.search(
        r"\b(?:break|exit|timeout)\b|\s-(?:ge|gt|le|lt)\s|\bif\s+\(\(",
        health_loop,
    )


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
    the single most common outcome (an immediate base-probe success).
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
    assert row["attempts"] == 1
    assert row["finish_reason"] == "stop"
    assert row["reasoning_without_content"] is False


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
    assert isinstance(error_type, type), "launcher must expose a typed preflight failure"

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

    viable, report, fallback_used = preflight(
        [primary], [fallback], client=client
    )

    assert viable == [fallback]
    assert fallback_used is True
    assert report["fallback_reason"] == "primary_routes_unavailable"
    assert report["primary_attempt"]["ready_count"] == 0
    assert [call[0] for call in client.calls] == [primary, fallback]

    ready_client = _ProbeClient(
        {primary.id: _openai_text("OK"), fallback.id: _openai_text("unused")}
    )
    viable, report, fallback_used = preflight(
        [primary], [fallback], client=ready_client
    )
    assert viable == [primary]
    assert fallback_used is False
    assert "fallback_reason" not in report
    assert [call[0] for call in ready_client.calls] == [primary]

    failing_client = _ProbeClient(
        {primary.id: TimeoutError("unavailable"), fallback.id: RuntimeError("rejected")}
    )
    with pytest.raises(namespace["ReviewPreflightError"]) as failure:
        preflight([primary], [fallback], client=failing_client)
    assert failure.value.report["ready_count"] == 0
    assert failure.value.report["primary_attempt"]["ready_count"] == 0


def test_fallback_escalation_budget_is_shared_with_primary_and_bounds_worst_case() -> None:
    """Regression for Devin Review's fallback-retries-exceed-startup-deadline
    finding: ``_preflight_review_agents`` used to start ``escalations_used``
    fresh on every call, so ``_preflight_with_fallback`` calling it twice (up
    to 8 primary routes, then up to 4 fallback routes) could spend the full
    ``REVIEW_PREFLIGHT_MAX_ESCALATIONS`` budget in EACH stage -- up to 8
    escalations total, 200s worst case (12 base attempts + 8 escalations x
    10s), blowing past Layer 1's 180s healthz-readiness watchdog and
    contradicting the ADR's own claimed 160s worst case.

    This drives all 8 primary routes and all 4 fallback routes (the exact
    ``REVIEW_PREFLIGHT_MAX_TOTAL_ROUTES`` split) through a response that
    always qualifies for escalation and never resolves, so every one of the
    12 candidates *would* escalate if the budget were not shared. Asserts
    the run spends at most ``REVIEW_PREFLIGHT_MAX_ESCALATIONS`` escalations
    in total (not per stage), and that the resulting worst-case attempt count
    keeps total elapsed time at or under 160s -- both stages' escalation
    counts are visible in the returned evidence.
    """
    namespace = _load_launcher()
    preflight = namespace["_preflight_with_fallback"]
    max_escalations = namespace["REVIEW_PREFLIGHT_MAX_ESCALATIONS"]
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
    # Exactly the ADR's own worst-case arithmetic: 12 base attempts (one per
    # candidate across both stages) + 4 escalations (the shared cap) = 16.
    assert total_attempts == total_route_limit + max_escalations


def test_preflight_stage_limits_share_one_startup_budget() -> None:
    """Free-first and priced-fallback probes share one bounded route budget."""
    namespace = _load_launcher()
    primary = namespace["_bounded_primary_catalog_limit"](
        99, pool="auto", has_free_rows=True
    )
    fallback = namespace["_bounded_fallback_catalog_limit"](
        99, primary_count=primary
    )
    assert (primary, fallback) == (8, 4)
    assert primary + fallback == namespace["REVIEW_PREFLIGHT_MAX_TOTAL_ROUTES"]


def test_catalog_account_cap_defaults_to_the_caller_supplied_policy_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The per-account cap falls back to ``policy.DEFAULT_ACCOUNT_CAP``, not the total budget.

    Regression for a real, observed failure mode
    (ContextualWisdomLab/.github#1415, reported as "빈 깡통 경로 너무 많다"): a
    sibling helper (``_catalog_family_cap()``) fell back to
    ``REVIEW_PREFLIGHT_MAX_TOTAL_ROUTES`` -- the *total* preflight budget --
    instead of the intended per-account cap whenever its env var was unset.
    That silently disabled per-account diversification: in a live production
    run, two NVIDIA NIM credentials sharing one rate-limited upstream jointly
    consumed all 12 preflight slots, of which 10 (83%) were then rejected via
    429/404/timeout. This module's own equivalent helper must never resolve
    to the same value as the total-routes budget when given the real
    ``policy.DEFAULT_ACCOUNT_CAP``, which is strictly smaller.
    """
    namespace = _load_launcher()
    monkeypatch.delenv("ORCHESTRATOR_CATALOG_ACCOUNT_CAP", raising=False)
    cap = namespace["_catalog_account_cap"](policy.DEFAULT_ACCOUNT_CAP)
    assert cap == policy.DEFAULT_ACCOUNT_CAP
    assert cap != namespace["REVIEW_PREFLIGHT_MAX_TOTAL_ROUTES"]
    assert cap < namespace["REVIEW_PREFLIGHT_MAX_TOTAL_ROUTES"]


def test_catalog_account_cap_honors_an_explicit_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An operator-set ``ORCHESTRATOR_CATALOG_ACCOUNT_CAP`` still takes effect."""
    namespace = _load_launcher()
    monkeypatch.setenv("ORCHESTRATOR_CATALOG_ACCOUNT_CAP", "6")
    assert namespace["_catalog_account_cap"](policy.DEFAULT_ACCOUNT_CAP) == 6


def test_main_sources_the_account_cap_default_from_policy_not_a_magic_number() -> None:
    """``main()`` must wire the cap default from ``policy.DEFAULT_ACCOUNT_CAP``.

    A hand-typed literal (or, worse, a total-routes-scale constant) can
    silently drift out of sync with ``policy.DEFAULT_ACCOUNT_CAP`` with no
    test catching it -- the exact drift that produced
    ContextualWisdomLab/.github#1415's real preflight-budget waste. This
    source-level contract test pins both ``build_zdr_prioritized_catalog``
    call sites in ``main()`` to the single source of truth and forbids the
    total-routes constant from ever reappearing as the account-cap fallback.
    """
    source = _LAUNCHER.read_text(encoding="utf-8")
    assert source.count("account_cap=_catalog_account_cap(DEFAULT_ACCOUNT_CAP)") == 2
    assert "ORCHESTRATOR_CATALOG_FAMILY_CAP" not in source
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

    assert [agent.id for agent in helper(str(path), agents, loader=loader)] == ["priced_route"]
    assert not path.exists()

    def failing_loader(value: str) -> list[object]:
        assert Path(value).exists()
        raise RuntimeError("loader rejected catalog")

    with pytest.raises(RuntimeError, match="loader rejected catalog"):
        helper(str(path), agents, loader=failing_loader)
    assert not path.exists()


def test_preflight_transport_has_no_inference_timeout_and_is_provider_neutral() -> None:
    launcher = _LAUNCHER.read_text(encoding="utf-8")

    assert "REVIEW_MAX_OUTPUT_TOKENS = 4096" in launcher
    assert "REVIEW_TEMPERATURE = 1.0" in launcher
    assert "REVIEW_PREFLIGHT_TIMEOUT_SECONDS" not in launcher
    assert "ModelClient(\n        timeout=" not in launcher
    assert "max_retries=0" in launcher
    assert "temperature=REVIEW_TEMPERATURE" in launcher


def test_sidecar_preserves_diagnostics_and_probes_the_real_gateway() -> None:
    """Artifacts retain safe evidence and readiness exercises the exact HTTP path."""
    launcher = _LAUNCHER.read_text(encoding="utf-8")
    sidecar = _SIDECAR.read_text(encoding="utf-8")

    assert "_preflight_with_fallback(" in launcher
    assert "preflight-out" in launcher
    assert "max_output_tokens=REVIEW_MAX_OUTPUT_TOKENS" in launcher
    assert "temperature=REVIEW_TEMPERATURE" in launcher

    assert 'STRIX_EVIDENCE_DIR="${GITHUB_WORKSPACE:-$ORCHESTRATOR_WORK}/strix_runs"' in sidecar
    assert 'sidecar_stdout="$STRIX_EVIDENCE_DIR/contextual-orchestrator-sidecar.stdout.log"' in sidecar
    assert 'sidecar_stderr="$STRIX_EVIDENCE_DIR/contextual-orchestrator-sidecar.stderr.log"' in sidecar
    assert 'preflight_report="$STRIX_EVIDENCE_DIR/contextual-orchestrator-preflight.json"' in sidecar
    assert '--preflight-out "$preflight_report"' in sidecar
    assert 'gateway_preflight_response="$ORCHESTRATOR_WORK/gateway-preflight.json"' in sidecar
    assert '"http://${ORCHESTRATOR_HOST}:${ORCHESTRATOR_PORT}/v1/chat/completions"' in sidecar
    assert 'Authorization: Bearer ${ORCHESTRATOR_TOKEN}' in sidecar
    assert 'orchestrator_pool="${CONTEXTUAL_ORCHESTRATOR_POOL:-free}"' in sidecar
    assert 'gateway_virtual_model="orchestrator/${orchestrator_pool}"' in sidecar
    assert '"model":"%s"' in sidecar
    assert '"$gateway_virtual_model" > "$gateway_preflight_request"' in sidecar
    assert '"model":"orchestrator/free"' not in sidecar
    assert "gateway preflight returned unusable chat content" in sidecar
    assert 'SIDECAR_LOG_SANITIZER="$ORG_REPO_ROOT/scripts/ci/sanitize_contextual_orchestrator_sidecar_stream.py"' in sidecar
    assert '"$sidecar_python" -u "$SIDECAR_LOG_SANITIZER" > "$sidecar_stdout"' in sidecar
    assert '"$sidecar_python" -u "$SIDECAR_LOG_SANITIZER" > "$sidecar_stderr"' in sidecar
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

    assert sanitize_line(
        "request_failed status=500 code=internal_error upstream sk-secret"
    ) == "request_failed status=500 code=internal_error"
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


def test_sidecar_log_level_defaults_to_debug(monkeypatch: pytest.MonkeyPatch) -> None:
    """The sidecar asks for DEBUG so provider attempts and circuit events are recorded."""
    monkeypatch.delenv("ORCHESTRATOR_SIDECAR_LOG_LEVEL", raising=False)
    namespace = _load_launcher()
    assert namespace["_sidecar_log_level"]() == "DEBUG"
    assert namespace["DEFAULT_SIDECAR_LOG_LEVEL"] == "DEBUG"


def test_sidecar_log_level_honors_an_explicit_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """An operator-set ``ORCHESTRATOR_SIDECAR_LOG_LEVEL`` is passed through untouched."""
    monkeypatch.setenv("ORCHESTRATOR_SIDECAR_LOG_LEVEL", "INFO")
    namespace = _load_launcher()
    assert namespace["_sidecar_log_level"]() == "INFO"


def test_configure_sidecar_logging_applies_level_and_timestamped_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The injected configurator receives the level and every root handler gets timestamps."""
    import logging

    monkeypatch.delenv("ORCHESTRATOR_SIDECAR_LOG_LEVEL", raising=False)
    namespace = _load_launcher()
    received: list[str] = []

    def fake_configure_logging(level_name: str) -> None:
        received.append(level_name)
        logging.basicConfig(level=getattr(logging, level_name), force=True)

    try:
        applied = namespace["_configure_sidecar_logging"](fake_configure_logging)
        assert applied == "DEBUG"
        assert received == ["DEBUG"]
        handlers = logging.getLogger().handlers
        assert handlers, "basicConfig(force=True) must have installed a root handler"
        for handler in handlers:
            assert handler.formatter is not None
            assert "%(asctime)s" in handler.formatter._fmt  # noqa: SLF001 - formatter has no public getter
    finally:
        logging.basicConfig(level=logging.WARNING, force=True)


def test_configure_sidecar_logging_rejects_an_invalid_level(monkeypatch: pytest.MonkeyPatch) -> None:
    """A misspelt level fails the launch instead of silently staying at WARNING."""
    monkeypatch.setenv("ORCHESTRATOR_SIDECAR_LOG_LEVEL", "LOUD")
    namespace = _load_launcher()

    def strict_configure_logging(level_name: str) -> None:
        raise ValueError(f"unknown log level {level_name!r}")

    with pytest.raises(SystemExit, match="ORCHESTRATOR_SIDECAR_LOG_LEVEL is invalid: unknown log level 'LOUD'"):
        namespace["_configure_sidecar_logging"](strict_configure_logging)


def test_main_configures_sidecar_logging_before_touching_credentials() -> None:
    """``main()`` wires the orchestrator's own ``configure_logging`` in before any credential work."""
    source = _LAUNCHER.read_text(encoding="utf-8")
    configure_at = source.index("_configure_sidecar_logging(configure_logging)")
    credentials_at = source.index("registered = register_review_credentials(os.environ)")
    assert configure_at < credentials_at
    assert "from contextual_orchestrator.debug_logging import configure_logging" in source
