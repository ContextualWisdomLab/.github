"""Regression for #1611: malformed model verdicts are infrastructure/model evidence.

A schema-valid JSON envelope whose adversarial probe uses an out-of-domain
outcome is not a consumer repository defect. The deterministic validator must
still reject it, but with a typed model-output error so the retry/control plane
can preserve the distinction from source findings and provider exhaustion.
"""

import pytest

from scripts.ci import noema_review_gate as gate


DIFF = """diff --git a/README.md b/README.md
index 1111111..2222222 100644
--- a/README.md
+++ b/README.md
@@ -1 +1 @@
-old
+new
"""


def _verdict() -> dict:
    return {
        "decision": "approve",
        "summary": "The changed line was reviewed.",
        "reviewed_lines": [
            {
                "path": "README.md",
                "line": 1,
                "side": "RIGHT",
                "analysis": "The replacement is bounded and reviewable.",
            }
        ],
        "adversarial_validation": {
            "status": "passed",
            "residual_risk": "No additional risk identified.",
            "probes": [
                {
                    "path": "README.md",
                    "line": 1,
                    "side": "RIGHT",
                    "hypothesis": "The replacement could be wrong.",
                    "attack_or_counterexample": "Compare the exact changed line.",
                    "evidence": "Observed the exact replacement in the diff.",
                    "outcome": "passed",  # real #1611 failure shape
                }
            ],
        },
        "findings": [],
    }


def test_invalid_probe_outcome_is_typed_model_output_failure() -> None:
    """Reject malformed LLM evidence without reclassifying it as source failure."""
    error_type = getattr(gate, "NoemaModelOutputError", None)
    assert error_type is not None, (
        "Noema must expose a typed model-output/schema failure so malformed "
        "LLM evidence cannot collapse into an opaque generic RuntimeError"
    )

    with pytest.raises(error_type, match="outcome must be falsified or confirmed"):
        gate.validate_substantive_verdict(_verdict(), DIFF, ["README.md"])



def test_bounded_repair_preserves_initial_schema_and_transport_evidence(monkeypatch) -> None:
    """A malformed verdict followed by 502 keeps both typed evidence classes."""
    import json
    import urllib.error

    monkeypatch.setenv("NOEMA_LLM_API_URL", "https://llm.example/v1/chat/completions")
    monkeypatch.setenv("NOEMA_LLM_API_KEY", "test-key")
    head_sha = "a" * 40
    requests: list[tuple[object, dict]] = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return json.dumps(
                {"choices": [{"message": {"content": json.dumps(_verdict())}}]}
            ).encode()

    def open_response(_opener, request, **kwargs):
        requests.append((request, kwargs))
        if len(requests) == 1:
            return Response()
        raise urllib.error.HTTPError(request.full_url, 502, "Bad Gateway", {}, None)

    monkeypatch.setattr(gate.urllib.request.OpenerDirector, "open", open_response)
    monkeypatch.setattr(
        gate,
        "fetch_pr",
        lambda _repo, _number: {"headRefOid": head_sha},
    )

    with pytest.raises(gate.NoemaTransportError) as exc_info:
        gate.call_llm(
            "owner/repo",
            7,
            {"title": "test", "headRefOid": head_sha},
            DIFF,
            False,
            head_sha,
            changed_paths=("README.md",),
        )

    message = str(exc_info.value)
    assert "outcome must be falsified or confirmed" in message
    assert "HTTPError" in message
    assert "502" in message
    assert len(requests) == 2
    assert requests[0][1] == {}
    assert requests[1][1] == {}


def test_repeated_model_output_failure_remains_typed(monkeypatch) -> None:
    """A second malformed verdict fails closed as model-output evidence."""
    import json

    monkeypatch.setenv("NOEMA_LLM_API_URL", "https://llm.example/v1/chat/completions")
    monkeypatch.setenv("NOEMA_LLM_API_KEY", "test-key")
    head_sha = "b" * 40

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return json.dumps(
                {"choices": [{"message": {"content": json.dumps(_verdict())}}]}
            ).encode()

    monkeypatch.setattr(
        gate.urllib.request.OpenerDirector,
        "open",
        lambda *_args, **_kwargs: Response(),
    )
    monkeypatch.setattr(
        gate,
        "fetch_pr",
        lambda _repo, _number: {"headRefOid": head_sha},
    )

    with pytest.raises(gate.NoemaModelOutputError) as exc_info:
        gate.call_llm(
            "owner/repo",
            7,
            {"title": "test", "headRefOid": head_sha},
            DIFF,
            False,
            head_sha,
            changed_paths=("README.md",),
        )

    assert "initial failure" in str(exc_info.value)
    assert "repair failure" in str(exc_info.value)



def test_total_repair_wall_clock_deadline_interrupts_slow_read(monkeypatch) -> None:
    """Trickling/slow response activity cannot extend the one repair budget."""
    import json
    import signal
    import time

    if not hasattr(signal, "setitimer"):
        pytest.skip("POSIX process timer is required by the Linux review runner")

    monkeypatch.setenv("NOEMA_LLM_API_URL", "https://llm.example/v1/chat/completions")
    monkeypatch.setenv("NOEMA_LLM_API_KEY", "test-key")
    monkeypatch.setattr(gate, "NOEMA_REPAIR_DEADLINE_SECONDS", 0.05)
    head_sha = "d" * 40
    calls = 0

    class FirstResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return json.dumps(
                {"choices": [{"message": {"content": json.dumps(_verdict())}}]}
            ).encode()

    class SlowRepairResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            time.sleep(2)
            return b"{}"

    def open_response(_opener, _request, **kwargs):
        nonlocal calls
        calls += 1
        assert kwargs == {}
        return FirstResponse() if calls == 1 else SlowRepairResponse()

    monkeypatch.setattr(gate.urllib.request.OpenerDirector, "open", open_response)
    monkeypatch.setattr(gate, "fetch_pr", lambda _repo, _number: {"headRefOid": head_sha})

    started = time.monotonic()
    with pytest.raises(gate.NoemaTransportError) as exc_info:
        gate.call_llm(
            "owner/repo",
            7,
            {"title": "test", "headRefOid": head_sha},
            DIFF,
            False,
            head_sha,
            changed_paths=("README.md",),
        )
    elapsed = time.monotonic() - started

    message = str(exc_info.value)
    assert "outcome must be falsified or confirmed" in message
    assert "NoemaRepairDeadlineExceeded" in message
    assert "wall-clock deadline" in message
    assert elapsed < 1.0
    assert calls == 2
    assert signal.getitimer(signal.ITIMER_REAL)[0] == 0



def test_repair_wall_clock_deadline_defensive_fail_closed_paths(monkeypatch) -> None:
    """Invalid budgets/platform state fail closed instead of weakening the bound."""
    import signal

    with pytest.raises(ValueError, match="must be positive"):
        with gate._repair_wall_clock_deadline(0):
            pass

    if not hasattr(signal, "setitimer"):
        pytest.skip("remaining cases require POSIX setitimer")

    monkeypatch.delattr(gate.signal, "setitimer")
    with pytest.raises(RuntimeError, match="requires POSIX setitimer support"):
        with gate._repair_wall_clock_deadline(1):
            pass


def test_repair_wall_clock_deadline_refuses_existing_process_alarm() -> None:
    """Noema never overwrites another caller's active process alarm."""
    import signal

    if not hasattr(signal, "setitimer"):
        pytest.skip("POSIX process timer is required by the Linux review runner")
    signal.setitimer(signal.ITIMER_REAL, 30)
    try:
        with pytest.raises(RuntimeError, match="refused to overwrite"):
            with gate._repair_wall_clock_deadline(1):
                pass
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)


def test_repair_wall_clock_deadline_rejects_non_main_thread_signal_context(monkeypatch) -> None:
    """A signal handler that cannot be installed fails closed before any timer starts."""
    import signal

    if not hasattr(signal, "setitimer"):
        pytest.skip("POSIX process timer is required by the Linux review runner")

    def reject_signal(*_args, **_kwargs):
        raise ValueError("signal only works in main thread")

    monkeypatch.setattr(gate.signal, "signal", reject_signal)
    with pytest.raises(RuntimeError, match="process main thread"):
        with gate._repair_wall_clock_deadline(1):
            pass
    assert signal.getitimer(signal.ITIMER_REAL)[0] == 0


def test_repair_unexpected_runtime_failure_preserves_initial_model_evidence(monkeypatch) -> None:
    """Unexpected corrective parser/runtime failures keep the first trusted diagnostic."""
    import json

    monkeypatch.setenv("NOEMA_LLM_API_URL", "https://llm.example/v1/chat/completions")
    monkeypatch.setenv("NOEMA_LLM_API_KEY", "test-key")
    head_sha = "e" * 40

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return json.dumps(
                {"choices": [{"message": {"content": json.dumps(_verdict())}}]}
            ).encode()

    monkeypatch.setattr(
        gate.urllib.request.OpenerDirector,
        "open",
        lambda *_args, **_kwargs: Response(),
    )
    monkeypatch.setattr(gate, "fetch_pr", lambda _repo, _number: {"headRefOid": head_sha})
    original_decode = gate.decode_llm_response_body
    decode_calls = 0

    def decode_once_then_fail(raw_bytes):
        nonlocal decode_calls
        decode_calls += 1
        if decode_calls == 2:
            raise RuntimeError("repair parser invariant failed")
        return original_decode(raw_bytes)

    monkeypatch.setattr(gate, "decode_llm_response_body", decode_once_then_fail)

    with pytest.raises(RuntimeError) as exc_info:
        gate.call_llm(
            "owner/repo",
            7,
            {"title": "test", "headRefOid": head_sha},
            DIFF,
            False,
            head_sha,
            changed_paths=("README.md",),
        )

    message = str(exc_info.value)
    assert "Noema repair failed closed" in message
    assert "outcome must be falsified or confirmed" in message
    assert "repair parser invariant failed" in message
    assert decode_calls == 2



def test_unparseable_diff_remains_source_evidence() -> None:
    """A location-free trusted diff is not retyped as model-output failure."""
    with pytest.raises(RuntimeError) as exc_info:
        gate.validate_substantive_verdict(_verdict(), "not a unified diff", ["README.md"])
    assert not isinstance(exc_info.value, gate.NoemaModelOutputError)
    assert "parseable changed-line evidence" in str(exc_info.value)


def test_model_sentinel_never_reaches_repair_prompt_or_final_diagnostic(monkeypatch) -> None:
    """Model-controlled invalid values are redacted while the defect class stays actionable."""
    import json

    sentinel = "MODEL_SENTINEL_DO_NOT_REFLECT"
    monkeypatch.setenv("NOEMA_LLM_API_URL", "https://llm.example/v1/chat/completions")
    monkeypatch.setenv("NOEMA_LLM_API_KEY", "test-key")
    head_sha = "e" * 40
    requests = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return json.dumps(
                {"choices": [{"message": {"content": json.dumps({"decision": sentinel})}}]}
            ).encode()

    def open_response(_opener, request, **kwargs):
        assert kwargs == {}
        requests.append(request)
        return Response()

    monkeypatch.setattr(gate.urllib.request.OpenerDirector, "open", open_response)
    monkeypatch.setattr(gate, "fetch_pr", lambda _repo, _number: {"headRefOid": head_sha})

    with pytest.raises(gate.NoemaModelOutputError) as exc_info:
        gate.call_llm(
            "owner/repo",
            7,
            {"title": "test", "headRefOid": head_sha},
            DIFF,
            False,
            head_sha,
            changed_paths=("README.md",),
        )

    assert len(requests) == 2
    repair_payload = requests[1].data.decode("utf-8")
    assert sentinel not in repair_payload
    assert "Noema LLM returned unsupported decision" in repair_payload
    assert sentinel not in str(exc_info.value)
    assert "Noema LLM returned unsupported decision" in str(exc_info.value)
    assert exc_info.value.__cause__ is None


def test_stable_failure_diagnostic_preserves_trusted_structure_and_redacts_values() -> None:
    """Trusted validator detail stays actionable; arbitrary model text stays opaque."""
    trusted = gate.NoemaModelOutputError(
        "Noema adversarial probe 1 outcome must be falsified or confirmed"
    )
    assert gate._stable_failure_diagnostic(trusted) == str(trusted)
    request_changes = gate.NoemaModelOutputError(
        "Noema LLM request_changes response did not contain a substantive finding"
    )
    assert gate._stable_failure_diagnostic(request_changes) == str(request_changes)
    assert gate._stable_failure_diagnostic(
        gate.NoemaModelOutputError("Noema LLM returned unsupported decision: 'SECRET_VALUE'")
    ) == "Noema LLM returned unsupported decision"
    assert gate._stable_failure_diagnostic(
        gate.NoemaModelOutputError("secret-ish model text")
    ) == "model-output-contract-invalid"
    assert gate._stable_failure_diagnostic(TimeoutError()) == "TimeoutError"


def test_repair_deadline_rejects_nonpositive_budget() -> None:
    with pytest.raises(ValueError, match="must be positive"):
        with gate._repair_wall_clock_deadline(0):
            pass


def test_repair_deadline_requires_setitimer(monkeypatch) -> None:
    monkeypatch.delattr(gate.signal, "setitimer")
    with pytest.raises(RuntimeError, match="requires POSIX"):
        with gate._repair_wall_clock_deadline(1):
            pass


def test_repair_deadline_requires_itimer_real(monkeypatch) -> None:
    monkeypatch.delattr(gate.signal, "ITIMER_REAL")
    with pytest.raises(RuntimeError, match="requires POSIX"):
        with gate._repair_wall_clock_deadline(1):
            pass


@pytest.mark.parametrize("timer_state", [(1.0, 0.0), (0.0, 1.0)])
def test_repair_deadline_refuses_existing_process_alarm(monkeypatch, timer_state) -> None:
    monkeypatch.setattr(gate.signal, "getitimer", lambda _which: timer_state)
    with pytest.raises(RuntimeError, match="active process alarm"):
        with gate._repair_wall_clock_deadline(1):
            pass


def test_repair_deadline_requires_main_thread_signal_registration(monkeypatch) -> None:
    monkeypatch.setattr(gate.signal, "getitimer", lambda _which: (0.0, 0.0))

    def reject_signal(*_args):
        raise ValueError("signal only works in main thread")

    monkeypatch.setattr(gate.signal, "signal", reject_signal)
    with pytest.raises(RuntimeError, match="process main thread"):
        with gate._repair_wall_clock_deadline(1):
            pass
