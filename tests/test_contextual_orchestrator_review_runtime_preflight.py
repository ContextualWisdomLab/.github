"""Regression tests for the Strix contextual-orchestrator runtime boundary."""

from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
import re
import runpy
from pathlib import Path
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


def test_reasoning_without_content_remains_rejected_even_with_the_full_budget() -> None:
    """A genuinely broken model must still fail closed at the full 4096-token
    budget -- proving the sidecar-preflight-max-tokens fix widens the budget
    without weakening the routing probe's fail-closed content check.

    Negative control for the same incident: raising the budget must never be
    mistaken for making every response acceptable. A route whose reply is
    reasoning-only (present ``reasoning``, empty ``content``) -- the exact
    shape ``contextual_orchestrator.orchestrator._response_content`` raises
    ``ProviderResponseError`` for -- is simulated at the routing-probe layer
    and must still be classified "rejected", never reclassified as a
    healthy "ready" route just because the token budget grew.
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

    with pytest.raises(namespace["ReviewPreflightError"], match="no provider route passed"):
        preflight([reasoning_only], client=client)

    assert client.calls[0][2]["max_tokens"] == namespace["REVIEW_MAX_OUTPUT_TOKENS"]


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
