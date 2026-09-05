"""Regression coverage for evidence-backed review-sidecar preflight concurrency."""

from __future__ import annotations

import runpy
import threading
from pathlib import Path
from types import SimpleNamespace

_REPO_ROOT = Path(__file__).resolve().parents[1]
_LAUNCHER = _REPO_ROOT / "scripts/ci/contextual_orchestrator_review_launcher.py"


class _ProviderBarrierProbeClient:
    """Require independent providers to progress together without same-account bursts."""

    def __init__(self, provider_count: int) -> None:
        self._provider_count = provider_count
        self._started_providers: set[str] = set()
        self._active_by_provider: dict[str, int] = {}
        self._providers_started = threading.Event()
        self._lock = threading.Lock()
        self.calls: list[str] = []
        self.same_provider_overlap = False

    def proxy_send_once(
        self, agent: object, endpoint: str, payload: dict[str, object]
    ) -> dict[str, object]:
        """Expose both cross-provider progress and same-provider overlap deterministically."""
        assert endpoint == "chat/completions"
        assert payload["max_tokens"] == 16
        provider = str(getattr(agent, "provider_name"))
        with self._lock:
            active = self._active_by_provider.get(provider, 0)
            if active:
                self.same_provider_overlap = True
            self._active_by_provider[provider] = active + 1
            self._started_providers.add(provider)
            self.calls.append(str(getattr(agent, "id")))
            if len(self._started_providers) >= self._provider_count:
                self._providers_started.set()

        if not self._providers_started.wait(timeout=0.5):
            raise RuntimeError("independent provider probes did not start concurrently")

        with self._lock:
            self._active_by_provider[provider] -= 1
        return {
            "choices": [
                {"finish_reason": "stop", "message": {"content": "OK"}}
            ]
        }


def _load_launcher() -> dict[str, object]:
    """Execute the dependency-lazy launcher and return its module namespace."""
    return runpy.run_path(str(_LAUNCHER))


def test_preflight_parallelizes_independent_providers_without_same_account_burst() -> None:
    """Provider accounts are concurrent lanes, while routes sharing one stay serialized.

    The review fleet has observed shared-key 429 storms when every model backed by
    one credential starts at once. Admission still includes the full catalog;
    only transport concurrency is keyed by the independently credentialed
    provider/account identity. Distinct providers must make progress together,
    and completion timing must not reorder persisted evidence.
    """
    namespace = _load_launcher()
    preflight = namespace["_preflight_review_agents"]
    agents = [
        SimpleNamespace(id="provider_a_model_1", provider_name="provider_a", model="model-1"),
        SimpleNamespace(id="provider_a_model_2", provider_name="provider_a", model="model-2"),
        SimpleNamespace(id="provider_b_model_1", provider_name="provider_b", model="model-1"),
    ]
    client = _ProviderBarrierProbeClient(provider_count=2)

    viable, report = preflight(agents, client=client)

    assert viable == agents
    assert report["probed_count"] == len(agents)
    assert report["ready_count"] == len(agents)
    assert report["rejected_count"] == 0
    assert [row["agent_id"] for row in report["routes"]] == [agent.id for agent in agents]
    assert [row["status"] for row in report["routes"]] == ["ready"] * len(agents)
    assert sorted(client.calls) == sorted(agent.id for agent in agents)
    assert client.same_provider_overlap is False


def test_preflight_worker_cardinality_tracks_provider_accounts_not_route_count() -> None:
    """The executor must derive concurrency from evidence identities, not a route cap."""
    source = _LAUNCHER.read_text(encoding="utf-8")
    assert "provider_lanes" in source
    assert "max_workers=len(provider_lanes)" in source
    assert "max_workers=len(agents)" not in source
