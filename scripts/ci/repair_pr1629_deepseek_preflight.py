#!/usr/bin/env python3
"""Apply and verify the PR #1629 DeepSeek preflight resilience repair."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "scripts/ci/contextual_orchestrator_review_launcher.py"
TEST = ROOT / "tests/test_contextual_orchestrator_review_transient_preflight.py"
DRIVER = Path(__file__).resolve()
WORKFLOW = ROOT / ".github/workflows/pr1629-deepseek-preflight-repair.yml"

TEST_SOURCE = '''"""Regression tests for transient review preflight and reasoning deadlines."""

from __future__ import annotations

import ast
import runpy
import urllib.error
from pathlib import Path
from types import SimpleNamespace

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[1]
_LAUNCHER = _REPO_ROOT / "scripts/ci/contextual_orchestrator_review_launcher.py"
_TRANSIENT_HTTP_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


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


def _agent() -> SimpleNamespace:
    """Return the DeepSeek route shape observed in the failing workflow."""
    return SimpleNamespace(
        id="nvidia_nim_deepseek_v4_flash",
        provider_name="nvidia_nim",
        model="deepseek-ai/deepseek-v4-flash-0731",
    )


class _RetryingProbeClient:
    """Model the orchestrator's retry-enabled and one-shot passthrough seams."""

    def __init__(self, outcomes: list[object]) -> None:
        """Store deterministic provider outcomes in transport-attempt order."""
        self._outcomes = iter(outcomes)
        self.retrying_calls = 0
        self.one_shot_calls = 0
        self.transport_attempts = 0

    def proxy_send_once(
        self, agent: object, endpoint: str, payload: dict[str, object]
    ) -> dict[str, object]:
        """Fail if production preflight bypasses the retry-enabled seam."""
        del agent, endpoint, payload
        self.one_shot_calls += 1
        raise AssertionError("preflight must use the retry-enabled passthrough seam")

    def proxy_send(
        self, agent: object, endpoint: str, payload: dict[str, object]
    ) -> dict[str, object]:
        """Retry one transient outcome and leave permanent failures terminal."""
        del agent, endpoint, payload
        self.retrying_calls += 1
        retries_left = 1
        while True:
            self.transport_attempts += 1
            outcome = next(self._outcomes)
            if not isinstance(outcome, BaseException):
                assert isinstance(outcome, dict)
                return outcome
            status = getattr(outcome, "code", None)
            is_transient = status in _TRANSIENT_HTTP_STATUS or isinstance(
                outcome, (TimeoutError, ConnectionError)
            )
            if is_transient and retries_left:
                retries_left -= 1
                continue
            raise outcome


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


def test_preflight_recovers_deepseek_route_after_transient_502() -> None:
    """A single upstream 502 must not permanently discard a healthy route."""
    namespace = _load_launcher()
    agent = _agent()
    client = _RetryingProbeClient([_http_error(502), _openai_text("OK")])

    viable, report = namespace["_preflight_review_agents"]([agent], client=client)

    assert viable == [agent]
    assert client.retrying_calls == 1
    assert client.one_shot_calls == 0
    assert client.transport_attempts == 2
    route = report["routes"][0]
    assert route["status"] == "ready"
    assert route["attempts"] == 1
    assert route["transport_retry_budget"] == 1


def test_preflight_does_not_retry_permanent_auth_failure() -> None:
    """Retry enablement must not turn a 401 into repeated credential traffic."""
    namespace = _load_launcher()
    client = _RetryingProbeClient([_http_error(401)])

    with pytest.raises(namespace["ReviewPreflightError"]) as excinfo:
        namespace["_preflight_review_agents"]([_agent()], client=client)

    assert client.retrying_calls == 1
    assert client.one_shot_calls == 0
    assert client.transport_attempts == 1
    route = excinfo.value.report["routes"][0]
    assert route["status"] == "rejected"
    assert route["http_status"] == 401
    assert route["transport_retry_budget"] == 1


def test_review_clients_have_no_inference_deadline_and_one_transient_retry() -> None:
    """Both inference clients are unbounded; only preflight retries once."""
    namespace = _load_launcher()
    assert namespace["REVIEW_PREFLIGHT_TRANSIENT_RETRIES"] == 1

    calls = _review_model_client_calls()
    assert len(calls) == 2
    for call in calls:
        timeout = _keyword(call, "timeout")
        assert isinstance(timeout, ast.Constant)
        assert timeout.value is None

    preflight_calls = [call for call in calls if _keyword(call, "max_retries") is not None]
    assert len(preflight_calls) == 1
    max_retries = _keyword(preflight_calls[0], "max_retries")
    assert isinstance(max_retries, ast.Name)
    assert max_retries.id == "REVIEW_PREFLIGHT_TRANSIENT_RETRIES"
'''


def _run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run one repository command with visible output and optional checking."""
    completed = subprocess.run(
        args,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    print(f"$ {' '.join(args)}")
    print(completed.stdout, end="")
    if check and completed.returncode:
        raise RuntimeError(f"command failed with exit code {completed.returncode}: {' '.join(args)}")
    return completed


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    """Replace one exact source fragment and reject stale or ambiguous heads."""
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one exact match, found {count}")
    return text.replace(old, new, 1)


def _patch_launcher() -> None:
    """Apply the minimal retry and no-inference-timeout implementation."""
    text = LAUNCHER.read_text(encoding="utf-8")
    text = _replace_once(
        text,
        "REVIEW_TEMPERATURE = 1.0\n# ADR-0005:",
        "REVIEW_TEMPERATURE = 1.0\n"
        "# Startup probes are idempotent and route-local. Reuse the orchestrator's\n"
        "# transient classifier and jittered backoff for one recovery attempt; do\n"
        "# not turn preflight into an unbounded retry loop or duplicate provider\n"
        "# status policy in this central launcher.\n"
        "REVIEW_PREFLIGHT_TRANSIENT_RETRIES = 1\n"
        "# ADR-0005:",
        "preflight retry constant",
    )
    text = _replace_once(
        text,
        "    return not _chat_response_has_text(response)\n\n\ndef _preflight_review_agent(\n",
        "    return not _chat_response_has_text(response)\n\n\n"
        "def _send_preflight_request(\n"
        "    client: Any, agent: object, payload: dict[str, object]\n"
        ") -> object:\n"
        "    \"\"\"Use the client's bounded transient-retry path for an idempotent probe.\n\n"
        "    The vendored ``ModelClient`` exposes retry policy through\n"
        "    ``proxy_send``. The one-shot fallback exists only for deterministic\n"
        "    compatibility clients and legacy test doubles that predate that seam;\n"
        "    production review clients always take the retry-enabled branch.\n"
        "    \"\"\"\n"
        "    retrying_send = getattr(client, \"proxy_send\", None)\n"
        "    if callable(retrying_send):\n"
        "        return retrying_send(agent, \"chat/completions\", payload)\n"
        "    return client.proxy_send_once(agent, \"chat/completions\", payload)\n\n\n"
        "def _preflight_review_agent(\n",
        "preflight transport helper",
    )
    text = _replace_once(
        text,
        "    \"\"\"Probe one admitted route with route-local budget escalation evidence.\"\"\"",
        "    \"\"\"Probe one route using bounded transport retry and token escalation.\n\n"
        "    ``attempts`` counts distinct semantic payloads (base budget and, only\n"
        "    when evidenced, one larger token budget). Transient HTTP retries stay\n"
        "    inside ``ModelClient.proxy_send`` and are reported separately through\n"
        "    ``transport_retry_budget`` so the two recovery mechanisms are never\n"
        "    conflated.\n"
        "    \"\"\"",
        "preflight agent docstring",
    )
    text = _replace_once(
        text,
        '        "attempts": 1,\n',
        '        "attempts": 1,\n'
        '        "transport_retry_budget": REVIEW_PREFLIGHT_TRANSIENT_RETRIES,\n',
        "route retry evidence",
    )
    text = _replace_once(
        text,
        '        response = client.proxy_send_once(agent, "chat/completions", base_payload)\n',
        '        response = _send_preflight_request(client, agent, base_payload)\n',
        "base preflight call",
    )
    text = _replace_once(
        text,
        '        escalated_response = client.proxy_send_once(\n'
        '            agent, "chat/completions", escalated_payload\n'
        '        )\n',
        '        escalated_response = _send_preflight_request(\n'
        '            client, agent, escalated_payload\n'
        '        )\n',
        "escalated preflight call",
    )
    text = _replace_once(
        text,
        "    client = ModelClient(\n"
        "        max_output_tokens=REVIEW_MAX_OUTPUT_TOKENS,\n"
        "        max_retries=0,\n"
        "        temperature=REVIEW_TEMPERATURE,\n"
        "    )\n",
        "    client = ModelClient(\n"
        "        timeout=None,\n"
        "        max_output_tokens=REVIEW_MAX_OUTPUT_TOKENS,\n"
        "        max_retries=REVIEW_PREFLIGHT_TRANSIENT_RETRIES,\n"
        "        temperature=REVIEW_TEMPERATURE,\n"
        "    )\n",
        "preflight ModelClient",
    )
    text = _replace_once(
        text,
        "    client = ModelClient(\n"
        "        max_output_tokens=REVIEW_MAX_OUTPUT_TOKENS,\n"
        "        temperature=REVIEW_TEMPERATURE,\n"
        "    )\n",
        "    client = ModelClient(\n"
        "        timeout=None,\n"
        "        max_output_tokens=REVIEW_MAX_OUTPUT_TOKENS,\n"
        "        temperature=REVIEW_TEMPERATURE,\n"
        "    )\n",
        "serving ModelClient",
    )
    LAUNCHER.write_text(text, encoding="utf-8")


def main() -> int:
    """Run RED, apply the repair, run GREEN, and remove temporary machinery."""
    if TEST.exists():
        raise RuntimeError(f"focused regression file already exists: {TEST}")
    TEST.write_text(TEST_SOURCE, encoding="utf-8")

    red = _run(
        sys.executable,
        "-m",
        "pytest",
        "-q",
        str(TEST.relative_to(ROOT)),
        check=False,
    )
    if red.returncode == 0:
        raise RuntimeError("RED verification unexpectedly passed before the implementation")
    print("RED verified: current launcher rejects the retry-enabled contract")

    _patch_launcher()

    _run(
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "tests/test_contextual_orchestrator_review_transient_preflight.py",
        "tests/test_contextual_orchestrator_review_runtime_preflight.py",
        "tests/test_contextual_orchestrator_review_preflight_concurrency.py",
        "tests/test_contextual_orchestrator_review_sidecar_contract.py",
    )
    _run(
        sys.executable,
        "-m",
        "compileall",
        "-q",
        "scripts/ci/contextual_orchestrator_review_launcher.py",
    )
    _run(
        sys.executable,
        "-m",
        "interrogate",
        "--fail-under",
        "100",
        "scripts/ci/contextual_orchestrator_review_launcher.py",
    )
    _run("git", "diff", "--check")

    DRIVER.unlink(missing_ok=True)
    WORKFLOW.unlink(missing_ok=True)
    _run("git", "diff", "--check")
    _run("git", "status", "--short")
    print("GREEN verified: transient retry and no-inference-timeout repair is ready to commit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
