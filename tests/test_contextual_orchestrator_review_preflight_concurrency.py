"""Regression coverage for bounded-latency review-sidecar startup preflight."""

from __future__ import annotations

import runpy
import threading
from pathlib import Path
from types import SimpleNamespace

_REPO_ROOT = Path(__file__).resolve().parents[1]
_LAUNCHER = _REPO_ROOT / "scripts/ci/contextual_orchestrator_review_launcher.py"


class _BarrierProbeClient:
    """Require every catalog route to enter transport before any may complete."""

    def __init__(self, agent_count: int) -> None:
        self._barrier = threading.Barrier(agent_count, timeout=0.5)
        self.calls: list[str] = []
        self._lock = threading.Lock()

    def proxy_send_once(self, agent: object, endpoint: str, payload: dict[str, object]) -> dict[str, object]:
        """Fail a sequential implementation while allowing concurrent probes through."""
        assert endpoint == "chat/completions"
        assert payload["max_tokens"] == 16
        with self._lock:
            self.calls.append(str(getattr(agent, "id")))
        self._barrier.wait()
        return {"choices": [{"finish_reason": "stop", "message": {"content": "OK"}}]}


def _load_launcher() -> dict[str, object]:
    """Execute the dependency-lazy launcher and return its module namespace."""
    return runpy.run_path(str(_LAUNCHER))


def test_full_catalog_preflight_starts_routes_concurrently_and_preserves_evidence_order() -> None:
    """A slow first route must not serialize every later admitted route at startup.

    This is the executable regression for the externally demonstrated false
    negative on PR #1629: sequential startup work made review latency scale as
    the sum of per-provider delays and could consume the workflow deadline
    before the sidecar began serving.  The barrier makes that defect causal and
    deterministic rather than asserting a fragile wall-clock threshold.
    """
    namespace = _load_launcher()
    preflight = namespace["_preflight_review_agents"]
    agents = [
        SimpleNamespace(id=f"route_{index}", provider_name="provider", model=f"model-{index}")
        for index in range(3)
    ]
    client = _BarrierProbeClient(len(agents))

    viable, report = preflight(agents, client=client)

    assert viable == agents
    assert report["probed_count"] == len(agents)
    assert report["ready_count"] == len(agents)
    assert report["rejected_count"] == 0
    assert [row["agent_id"] for row in report["routes"]] == [agent.id for agent in agents]
    assert [row["status"] for row in report["routes"]] == ["ready"] * len(agents)
    assert sorted(client.calls) == sorted(agent.id for agent in agents)
