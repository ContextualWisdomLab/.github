"""Regression contract for unbounded Strix inference through contextual-orchestrator."""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "strix.yml"
TOKEN_LOADER = ROOT / "scripts" / "ci" / "load_contextual_orchestrator_token.sh"
INSTALLER = ROOT / "scripts" / "ci" / "install_strix_timeout_compat.py"
LAUNCHER = ROOT / "scripts" / "ci" / "strix_timeout_compat.py"


def _load_launcher():
    """Load the compatibility launcher without requiring Strix at test import time."""
    spec = importlib.util.spec_from_file_location("strix_timeout_compat", LAUNCHER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_strix_timeout_compat_is_installed_after_the_pinned_runtime() -> None:
    """Keep the upstream 1.5.3 parser value from becoming a real inference deadline."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    token_loader = TOKEN_LOADER.read_text(encoding="utf-8")

    # Strix 1.5.3 parses an integer here; 300 remains only as its compatible
    # bootstrap value. The trusted launcher below normalizes actual inference to
    # the repository's unbounded model-time contract before importing Strix.
    assert "export LLM_TIMEOUT=300" in workflow
    assert 'if [ -n "${STRIX_EXECUTABLE_PATH:-}" ]; then' in token_loader
    assert "install_strix_timeout_compat.py" in token_loader
    assert INSTALLER.is_file()
    assert LAUNCHER.is_file()


def test_compat_launcher_disables_request_and_stream_idle_deadlines() -> None:
    """The launcher maps the central review policy to zero/unbounded settings."""
    launcher = _load_launcher()
    environment = {"LLM_TIMEOUT": "300", "LLM_STREAM_IDLE_TIMEOUT": "300"}

    launcher.normalize_inference_timeout_environment(environment)

    assert environment["LLM_TIMEOUT"] == "0"
    assert environment["LLM_STREAM_IDLE_TIMEOUT"] == "0"
    assert launcher.SUPPORTED_VERSION == "1.5.3"


def test_compat_asyncio_proxy_removes_only_model_warmup_wait_deadline() -> None:
    """Warm-up wait_for is unbounded without globally patching asyncio."""
    launcher = _load_launcher()
    seen_timeouts: list[object] = []

    class FakeAsyncio:
        marker = "delegated"

        @staticmethod
        async def wait_for(awaitable, timeout):
            seen_timeouts.append(timeout)
            return await awaitable

    async def result():
        return "ok"

    proxy = launcher.UnboundedInferenceAsyncio(FakeAsyncio())
    assert proxy.marker == "delegated"
    assert asyncio.run(proxy.wait_for(result(), 300)) == "ok"
    assert seen_timeouts == [None]
