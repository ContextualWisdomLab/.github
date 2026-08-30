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


def test_gateway_preflight_max_tokens_is_synchronized_with_the_routing_probe() -> None:
    """The bash script's end-to-end gateway check must not retest a route the
    Python routing probe already proved ready with a stricter token budget.

    Regression for the 2026-08-30 sidecar-preflight-max-tokens incident: the
    routing probe (`_preflight_review_agents`, tested above) already uses
    `REVIEW_MAX_OUTPUT_TOKENS` and correctly marked a reasoning-capable
    nvidia_nim route "ready". The separate end-to-end gateway check in
    ``contextual_orchestrator_review_sidecar.sh`` used to hardcode
    ``"max_tokens":16`` for that same virtual-model request -- far too small
    for a reasoning model to emit any answer content after its internal
    reasoning tokens, so the gateway rejected a route its own routing probe
    had just proven healthy. This asserts the two budgets stay numerically
    identical so that mismatch cannot silently return; it fails on the
    pre-fix literal (16) and passes once the gateway request is synchronized
    with the routing probe's budget.
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


def test_gateway_preflight_curl_timeout_tolerates_real_reasoning_latency() -> None:
    """The end-to-end gateway check's curl timeout must not undercut real completion latency.

    Regression for the 2026-08-30 gateway-preflight-timeout incident: exact-
    evidence reproduction (Strix run 33306775025 on
    ContextualWisdomLab/contextual-orchestrator#921, job 99244624298) showed
    the routing probe marking a DeepSeek NIM route "ready" in 18s, then the
    identical gateway request against that same healthy route being cut off
    at exactly curl's configured bound -- "gateway preflight request could
    not reach the local sidecar" was that timeout, not a real connectivity
    failure. This asserts the bound is generous enough to tolerate a real
    reasoning generation (well above the routing probe's own 10s
    per-candidate budget) rather than the previous 30s, which rejected a
    route the routing probe had just proven healthy.
    """
    sidecar = _SIDECAR.read_text(encoding="utf-8")

    match = re.search(r"curl -sS --max-time (\d+) \\\n\s*-o \"\$gateway_preflight_response\"", sidecar)
    assert match, "sidecar must send the gateway preflight request with an explicit curl --max-time"
    gateway_preflight_timeout_seconds = int(match.group(1))

    assert gateway_preflight_timeout_seconds >= 120, (
        "gateway preflight curl --max-time "
        f"({gateway_preflight_timeout_seconds}s) must tolerate real reasoning-model "
        "completion latency; 30s was observed cutting off a route the routing probe "
        "had just proven ready"
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
# success -- without a real gateway process. A plan file's first line is
# either "FAIL" (curl exits non-zero, exactly like a real timeout with zero
# bytes) or an HTTP status code (written verbatim to stdout, mirroring
# `-w '%{http_code}'`); any remaining lines become the `-o` response body,
# exactly like a real curl would write one.
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
    timeout_seconds = namespace["REVIEW_PREFLIGHT_TIMEOUT_SECONDS"]
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
    worst_case_seconds = total_attempts * timeout_seconds
    assert worst_case_seconds <= 160, (
        f"worst-case preflight time ({worst_case_seconds}s across "
        f"{total_attempts} attempts) must stay within the 160s the ADR "
        "computes and the 180s healthz-readiness watchdog allows"
    )
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
        {"cost_evidence": "free"},
        {"cost_evidence": "priced"},
        {"cost_evidence": "priced"},
        {"cost_evidence": "unknown"},
    ]
    enriched = namespace["_with_discovery_counts"](base, rows)
    assert base == {"selected_count": 1, "selected": [{"model": "priced/model"}]}
    assert [enriched[key] for key in (
        "total_routes", "total_free_routes", "total_priced_routes", "total_unknown_routes"
    )] == [4, 1, 2, 1]


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


def test_preflight_transport_is_bounded_and_provider_neutral() -> None:
    """Sequential route probes must fit inside the sidecar startup budget."""
    launcher = _LAUNCHER.read_text(encoding="utf-8")

    assert "REVIEW_MAX_OUTPUT_TOKENS = 4096" in launcher
    assert "REVIEW_TEMPERATURE = 1.0" in launcher
    assert "REVIEW_PREFLIGHT_TIMEOUT_SECONDS = 10" in launcher
    assert "timeout=REVIEW_PREFLIGHT_TIMEOUT_SECONDS" in launcher
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
