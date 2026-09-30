"""Behavior coverage for the contextual-orchestrator review launcher."""

from __future__ import annotations

import json
import logging
import runpy
import sys
import time
from pathlib import Path
from types import ModuleType, SimpleNamespace
from urllib.error import HTTPError

import pytest

from scripts.ci import contextual_orchestrator_review_launcher as launcher
from scripts.ci import contextual_orchestrator_review_policy as policy


LAUNCHER_PATH = Path(launcher.__file__)


def _discovered_model(
    *,
    provider_name: str = "bytez",
    model_id: str = "test/free",
    agent_id: str = "bytez_free",
    credential_name: str = "BYTEZ_API_KEY",
    prompt_price: float = 0.0,
    completion_price: float = 0.0,
    output_modalities: tuple[str, ...] = ("text",),
) -> SimpleNamespace:
    """Return one complete discovery row shaped like the owner runtime."""
    provider_settings = {
        "bytez": ("https://api.bytez.com/models/v2/openai/v1", "raw-token"),
        "openai": ("https://api.openai.com/v1", "bearer"),
    }
    base_url, auth_scheme = provider_settings[provider_name]
    return SimpleNamespace(
        provider_name=provider_name,
        model_id=model_id,
        agent_id=agent_id,
        chat_base_url=base_url,
        credential_name=credential_name,
        auth_scheme=auth_scheme,
        output_modalities=output_modalities,
        prompt_price_per_1k=prompt_price,
        completion_price_per_1k=completion_price,
        currency_code="USD",
    )


def _install_owner_runtime(
    monkeypatch: pytest.MonkeyPatch,
    *,
    discovered_models: list[object] | None = None,
    registered_credentials: list[str] | None = None,
    auth_token: str | None = "gateway-token",
    discovery_error: Exception | None = None,
    failing_agent_ids: frozenset[str] = frozenset(),
) -> SimpleNamespace:
    """Install controlled owner-package modules without copying owner source."""
    runtime_state = SimpleNamespace(
        discovered_models=discovered_models or [_discovered_model()],
        registered_credentials=(
            ["BYTEZ_API_KEY"]
            if registered_credentials is None
            else registered_credentials
        ),
        auth_token=auth_token,
        discovery_error=discovery_error,
        failing_agent_ids=failing_agent_ids,
        configured_levels=[],
        model_clients=[],
        served_requests=[],
    )

    owner_package = ModuleType("contextual_orchestrator")
    owner_package.__path__ = []

    credentials_module = ModuleType("contextual_orchestrator.credentials")
    credentials_module.get_credential = lambda credential_name: runtime_state.auth_token

    capability_module = ModuleType("contextual_orchestrator.chat_capability")
    capability_module.is_general_chat_agent_model_id = (
        lambda model_id: not str(model_id).startswith("embedding-")
    )

    discovery_module = ModuleType("contextual_orchestrator.model_discovery")

    def discover_all_models() -> tuple[list[object], list[object]]:
        if runtime_state.discovery_error is not None:
            raise runtime_state.discovery_error
        return runtime_state.discovered_models, []

    discovery_module.discover_all_models = discover_all_models
    discovery_module.free_discovered_models = lambda models: [
        model
        for model in models
        if getattr(model, "prompt_price_per_1k", None) == 0.0
        and getattr(model, "completion_price_per_1k", None) == 0.0
    ]

    orchestrator_module = ModuleType("contextual_orchestrator.orchestrator")

    class ModelClient:
        """Return explicit text or a bounded provider rejection by agent id."""

        def __init__(self, **settings: object) -> None:
            self.settings = settings
            runtime_state.model_clients.append(self)

        def proxy_send_once(
            self, agent: object, endpoint: str, payload: dict[str, object]
        ) -> dict[str, object]:
            if str(getattr(agent, "id", "")) in runtime_state.failing_agent_ids:
                raise HTTPError(
                    "https://provider.invalid", 401, "private", {}, None
                )
            return {
                "choices": [
                    {"finish_reason": "stop", "message": {"content": "OK"}}
                ]
            }

    class TaskOrchestrator:
        """Capture the validated serving pool."""

        def __init__(self, agents: list[object], *, client: object) -> None:
            self.agents = agents
            self.client = client

    def load_agents(catalog_path: str) -> list[SimpleNamespace]:
        catalog = json.loads(Path(catalog_path).read_text(encoding="utf-8"))
        return [SimpleNamespace(**agent) for agent in catalog["agents"]]

    orchestrator_module.ModelClient = ModelClient
    orchestrator_module.TaskOrchestrator = TaskOrchestrator
    orchestrator_module.load_agents = load_agents

    gateway_module = ModuleType("contextual_orchestrator.review_gateway")
    gateway_module.REVIEW_AUTH_CREDENTIAL_NAME = "REVIEW_GATEWAY_TOKEN"
    gateway_module.register_review_credentials = (
        lambda environment: runtime_state.registered_credentials
    )

    server_module = ModuleType("contextual_orchestrator.server")

    class SecurityConfig:
        """Retain the authentication boundary passed to the server."""

        def __init__(
            self,
            *,
            auth_token: str,
            max_body_bytes: int,
            max_concurrent_runs: int,
        ) -> None:
            self.auth_token = auth_token
            self.max_body_bytes = max_body_bytes
            self.max_concurrent_runs = max_concurrent_runs

    def serve(
        orchestrator: object,
        *,
        host: str,
        port: int,
        security: object,
    ) -> None:
        runtime_state.served_requests.append(
            SimpleNamespace(
                orchestrator=orchestrator,
                host=host,
                port=port,
                security=security,
            )
        )

    server_module.SecurityConfig = SecurityConfig
    server_module.serve = serve

    logging_module = ModuleType("contextual_orchestrator.debug_logging")
    logging_module.configure_logging = runtime_state.configured_levels.append

    owner_modules = {
        "contextual_orchestrator": owner_package,
        "contextual_orchestrator.credentials": credentials_module,
        "contextual_orchestrator.chat_capability": capability_module,
        "contextual_orchestrator.model_discovery": discovery_module,
        "contextual_orchestrator.orchestrator": orchestrator_module,
        "contextual_orchestrator.review_gateway": gateway_module,
        "contextual_orchestrator.server": server_module,
        "contextual_orchestrator.debug_logging": logging_module,
    }
    for module_name, module_value in owner_modules.items():
        monkeypatch.setitem(sys.modules, module_name, module_value)
    return runtime_state


def _launcher_arguments(temporary_path: Path, *extra_arguments: str) -> list[str]:
    """Return complete launcher arguments rooted in one temporary directory."""
    return [
        "--discovery-out",
        str(temporary_path / "discovery.json"),
        "--catalog-out",
        str(temporary_path / "catalog.json"),
        "--report-out",
        str(temporary_path / "report.json"),
        "--preflight-out",
        str(temporary_path / "preflight.json"),
        *extra_arguments,
    ]


def test_main_serves_a_discovered_free_route(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A free text route reaches the authenticated loopback server."""
    runtime_state = _install_owner_runtime(
        monkeypatch,
        discovered_models=[
            _discovered_model(),
            _discovered_model(
                provider_name="openai",
                model_id="gpt-priced",
                agent_id="openai_priced",
                credential_name="OPENAI_API_KEY",
                prompt_price=1.0,
                completion_price=2.0,
            ),
        ],
        registered_credentials=["BYTEZ_API_KEY", "OPENAI_API_KEY"],
    )

    assert launcher.main(_launcher_arguments(tmp_path)) == 0

    assert runtime_state.configured_levels == [launcher.DEFAULT_SIDECAR_LOG_LEVEL]
    assert len(runtime_state.served_requests) == 1
    served_request = runtime_state.served_requests[0]
    assert served_request.host == "127.0.0.1"
    assert served_request.port == 18080
    assert served_request.security.auth_token == "gateway-token"
    assert served_request.security.max_body_bytes == launcher.REVIEW_MAX_BODY_BYTES
    assert served_request.security.max_concurrent_runs == 16
    assert [agent.id for agent in served_request.orchestrator.agents] == [
        "bytez_free"
    ]
    assert json.loads((tmp_path / "preflight.json").read_text(encoding="utf-8"))[
        "ready_count"
    ] == 1


def test_main_uses_the_priced_fallback_only_after_free_routes_fail(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Auto mode replaces a rejected free catalog with its priced successor."""
    free_model = _discovered_model()
    priced_model = _discovered_model(
        provider_name="openai",
        model_id="gpt-priced",
        agent_id="openai_priced",
        credential_name="OPENAI_API_KEY",
        prompt_price=1.0,
        completion_price=2.0,
    )
    runtime_state = _install_owner_runtime(
        monkeypatch,
        discovered_models=[free_model, priced_model],
        registered_credentials=["BYTEZ_API_KEY", "OPENAI_API_KEY"],
        failing_agent_ids=frozenset({"bytez_free"}),
    )

    assert launcher.main(_launcher_arguments(tmp_path, "--pool", "auto")) == 0

    catalog = json.loads((tmp_path / "catalog.json").read_text(encoding="utf-8"))
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert [agent["id"] for agent in catalog["agents"]] == ["openai_priced"]
    assert report["fallback_reason"] == "primary_routes_unavailable"
    assert report["primary_selected_count"] == 1
    assert not (tmp_path / "catalog.json.priced").exists()
    assert [agent.id for agent in runtime_state.served_requests[0].orchestrator.agents] == [
        "openai_priced"
    ]


def test_main_keeps_the_free_catalog_when_priced_policy_rejects_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An unavailable optional priced catalog cannot replace a valid free pool."""
    free_model = _discovered_model()
    priced_model = _discovered_model(
        provider_name="openai",
        model_id="gpt-priced",
        agent_id="openai_priced",
        credential_name="OPENAI_API_KEY",
        prompt_price=1.0,
        completion_price=2.0,
    )
    _install_owner_runtime(
        monkeypatch,
        discovered_models=[free_model, priced_model],
        registered_credentials=["BYTEZ_API_KEY", "OPENAI_API_KEY"],
    )
    real_builder = policy.build_zdr_prioritized_catalog

    def reject_priced_rows(rows: list[dict[str, object]], **settings: object) -> object:
        if rows and all(row.get("cost_evidence") == "priced" for row in rows):
            raise policy.PolicyError("priced fallback unavailable")
        return real_builder(rows, **settings)

    monkeypatch.setattr(policy, "build_zdr_prioritized_catalog", reject_priced_rows)

    assert launcher.main(_launcher_arguments(tmp_path, "--pool", "auto")) == 0
    catalog = json.loads((tmp_path / "catalog.json").read_text(encoding="utf-8"))
    assert [agent["id"] for agent in catalog["agents"]] == ["bytez_free"]


@pytest.mark.parametrize(
    ("runtime_settings", "expected_message"),
    (
        ({"auth_token": None}, "requires an explicit --auth-token"),
        ({"registered_credentials": []}, "requires at least one provider credential"),
        (
            {"discovery_error": RuntimeError("discovery unavailable")},
            "review sidecar discovery failed: discovery unavailable",
        ),
        (
            {
                "discovered_models": [
                    _discovered_model(output_modalities=("image",))
                ]
            },
            "discovered no eligible models",
        ),
    ),
)
def test_main_fails_closed_before_serving_invalid_runtime_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    runtime_settings: dict[str, object],
    expected_message: str,
) -> None:
    """Missing trust prerequisites terminate before a server can be exposed."""
    runtime_state = _install_owner_runtime(monkeypatch, **runtime_settings)

    with pytest.raises(SystemExit, match=expected_message):
        launcher.main(_launcher_arguments(tmp_path))

    assert runtime_state.served_requests == []


def test_main_persists_sanitized_preflight_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A provider rejection writes bounded evidence and never starts serving."""
    runtime_state = _install_owner_runtime(
        monkeypatch, failing_agent_ids=frozenset({"bytez_free"})
    )

    with pytest.raises(SystemExit, match="review sidecar preflight failed"):
        launcher.main(_launcher_arguments(tmp_path))

    preflight_report = json.loads(
        (tmp_path / "preflight.json").read_text(encoding="utf-8")
    )
    assert preflight_report["routes"][0]["http_status"] == 401
    assert "private" not in json.dumps(preflight_report)
    assert "preflight_route_rejected provider=bytez" in capsys.readouterr().err
    assert runtime_state.served_requests == []


def test_script_entrypoint_exits_with_main_result(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Direct script execution propagates the successful launcher exit code."""
    runtime_state = _install_owner_runtime(monkeypatch)
    monkeypatch.setattr(
        sys, "argv", [str(LAUNCHER_PATH), *_launcher_arguments(tmp_path)]
    )

    with pytest.raises(SystemExit) as exit_result:
        runpy.run_path(str(LAUNCHER_PATH), run_name="__main__")

    assert exit_result.value.code == 0
    assert len(runtime_state.served_requests) == 1


@pytest.mark.parametrize(
    ("response_value", "expected_text", "expected_reasoning"),
    (
        (object(), False, False),
        ({"choices": [object()]}, False, False),
        ({"choices": [{"message": object()}]}, False, False),
        (
            {"choices": [{"finish_reason": "bad-value!", "message": {}}]},
            False,
            False,
        ),
    ),
)
def test_response_parsers_reject_malformed_provider_shapes(
    response_value: object, expected_text: bool, expected_reasoning: bool
) -> None:
    """Malformed response layers remain unusable without raising."""
    assert launcher._chat_response_has_text(response_value) is expected_text
    assert (
        launcher._response_has_reasoning_without_content(response_value)
        is expected_reasoning
    )
    finish_reason = launcher._response_finish_reason(response_value)
    if isinstance(response_value, dict) and response_value.get("choices"):
        first_choice = response_value["choices"][0]
        if isinstance(first_choice, dict) and first_choice.get("finish_reason"):
            assert finish_reason == "unknown"
            return
    assert finish_reason is None


def test_report_rows_skip_missing_identity_and_use_policy_defaults() -> None:
    """Only complete route identities become policy rows."""
    missing_identity = SimpleNamespace(provider_name="", model_id="")
    defaulted_model = SimpleNamespace(
        provider_name="bytez",
        model_id="test/free",
        agent_id="bytez_free",
        output_modalities=("text",),
    )

    assert launcher._route_identity(SimpleNamespace()) == ("", "")
    assert launcher._report_rows([missing_identity], frozenset()) == []
    row = launcher._report_rows(
        [defaulted_model], frozenset({("bytez", "test/free")})
    )[0]
    assert row["base_url"] == "https://api.bytez.com/models/v2/openai/v1"
    assert row["credential_key"] == "BYTEZ_API_KEY"
    assert row["auth_scheme"] == "Key"


@pytest.mark.parametrize(
    ("function_call", "expected_message"),
    (
        (
            lambda: launcher._bounded_primary_catalog_limit(
                0, pool="free", has_free_rows=True
            ),
            "must be positive",
        ),
        (
            lambda: launcher._bounded_fallback_catalog_limit(0, primary_count=0),
            "must be positive",
        ),
        (
            lambda: launcher._bounded_fallback_catalog_limit(4, primary_count=5),
            "exceeds the preflight budget",
        ),
    ),
)
def test_catalog_limits_reject_impossible_budgets(
    function_call: object, expected_message: str
) -> None:
    """Invalid catalog budgets fail before route selection."""
    with pytest.raises(ValueError, match=expected_message):
        function_call()


def test_preflight_without_fallback_preserves_the_primary_failure() -> None:
    """A failed primary stage cannot be disguised when no successor exists."""
    primary_report = {"routes": [], "escalations_used": 0}

    def reject_primary(agents: list[object], **settings: object) -> object:
        raise launcher.ReviewPreflightError("primary unavailable", primary_report)

    with pytest.raises(launcher.ReviewPreflightError) as error_result:
        launcher._preflight_with_fallback(
            [object()], [], client=object(), preflight=reject_primary
        )

    assert error_result.value.report is primary_report


def test_concurrent_preflight_waits_for_an_outstanding_route() -> None:
    """Exhausting the iterator waits for its live probe instead of failing early."""
    agent = SimpleNamespace(
        id="slow-ready", provider_name="bytez", model="test/free", priority=0
    )

    class SlowClient:
        """Delay long enough for the scheduler to enter its blocking receive."""

        def proxy_send_once(
            self, selected_agent: object, endpoint: str, payload: dict[str, object]
        ) -> dict[str, object]:
            time.sleep(0.02)
            return {
                "choices": [
                    {"finish_reason": "stop", "message": {"content": "OK"}}
                ]
            }

    viable_agents, preflight_report = launcher._preflight_review_agents_concurrently(
        [agent], client=SlowClient()
    )

    assert viable_agents == [agent]
    assert preflight_report["ready_count"] == 1


def test_postponed_concurrent_probe_cannot_spend_an_escalation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A postponed candidate reports the first-pass escalation reservation."""
    agents = [
        SimpleNamespace(
            id=str(index), provider_name="bytez", model=f"test/{index}", priority=0
        )
        for index in range(3)
    ]
    probe_calls = 0

    def deterministic_probe(
        selected_agents: list[object], **settings: object
    ) -> tuple[list[object], dict[str, object]]:
        nonlocal probe_calls
        probe_calls += 1
        selected_agent = selected_agents[0]
        if probe_calls <= 2:
            route = {
                "agent_id": selected_agent.id,
                "provider": "bytez",
                "model": selected_agent.model,
                "status": "rejected",
                "error_type": "HTTPError",
                "http_status": 429,
            }
        else:
            route = {
                "agent_id": selected_agent.id,
                "provider": "bytez",
                "model": selected_agent.model,
                "status": "rejected",
                "error_type": "escalation_budget_exhausted",
            }
        report = {
            "routes": [route],
            "escalations_used": launcher.REVIEW_PREFLIGHT_MAX_ESCALATIONS,
        }
        raise launcher.ReviewPreflightError("unavailable", report)

    monkeypatch.setattr(launcher, "_preflight_review_agents", deterministic_probe)

    with pytest.raises(launcher.ReviewPreflightError) as error_result:
        launcher._preflight_review_agents_concurrently(agents, client=object())

    postponed_route = error_result.value.report["routes"][2]
    assert postponed_route["error_type"] == "escalation_reserved_for_first_pass"
