"""Regression tests for the Strix contextual-orchestrator runtime boundary."""

from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
import runpy
import socket
from pathlib import Path
import sys
from types import SimpleNamespace
import urllib.error

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_LAUNCHER = _REPO_ROOT / "scripts/ci/contextual_orchestrator_review_launcher.py"
_SIDECAR = _REPO_ROOT / "scripts/ci/contextual_orchestrator_review_sidecar.sh"
_SANITIZER = _REPO_ROOT / "scripts/ci/sanitize_contextual_orchestrator_sidecar_stream.py"


class _ProbeClient:
    """Return deterministic per-agent outcomes for runtime preflight tests.

    An outcome may be a single value (returned or raised on every call for
    that agent, the original behavior) or a ``list`` of values consumed one
    per call in order -- the last entry repeats once the list is exhausted --
    so a test can exercise the preflight retry path by giving one agent a
    transient failure followed by success.
    """

    def __init__(self, outcomes: dict[str, object]) -> None:
        self.outcomes = outcomes
        self.calls: list[tuple[object, str, dict[str, object]]] = []
        self._call_counts: dict[str, int] = {}

    def proxy_send_once(
        self, agent: object, endpoint: str, payload: dict[str, object]
    ) -> dict[str, object]:
        """Capture one request and return or raise the configured outcome."""
        self.calls.append((agent, endpoint, payload))
        agent_id = str(getattr(agent, "id"))
        outcome = self.outcomes[agent_id]
        if isinstance(outcome, list):
            call_index = self._call_counts.get(agent_id, 0)
            self._call_counts[agent_id] = call_index + 1
            outcome = outcome[min(call_index, len(outcome) - 1)]
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
    assert report["routes"][1]["error_type"] == "InvalidChatResponse"
    assert secret not in repr(report)

    for agent, endpoint, payload in client.calls:
        assert endpoint == "chat/completions"
        assert payload["model"] == agent.model
        assert payload["stream"] is False
        assert payload["max_tokens"] == 4096
        assert payload["temperature"] == 1.0
        assert payload["messages"] == [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Reply with just 'OK'."},
        ]
        assert "tools" not in payload


def test_preflight_retries_once_after_a_transient_failure() -> None:
    """A single flaky attempt must not permanently disqualify a healthy route.

    Regression coverage for the second, .github-local half of the 2026-08-30
    request-time-failover investigation: contextual-orchestrator's own
    routing fix (classify_provider_transport_failure) cannot help here, since
    this loop calls proxy_send_once directly and never reaches
    TaskOrchestrator's routing at all. Before this retry existed, one
    transient blip (a 503, a timeout) during preflight rejected the route
    outright; if every discovered candidate hit the same blip in one run, the
    whole sidecar would exit before healthz regardless of how good the
    gateway's own failover is.
    """
    namespace = _load_launcher()
    preflight = namespace.get("_preflight_review_agents")
    assert callable(preflight)

    flaky = SimpleNamespace(id="flaky_then_ready", provider_name="openai", model="flaky/free")
    client = _ProbeClient(
        {
            flaky.id: [
                urllib.error.HTTPError("https://example.invalid", 503, "Service Unavailable", {}, None),
                _openai_text("OK"),
            ],
        }
    )

    viable, report = preflight([flaky], client=client)

    assert viable == [flaky]
    assert report["routes"] == [{"agent_id": "flaky_then_ready", "provider": "openai", "model": "flaky/free", "status": "ready"}]
    # Exactly one retry: two calls total, not an unbounded loop.
    assert len(client.calls) == 2


def test_preflight_does_not_retry_a_non_retryable_failure() -> None:
    """An auth/not-found style failure is rejected on its first attempt, unchanged."""
    namespace = _load_launcher()
    preflight = namespace.get("_preflight_review_agents")
    error_type = namespace.get("ReviewPreflightError")
    assert callable(preflight)

    not_found = SimpleNamespace(id="nim_retired_model", provider_name="nvidia_nim", model="retired/free")
    client = _ProbeClient(
        {
            not_found.id: [
                urllib.error.HTTPError("https://example.invalid", 404, "Not Found", {}, None),
                _openai_text("OK"),
            ],
        }
    )

    with pytest.raises(error_type) as excinfo:
        preflight([not_found], client=client)

    report = excinfo.value.report
    assert report["routes"][0]["status"] == "rejected"
    assert report["routes"][0]["http_status"] == 404
    # No retry spent on a non-transient failure, even though the queued
    # second outcome would have succeeded -- proves the retry is gated on
    # retryability, not just "there was a second attempt available."
    assert len(client.calls) == 1


def test_preflight_bounds_retries_when_every_attempt_is_transient() -> None:
    """A persistently flaky route is still rejected after its one bounded retry."""
    namespace = _load_launcher()
    preflight = namespace.get("_preflight_review_agents")
    error_type = namespace.get("ReviewPreflightError")
    assert callable(preflight)

    always_flaky = SimpleNamespace(
        id="always_flaky", provider_name="openrouter", model="flaky/free"
    )
    client = _ProbeClient({always_flaky.id: socket.timeout("timed out")})

    with pytest.raises(error_type) as excinfo:
        preflight([always_flaky], client=client)

    report = excinfo.value.report
    assert report["routes"][0]["status"] == "rejected"
    # socket.timeout is an alias for TimeoutError as of Python 3.10.
    assert report["routes"][0]["error_type"] == "TimeoutError"
    # REVIEW_PREFLIGHT_ATTEMPTS_PER_ROUTE == 2: one initial attempt plus
    # exactly one retry, never an unbounded loop.
    assert len(client.calls) == 2


def test_is_retryable_preflight_error_classifies_by_type_and_status_only() -> None:
    """The retry gate never inspects a message body, only type/status."""
    namespace = _load_launcher()
    is_retryable = namespace.get("_is_retryable_preflight_error")
    assert callable(is_retryable)

    for status in (408, 429, 500, 502, 503, 504):
        assert is_retryable(
            urllib.error.HTTPError("https://example.invalid", status, "x", {}, None)
        )
    for status in (400, 401, 403, 404, 422):
        assert not is_retryable(
            urllib.error.HTTPError("https://example.invalid", status, "x", {}, None)
        )
    assert is_retryable(urllib.error.URLError("connection refused"))
    assert is_retryable(TimeoutError("timed out"))
    assert is_retryable(ConnectionError("reset"))
    assert is_retryable(socket.timeout("timed out"))
    assert not is_retryable(RuntimeError("some other failure"))
    assert not is_retryable(ValueError("bad payload"))


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
    # An error_type value is only ever a Python identifier in real callers
    # (see _preflight_review_agents' own isidentifier() guard), so an
    # unexpected non-identifier string like this one prints as-is here --
    # the bound that actually protects evidence is upstream of this helper.
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
    # TimeoutError is retryable, so the primary route gets its one bounded
    # retry (both attempts still fail) before fallback is tried.
    assert [call[0] for call in client.calls] == [primary, primary, fallback]

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
