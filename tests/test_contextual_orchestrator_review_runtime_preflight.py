"""Regression tests for the Strix contextual-orchestrator runtime boundary."""

from __future__ import annotations

import runpy
from pathlib import Path
from types import SimpleNamespace

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_LAUNCHER = _REPO_ROOT / "scripts/ci/contextual_orchestrator_review_launcher.py"
_SIDECAR = _REPO_ROOT / "scripts/ci/contextual_orchestrator_review_sidecar.sh"


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


def _openai_text(content: str) -> dict[str, object]:
    """Build the minimal OpenAI chat response shape accepted by preflight."""
    return {"choices": [{"message": {"content": content}}]}


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

    assert "_preflight_review_agents(agents, client=client)" in launcher
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
    assert '"model":"orchestrator/free"' in sidecar
    assert "gateway preflight returned unusable chat content" in sidecar
