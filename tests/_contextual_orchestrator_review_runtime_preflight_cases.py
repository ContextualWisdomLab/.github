"""Current regressions for the contextual-orchestrator review runtime boundary.

Historical incidents remain documented in ADRs and doctoring records. This
module contains only executable expectations that still match the current
one-shot, provider-default preflight contract; retired token escalation,
priced-fallback, and shell-level inference/retry policies do not remain as
hidden test oracles.
"""

from __future__ import annotations

from contextlib import redirect_stdout
import io
from pathlib import Path
import re
import runpy
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


def test_routable_discovered_models_excludes_evidence_only_rows() -> None:
    """Evidence-only discovery rows must never enter live route selection."""
    namespace = _load_launcher()
    routable = namespace.get("_routable_discovered_models")
    assert callable(routable)

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
    """Discarded discovery failures remain visible without raw provider data."""
    namespace = _load_launcher()
    log_discovery_errors = namespace.get("_log_discovery_errors")
    assert callable(log_discovery_errors)

    log_discovery_errors(
        [
            SimpleNamespace(provider_name="bytez", error_code="http_status_401"),
            SimpleNamespace(provider_name="openai", error_code="timeout"),
        ]
    )

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
    """A clean discovery emits only the completion sentinel."""
    namespace = _load_launcher()
    log_discovery_errors = namespace.get("_log_discovery_errors")
    assert callable(log_discovery_errors)

    log_discovery_errors([])

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "discovery_diagnostics_complete\n"


def test_log_discovery_errors_sentinel_matches_the_sidecar_scripts_constant() -> None:
    """The sidecar poll target and launcher sentinel must remain identical."""
    namespace = _load_launcher()
    sentinel = namespace.get("_DISCOVERY_DIAGNOSTICS_COMPLETE_SENTINEL")
    assert sentinel == "discovery_diagnostics_complete"
    sidecar_text = _SIDECAR.read_text(encoding="utf-8")
    assert f'SIDECAR_DISCOVERY_DIAGNOSTICS_SENTINEL="{sentinel}"' in sidecar_text


def test_reasoning_without_content_requires_content_to_actually_be_absent() -> None:
    """Reasoning metadata alone never makes a usable response look starved."""
    namespace = _load_launcher()
    has_reasoning_without_content = namespace["_response_has_reasoning_without_content"]

    assert not has_reasoning_without_content(
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
    assert has_reasoning_without_content(
        {"choices": [{"message": {"reasoning": "still thinking", "content": ""}}]}
    )
    assert has_reasoning_without_content(
        {"choices": [{"message": {"reasoning": "still thinking"}}]}
    )
    assert not has_reasoning_without_content(
        {"choices": [{"message": {"content": "a normal reply"}}]}
    )


def test_log_preflight_rejections_prints_bounded_summary_to_stderr(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Rejected route evidence reaches the job log without leaking messages."""
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
        ]
    }

    log_preflight_rejections(report)

    captured = capsys.readouterr()
    assert captured.out == ""
    assert secret not in captured.err
    assert (
        "preflight_route_rejected provider=nvidia_nim "
        "error_type=ProviderUpstreamError http_status=429"
    ) in captured.err
    assert "preflight_route_rejected provider=openrouter error_type=UnknownError" in captured.err
    assert "RuntimeError" not in captured.err
    assert "ready_one" not in captured.err


def test_log_preflight_rejections_ignores_malformed_report(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Malformed diagnostic data must not raise or manufacture output."""
    namespace = _load_launcher()
    log_preflight_rejections = namespace.get("_log_preflight_rejections")
    assert callable(log_preflight_rejections)

    log_preflight_rejections({})
    log_preflight_rejections({"routes": "not-a-list"})
    log_preflight_rejections({"routes": ["not-a-dict"]})

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_sidecar_discovery_and_health_have_no_wall_clock_timeout() -> None:
    """Non-inference startup waits remain process-liveness based, not guessed deadlines."""
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
        command = " ".join(
            line.strip().removesuffix("\\") for line in lines[start : end + 1]
        )
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


def test_base_probe_success_with_reasoning_and_content_is_never_flagged_as_starved() -> None:
    """A complete one-shot response may carry reasoning metadata and remain ready."""
    namespace = _load_launcher()
    preflight = namespace["_preflight_review_agents"]
    agent = SimpleNamespace(
        id="openai_transparent_reasoner",
        provider_name="openai",
        model="reasoner/free",
    )
    client = _ProbeClient(
        {
            agent.id: {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "reasoning": "the user asked for a greeting",
                            "content": "Hello!",
                        },
                    }
                ]
            }
        }
    )

    viable, report = preflight([agent], client=client)

    assert viable == [agent]
    assert len(client.calls) == 1
    row = report["routes"][0]
    assert row["status"] == "ready"
    assert row["attempts"] == 1
    assert row["finish_reason"] == "stop"
    assert row["reasoning_without_content"] is False


def test_preflight_fails_closed_when_every_route_rejects() -> None:
    """A healthy HTTP process is not review-ready without one live LLM route."""
    namespace = _load_launcher()
    preflight = namespace.get("_preflight_review_agents")
    error_type = namespace.get("ReviewPreflightError")
    assert callable(preflight)
    assert isinstance(error_type, type)

    agent = SimpleNamespace(
        id="openrouter_rejected", provider_name="openrouter", model="rejected/free"
    )
    client = _ProbeClient({agent.id: TimeoutError("provider timed out")})

    with pytest.raises(error_type, match="no provider route passed"):
        preflight([agent], client=client)
    assert len(client.calls) == 1


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


def test_launcher_has_no_legacy_catalog_admission_caps() -> None:
    """Runtime bootstrap must not restore retired catalog admission authority."""
    namespace = _load_launcher()
    source = _LAUNCHER.read_text(encoding="utf-8")

    assert "_bounded_primary_catalog_limit" not in namespace
    assert "_bounded_fallback_catalog_limit" not in namespace
    assert "_catalog_account_cap" not in namespace
    assert "REVIEW_PREFLIGHT_MAX_TOTAL_ROUTES" not in source
    assert "REVIEW_PREFLIGHT_PRIMARY_ROUTE_LIMIT" not in source
    assert "ORCHESTRATOR_CATALOG_LIMIT" not in source
    assert "ORCHESTRATOR_CATALOG_ACCOUNT_CAP" not in source
