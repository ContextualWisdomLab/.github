"""No-heuristics contracts for the shared contextual-orchestrator review sidecar."""

from __future__ import annotations

import ast
from pathlib import Path
import runpy
from types import SimpleNamespace


_REPO_ROOT = Path(__file__).resolve().parents[1]
_LAUNCHER = _REPO_ROOT / "scripts/ci/contextual_orchestrator_review_launcher.py"


class _SequenceClient:
    def __init__(self, outcomes: list[object]) -> None:
        self._outcomes = iter(outcomes)
        self.calls: list[dict[str, object]] = []

    def proxy_send_once(self, _agent: object, _endpoint: str, payload: dict[str, object]) -> object:
        self.calls.append(dict(payload))
        outcome = next(self._outcomes)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _launcher_namespace() -> dict[str, object]:
    return runpy.run_path(str(_LAUNCHER))


def test_preflight_contains_no_repository_authored_sampling_or_token_allocation() -> None:
    """Startup admission may observe provider behavior but may not invent TTC knobs."""
    source = _LAUNCHER.read_text(encoding="utf-8")
    tree = ast.parse(source)

    forbidden_names = {
        "REVIEW_MAX_OUTPUT_TOKENS",
        "REVIEW_TEMPERATURE",
        "REVIEW_PREFLIGHT_BASE_TOKENS",
        "REVIEW_PREFLIGHT_ESCALATED_TOKENS",
        "REVIEW_PREFLIGHT_MAX_ESCALATIONS",
        "REVIEW_PREFLIGHT_MAX_TOTAL_ROUTES",
        "REVIEW_PREFLIGHT_PRIMARY_ROUTE_LIMIT",
    }
    assigned_names = {
        target.id
        for node in ast.walk(tree)
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        for target in (
            node.targets if isinstance(node, ast.Assign) else [node.target]
        )
        if isinstance(target, ast.Name)
    }
    assert forbidden_names.isdisjoint(assigned_names)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        literal_keys = {
            key.value
            for key in node.keys
            if isinstance(key, ast.Constant) and isinstance(key.value, str)
        }
        assert "temperature" not in literal_keys
        assert "max_tokens" not in literal_keys


def test_budget_starvation_evidence_does_not_allocate_an_ad_hoc_second_model_call() -> None:
    """Without an identified compute model, a starved probe fails closed after one call."""
    namespace = _launcher_namespace()
    preflight = namespace["_preflight_review_agents"]
    agent = SimpleNamespace(id="provider_one", provider_name="nvidia_nim", model="provider/model")
    client = _SequenceClient(
        [
            {
                "choices": [
                    {
                        "message": {"content": "", "reasoning": "incomplete"},
                        "finish_reason": "length",
                    }
                ]
            }
        ]
    )

    error_type = namespace["ReviewPreflightError"]
    try:
        preflight([agent], client=client)
    except error_type as exc:
        report = exc.report
    else:  # pragma: no cover - this is the forbidden behavior
        raise AssertionError("starved preflight must fail closed without allocating another model call")

    assert len(client.calls) == 1
    assert "max_tokens" not in client.calls[0]
    assert "temperature" not in client.calls[0]
    assert report["routes"][0]["status"] == "rejected"
    assert report["routes"][0]["error_type"] == "insufficient_preflight_evidence"
    assert "escalations_used" not in report
    assert "escalation_budget" not in report


def test_preflight_success_uses_provider_defaults_and_one_model_call() -> None:
    """A successful compatibility observation is one provider-default request."""
    namespace = _launcher_namespace()
    preflight = namespace["_preflight_review_agents"]
    agent = SimpleNamespace(id="provider_one", provider_name="openrouter", model="provider/model")
    client = _SequenceClient(
        [{"choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}]}]
    )

    viable, report = preflight([agent], client=client)

    assert viable == [agent]
    assert len(client.calls) == 1
    assert client.calls[0] == {
        "model": "provider/model",
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Reply with just 'OK'."},
        ],
        "stream": False,
    }
    assert report["ready_count"] == 1
    assert "escalations_used" not in report
