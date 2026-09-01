#!/usr/bin/env python3
"""Add fail-closed coverage for PR #1617's temporary production transform.

This one-shot helper is removed by the repair workflow before the verified
production commit is created.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TEST = ROOT / "tests/test_noema_model_output_failure_classification.py"


def main() -> None:
    text = TEST.read_text(encoding="utf-8")
    marker = "def test_repair_wall_clock_deadline_defensive_fail_closed_paths"
    if marker in text:
        raise RuntimeError("#1617 deadline coverage regressions already present")
    text += r'''


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
'''
    TEST.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
