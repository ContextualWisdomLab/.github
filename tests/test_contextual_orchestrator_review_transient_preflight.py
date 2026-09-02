"""Regression tests for provider-neutral preflight evidence and inference deadlines."""

from __future__ import annotations

import ast
import runpy
import urllib.error
from pathlib import Path
from types import SimpleNamespace

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[1]
_LAUNCHER = _REPO_ROOT / "scripts/ci/contextual_orchestrator_review_launcher.py"


def _load_launcher() -> dict[str, object]:
    """Execute the dependency-lazy launcher and return its module namespace."""
    return runpy.run_path(str(_LAUNCHER))


def _http_error(status: int) -> urllib.error.HTTPError:
    """Build one deterministic provider HTTP failure."""
    return urllib.error.HTTPError(
        "https://provider.example/v1/chat/completions",
        status,
        "provider failure",
        {},
        None,
    )


def _openai_text(content: str) -> dict[str, object]:
    """Build the smallest usable OpenAI-compatible chat response."""
    return {
        "choices": [
            {"finish_reason": "stop", "message": {"content": content}}
        ]
    }


def _agent(*, reasoning_effort_supported: bool | None = None) -> SimpleNamespace:
    """Return a provider-neutral route with optional reasoning capability evidence."""
    return SimpleNamespace(
        id="provider_route",
        provider_name="provider",
        model="arbitrary-chat-model",
        reasoning_effort_supported=reasoning_effort_supported,
    )


class _OneShotProbeClient:
    """Model one-shot provider sends and reject retry-enabled transport use."""

    def __init__(self, outcomes: list[object]) -> None:
        """Store deterministic provider outcomes in semantic-payload order."""
        self._outcomes = iter(outcomes)
        self.retrying_calls = 0
        self.one_shot_calls = 0
        self.transport_attempts = 0
        self.payloads: list[dict[str, object]] = []

    def proxy_send_once(
        self, agent: object, endpoint: str, payload: dict[str, object]
    ) -> dict[str, object]:
        """Send one exact payload once and return or raise its observed outcome."""
        del agent, endpoint
        self.payloads.append(dict(payload))
        self.one_shot_calls += 1
        self.transport_attempts += 1
        outcome = next(self._outcomes)
        if isinstance(outcome, BaseException):
            raise outcome
        assert isinstance(outcome, dict)
        return outcome

    def proxy_send(
        self, agent: object, endpoint: str, payload: dict[str, object]
    ) -> dict[str, object]:
        """Fail if production preflight reintroduces retry-enabled transport."""
        del agent, endpoint, payload
        self.retrying_calls += 1
        raise AssertionError("preflight must use the one-shot passthrough seam")


def _keyword(call: ast.Call, name: str) -> ast.expr | None:
    """Return one keyword expression from an AST call, if present."""
    return next((item.value for item in call.keywords if item.arg == name), None)


def _review_model_client_calls() -> list[ast.Call]:
    """Return the two review-runtime ModelClient constructor calls."""
    tree = ast.parse(_LAUNCHER.read_text(encoding="utf-8"))
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "ModelClient"
        and _keyword(node, "max_output_tokens") is not None
    ]


@pytest.mark.parametrize("reasoning_effort_supported", [None, False, True])
def test_preflight_rejects_transient_502_after_one_attempt_independent_of_reasoning_capability(
    reasoning_effort_supported: bool | None,
) -> None:
    """Transient taxonomy is evidence only and cannot manufacture another model call."""
    namespace = _load_launcher()
    agent = _agent(reasoning_effort_supported=reasoning_effort_supported)
    client = _OneShotProbeClient([_http_error(502)])

    with pytest.raises(namespace["ReviewPreflightError"]) as excinfo:
        namespace["_preflight_review_agents"]([agent], client=client)

    assert client.retrying_calls == 0
    assert client.one_shot_calls == 1
    assert client.transport_attempts == 1
    route = excinfo.value.report["routes"][0]
    assert route["status"] == "rejected"
    assert route["http_status"] == 502
    assert route["attempts"] == 1
    assert "transport_retry_budget" not in route


def test_preflight_does_not_retry_permanent_auth_failure() -> None:
    """A 401 remains a single provider call with bounded typed evidence."""
    namespace = _load_launcher()
    client = _OneShotProbeClient([_http_error(401)])

    with pytest.raises(namespace["ReviewPreflightError"]) as excinfo:
        namespace["_preflight_review_agents"]([_agent()], client=client)

    assert client.retrying_calls == 0
    assert client.one_shot_calls == 1
    assert client.transport_attempts == 1
    route = excinfo.value.report["routes"][0]
    assert route["status"] == "rejected"
    assert route["http_status"] == 401
    assert "transport_retry_budget" not in route


def test_reasoning_budget_escalation_uses_response_evidence_not_model_name() -> None:
    """Semantic token recovery follows the response while each payload stays one-shot."""
    namespace = _load_launcher()
    agent = _agent(reasoning_effort_supported=None)
    client = _OneShotProbeClient(
        [
            {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "reasoning": "internal reasoning consumed the base budget",
                            "content": "",
                        },
                    }
                ]
            },
            _openai_text("OK"),
        ]
    )

    viable, report = namespace["_preflight_review_agents"]([agent], client=client)

    assert viable == [agent]
    assert client.retrying_calls == 0
    assert client.one_shot_calls == 2
    assert client.transport_attempts == 2
    assert [payload["max_tokens"] for payload in client.payloads] == [16, 4096]
    route = report["routes"][0]
    assert route["status"] == "ready"
    assert route["attempts"] == 2
    assert route["escalated"] is True
    assert route["reasoning_without_content"] is False
    assert "transport_retry_budget" not in route


def test_review_clients_have_no_inference_deadline_or_transport_retry() -> None:
    """Both preflight and serving clients are deadline-free and one-shot."""
    namespace = _load_launcher()
    assert "REVIEW_PREFLIGHT_TRANSIENT_RETRIES" not in namespace

    calls = _review_model_client_calls()
    assert len(calls) == 2
    for call in calls:
        timeout = _keyword(call, "timeout")
        assert isinstance(timeout, ast.Constant)
        assert timeout.value is None
        max_retries = _keyword(call, "max_retries")
        assert isinstance(max_retries, ast.Constant)
        assert max_retries.value == 0
