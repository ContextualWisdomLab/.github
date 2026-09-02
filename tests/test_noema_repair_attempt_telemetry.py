"""Regression coverage for Noema repair-path telemetry.

Owner complaint (2026-09-02, `html4tree` run 33560972491, job 100033086428):
a Noema repair-deadline failure gave no diagnostic detail beyond "exceeded
900-second absolute wall-clock deadline" -- no attempt count, no duration
breakdown, no indication of which sub-phase (connect/read/decode/validate)
the one bounded repair attempt was in when the deadline fired, and no record
of which ``orchestrator/free`` candidate served (or was attempted for) a
call. See ``docs/doctoring/noema-repair-attempt-telemetry.md`` for the full
incident and reasoning trail this test file backs.

These tests never make a real network call (per this repo's convention):
every HTTP interaction is monkeypatched at ``urllib.request.OpenerDirector.open``.
"""

import json
import signal
import time

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


def _comment_verdict() -> dict:
    """Return a minimal always-valid verdict (decision=comment needs no probes)."""
    return {"decision": "comment", "summary": "Looks fine.", "findings": []}


def _malformed_probe_verdict() -> dict:
    """Return a schema-valid JSON envelope with an out-of-domain probe outcome.

    Same real #1611 failure shape used by
    ``test_noema_model_output_failure_classification.py``: it passes JSON
    decoding but fails the deterministic ``validate_substantive_verdict``
    check, which is exactly the malformed-then-repair path this module logs
    telemetry for.
    """
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
                    "outcome": "passed",  # invalid: must be falsified|confirmed
                }
            ],
        },
        "findings": [],
    }


class _JsonResponse:
    """Minimal context-manager stand-in for ``http.client.HTTPResponse``."""

    def __init__(self, body: dict):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        return json.dumps(self._body).encode()


def test_response_format_is_the_openai_structured_output_envelope_on_every_call(monkeypatch):
    """Both the primary and the repair call declare the OpenAI json_schema envelope.

    contextual-orchestrator's ``orchestrator/free`` sidecar is a proven
    OpenAI-compatible endpoint (ADR-0003), so the outer envelope must be
    OpenAI's own ``response_format`` wrapping convention, not bare JSON
    Schema. This does not implement any gateway-owned candidate-selection or
    retry policy (PR #1602); it only declares what shape the caller wants.
    """
    monkeypatch.setenv("NOEMA_LLM_API_URL", "https://llm.example/v1/chat/completions")
    monkeypatch.setenv("NOEMA_LLM_API_KEY", "test-key")
    head_sha = "a" * 40
    requests: list[object] = []

    def open_response(_opener, request, **_kwargs):
        requests.append(request)
        if len(requests) == 1:
            return _JsonResponse(
                {"choices": [{"message": {"content": json.dumps(_malformed_probe_verdict())}}]}
            )
        return _JsonResponse(
            {"choices": [{"message": {"content": json.dumps(_comment_verdict())}}]}
        )

    monkeypatch.setattr(gate.urllib.request.OpenerDirector, "open", open_response)
    monkeypatch.setattr(gate, "fetch_pr", lambda _repo, _number: {"headRefOid": head_sha})

    verdict = gate.call_llm(
        "owner/repo", 7, {"title": "test", "headRefOid": head_sha}, DIFF, False, head_sha,
        changed_paths=("README.md",),
    )

    assert verdict == _comment_verdict()
    assert len(requests) == 2
    for request in requests:
        payload = json.loads(request.data)
        assert payload["response_format"] == gate.NOEMA_VERDICT_RESPONSE_FORMAT
    schema = gate.NOEMA_VERDICT_RESPONSE_FORMAT["json_schema"]
    assert schema["strict"] is True
    assert gate.NOEMA_VERDICT_RESPONSE_FORMAT["type"] == "json_schema"
    assert set(schema["schema"]["required"]) == {
        "decision", "summary", "reviewed_lines", "adversarial_validation", "findings",
    }


def test_served_model_telemetry_reads_envelope_model_field_when_present(monkeypatch, capsys):
    """A successful attempt logs which candidate model served it."""
    monkeypatch.setenv("NOEMA_LLM_API_URL", "https://llm.example/v1/chat/completions")
    monkeypatch.setenv("NOEMA_LLM_API_KEY", "test-key")
    head_sha = "b" * 40

    monkeypatch.setattr(
        gate.urllib.request.OpenerDirector,
        "open",
        lambda *_a, **_k: _JsonResponse(
            {
                "model": "some-provider/some-model-v1",
                "choices": [{"message": {"content": json.dumps(_comment_verdict())}}],
            }
        ),
    )

    verdict = gate.call_llm(
        "owner/repo", 7, {"title": "test", "headRefOid": head_sha}, DIFF, False, head_sha,
        changed_paths=("README.md",),
    )

    assert verdict == _comment_verdict()
    notice = capsys.readouterr().out
    assert "::notice::Noema primary attempt outcome=success" in notice
    assert "served_model=some-provider/some-model-v1" in notice


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('{"model": "provider/model-x", "choices": []}', "provider/model-x"),
        ('{"choices": []}', None),
        ('{"model": "", "choices": []}', None),
        ('{"model": 5, "choices": []}', None),
        ("not json at all", None),
        ("[]", None),
    ],
)
def test_extract_served_model_is_best_effort_and_never_raises(raw, expected):
    """``_extract_served_model`` only reads a real, non-empty string field."""
    assert gate._extract_served_model(raw) == expected


def test_extract_served_model_scrubs_and_bounds_the_value():
    """The served-model field is untrusted gateway/model output and is scrubbed."""
    raw = json.dumps({"model": "bearer abc123 " + "x" * 500, "choices": []})
    served = gate._extract_served_model(raw)
    assert served is not None
    assert "abc123" not in served
    assert len(served) <= 200


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (gate.NoemaRepairDeadlineExceeded("exceeded"), "deadline_exceeded"),
        (gate.NoemaModelOutputError("bad"), "malformed_output"),
        (gate.NoemaTransportError("bad transport"), "runtime_error"),
        (RuntimeError("unexpected"), "runtime_error"),
    ],
)
def test_classify_attempt_outcome_orders_deadline_before_transport(exc, expected):
    """Deadline-exceeded must not misreport as a generic transport error.

    ``NoemaRepairDeadlineExceeded`` is itself an ``OSError``/``TimeoutError``
    subclass, so the classifier must check it before the broader transport
    class or the one distinction the original bare timeout message could
    not make (deadline vs. ordinary transport failure) would be lost again.
    """
    assert gate._classify_attempt_outcome(exc) == expected


def test_classify_attempt_outcome_detects_transport_family():
    import http.client
    import urllib.error

    assert gate._classify_attempt_outcome(urllib.error.URLError("boom")) == "transport_error"
    assert (
        gate._classify_attempt_outcome(http.client.HTTPException("boom"))
        == "transport_error"
    )
    assert gate._classify_attempt_outcome(OSError("boom")) == "transport_error"


def test_repair_deadline_exceeded_emits_full_attempt_breakdown(monkeypatch, capsys):
    """The owner's exact complaint: a deadline failure must explain itself.

    Reproduces the `html4tree` run 33560972491 / job 100033086428 shape --
    malformed primary JSON, then a repair attempt that runs past its
    wall-clock budget -- and asserts the failure now carries an attempt
    count, a duration, and the furthest phase reached, plus a matching
    ``::notice::``/``::warning::`` pair a human can read straight from the
    public Actions log without re-running anything.
    """
    if not hasattr(signal, "setitimer"):
        pytest.skip("POSIX process timer is required by the Linux review runner")

    monkeypatch.setenv("NOEMA_LLM_API_URL", "https://llm.example/v1/chat/completions")
    monkeypatch.setenv("NOEMA_LLM_API_KEY", "test-key")
    monkeypatch.setattr(gate, "NOEMA_REPAIR_DEADLINE_SECONDS", 0.05)
    head_sha = "d" * 40
    calls = 0

    class SlowRepairResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            time.sleep(2)
            return b"{}"

    def open_response(_opener, _request, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return _JsonResponse(
                {"choices": [{"message": {"content": json.dumps(_malformed_probe_verdict())}}]}
            )
        return SlowRepairResponse()

    monkeypatch.setattr(gate.urllib.request.OpenerDirector, "open", open_response)
    monkeypatch.setattr(gate, "fetch_pr", lambda _repo, _number: {"headRefOid": head_sha})

    with pytest.raises(gate.NoemaTransportError) as exc_info:
        gate.call_llm(
            "owner/repo", 7, {"title": "test", "headRefOid": head_sha}, DIFF, False, head_sha,
            changed_paths=("README.md",),
        )

    message = str(exc_info.value)
    assert "NoemaRepairDeadlineExceeded" in message
    assert "repair attempts=1" in message
    assert "repair duration=" in message
    assert "phase=reading" in message
    assert calls == 2

    captured = capsys.readouterr().out
    assert "::notice::Noema primary attempt outcome=malformed_output" in captured
    assert "starting one bounded repair attempt" in captured
    assert "::warning::Noema repair attempt outcome=deadline_exceeded" in captured
    assert "phase=reading" in captured
    assert "served_model=unknown" in captured
    assert "not a retry loop" in captured


def test_strip_trailing_commas_outside_strings_is_lossless_and_string_safe():
    """The trailing-comma fixer only removes a comma directly before a closer.

    A comma that is genuine string content (inside quotes) is never touched,
    proven here by a value that itself contains ``,}`` as literal text.
    """
    fixed = gate._strip_trailing_commas_outside_strings('{"a": 1, "b": [1, 2,], },')
    assert fixed == '{"a": 1, "b": [1, 2] },'
    assert json.loads(fixed.rstrip(",")) == {"a": 1, "b": [1, 2]}

    untouched = '{"note": "trailing ,} inside a string"}'
    assert gate._strip_trailing_commas_outside_strings(untouched) == untouched

    # An escaped quote inside a string must not end the string early, so a
    # ",}" that follows it (but is still inside the string) stays untouched.
    escaped = '{"note": "an escaped quote \\" then ,} still inside"}'
    assert gate._strip_trailing_commas_outside_strings(escaped) == escaped


def test_extract_json_object_recovers_a_trailing_comma_response(capsys):
    """A trailing-comma-malformed verdict recovers locally, no network retry needed."""
    malformed = '{"decision":"comment","summary":"ok","findings":[],}'
    with pytest.raises(gate.NoemaModelOutputError):
        gate._extract_json_object_once(malformed)

    verdict = gate.extract_json_object(malformed)
    assert verdict == {"decision": "comment", "summary": "ok", "findings": []}
    notice = capsys.readouterr().out
    assert "::notice::Noema local trailing-comma JSON repair recovered" in notice
    assert "no network repair retry was needed" in notice


def test_extract_json_object_does_not_guess_repair_other_malformations(capsys):
    """Only the trailing-comma class is repaired; other malformed JSON still fails closed."""
    unquoted_key = '{"decision":"approve", trailing garbage not: "quoted}'
    with pytest.raises(gate.NoemaModelOutputError, match="was not valid JSON"):
        gate.extract_json_object(unquoted_key)
    assert "::notice::" not in capsys.readouterr().out


def test_successful_repair_attempt_logs_success_with_served_model(monkeypatch, capsys):
    """A repair attempt that succeeds still gets one success telemetry line."""
    monkeypatch.setenv("NOEMA_LLM_API_URL", "https://llm.example/v1/chat/completions")
    monkeypatch.setenv("NOEMA_LLM_API_KEY", "test-key")
    head_sha = "c" * 40
    calls = 0

    def open_response(_opener, _request, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return _JsonResponse(
                {"choices": [{"message": {"content": json.dumps(_malformed_probe_verdict())}}]}
            )
        return _JsonResponse(
            {
                "model": "repair-candidate/model-y",
                "choices": [{"message": {"content": json.dumps(_comment_verdict())}}],
            }
        )

    monkeypatch.setattr(gate.urllib.request.OpenerDirector, "open", open_response)
    monkeypatch.setattr(gate, "fetch_pr", lambda _repo, _number: {"headRefOid": head_sha})

    verdict = gate.call_llm(
        "owner/repo", 7, {"title": "test", "headRefOid": head_sha}, DIFF, False, head_sha,
        changed_paths=("README.md",),
    )

    assert verdict == _comment_verdict()
    assert calls == 2
    captured = capsys.readouterr().out
    assert "::notice::Noema repair attempt outcome=success" in captured
    assert "served_model=repair-candidate/model-y" in captured
