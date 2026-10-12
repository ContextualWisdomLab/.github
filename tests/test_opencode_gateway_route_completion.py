"""Keep a gateway request from prematurely ending CLI error evidence capture."""

import json
import subprocess

from tests import test_opencode_gateway_route_integration as integration


def test_error_evidence_waits_for_cli_completion(tmp_path, monkeypatch):
    """A recorded request is not the later error event the negative case needs."""
    clock = [0.0]
    killed = []
    error_event = json.dumps({"type": "error", "error": {"message": "not found"}}) + "\n"

    class Process:
        def poll(self):
            return 1 if clock[0] >= 25 else None

        def communicate(self, timeout=None):
            if clock[0] < 25:
                clock[0] += timeout
            if clock[0] < 25:
                raise subprocess.TimeoutExpired("opencode", timeout)
            return error_event, ""

        def kill(self):
            killed.append(True)
            raise AssertionError("CLI killed before its error event was available")

    monkeypatch.setattr(integration.subprocess, "Popen", lambda *args, **kwargs: Process())
    monkeypatch.setattr(integration.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(integration.time, "sleep", lambda duration: clock.__setitem__(0, clock[0] + duration))
    stdout, _stderr = integration._run_opencode(
        tmp_path, "{env:CONTEXTUAL_ORCHESTRATOR_BASE_URL}", "http://127.0.0.1:1", ["/chat/completions"]
    )
    assert json.loads(stdout)["type"] == "error"
    assert killed == []
