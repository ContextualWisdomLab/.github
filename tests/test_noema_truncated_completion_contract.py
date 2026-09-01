"""Regression contract for bounded Noema structured completions."""

from __future__ import annotations

import json
from typing import Any

import pytest

from scripts.ci import noema_review_gate as noema


HEAD = "a" * 40


def _pr() -> dict[str, Any]:
    """Return the minimal immutable PR identity required by ``call_llm``."""
    return {"title": "bounded completion", "headRefOid": HEAD}


def _envelope(content: str, finish_reason: Any, *, model: Any = "provider/model") -> bytes:
    """Build one OpenAI-compatible envelope for the fake sidecar."""
    return json.dumps(
        {
            "model": model,
            "usage": {"prompt_tokens": 21, "completion_tokens": 34},
            "choices": [
                {
                    "finish_reason": finish_reason,
                    "message": {"content": content},
                }
            ],
        }
    ).encode("utf-8")


class _Response:
    """Expose one deterministic byte response through the urllib context API."""

    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args: object) -> bool:
        return False

    def read(self) -> bytes:
        return self.body


class _Opener:
    """Capture requests while returning a finite sequence of fake replies."""

    def __init__(self, bodies: list[bytes]) -> None:
        self.bodies = iter(bodies)
        self.requests: list[Any] = []

    def open(self, request: Any) -> _Response:
        self.requests.append(request)
        return _Response(next(self.bodies))


def _configure(monkeypatch: pytest.MonkeyPatch, opener: _Opener) -> None:
    """Bind ``call_llm`` to a deterministic public-style fake endpoint."""
    monkeypatch.setenv(
        "NOEMA_LLM_API_URL", "https://llm.example/v1/chat/completions"
    )
    monkeypatch.setenv("NOEMA_LLM_API_KEY", "test-key")
    monkeypatch.setattr(noema.urllib.request, "build_opener", lambda *_args: opener)
    monkeypatch.setattr(noema, "fetch_pr", lambda _repo, _number: _pr())


def test_completion_envelope_preserves_bounded_finish_and_usage_metadata() -> None:
    """The consumer must retain the provider's termination and token evidence."""
    completion = noema.extract_llm_completion(
        _envelope('{"decision":"comment"}', "stop").decode("utf-8")
    )

    assert completion.content == '{"decision":"comment"}'
    assert completion.finish_reason == "stop"
    assert completion.model == "provider/model"
    assert completion.prompt_tokens == 21
    assert completion.completion_tokens == 34


def test_call_llm_retries_length_with_explicit_json_output_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A declared length stop gets one compact retry under an explicit budget."""
    recovered = json.dumps(
        {"decision": "comment", "summary": "Recovered.", "findings": []}
    )
    opener = _Opener(
        [
            _envelope('{"decision":"comment","summary":"cut', "length"),
            _envelope(recovered, "stop"),
        ]
    )
    _configure(monkeypatch, opener)

    verdict = noema.call_llm(
        "owner/repo", 7, _pr(), "diff", False, HEAD, "bounded context"
    )

    assert verdict["summary"] == "Recovered."
    assert len(opener.requests) == 2
    first_payload = json.loads(opener.requests[0].data)
    retry_payload = json.loads(opener.requests[1].data)
    for payload in (first_payload, retry_payload):
        assert payload["max_completion_tokens"] == noema.NOEMA_LLM_MAX_COMPLETION_TOKENS
        assert payload["response_format"] == {"type": "json_object"}
    assert "smallest complete JSON verdict" in retry_payload["messages"][1]["content"]


def test_call_llm_types_repeated_length_as_truncated_after_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Repeated provider-declared truncation must fail closed with its own type."""
    opener = _Opener(
        [
            _envelope('{"decision":"comment"', "length"),
            _envelope('{"decision":"comment"', "length"),
        ]
    )
    _configure(monkeypatch, opener)

    with pytest.raises(RuntimeError, match="truncated_after_retry"):
        noema.call_llm("owner/repo", 7, _pr(), "diff", False, HEAD)

    assert len(opener.requests) == 2


def test_call_llm_types_repeated_malformed_json_as_invalid_after_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Repeated malformed content stays distinct from a declared length stop."""
    opener = _Opener(
        [
            _envelope('{"decision":"comment"', "stop"),
            _envelope('{"decision":"comment"', "stop"),
        ]
    )
    _configure(monkeypatch, opener)

    with pytest.raises(RuntimeError, match="invalid_json_after_retry"):
        noema.call_llm("owner/repo", 7, _pr(), "diff", False, HEAD)

    assert len(opener.requests) == 2


def test_completion_envelope_rejects_unbounded_or_wrong_typed_metadata() -> None:
    """Provider metadata cannot become an unbounded public diagnostic channel."""
    too_long_reason = "x" * 65
    with pytest.raises(RuntimeError, match="finish_reason"):
        noema.extract_llm_completion(
            _envelope("{}", too_long_reason).decode("utf-8")
        )
    with pytest.raises(RuntimeError, match="model"):
        noema.extract_llm_completion(
            _envelope("{}", "stop", model={"unexpected": "object"}).decode("utf-8")
        )


def test_verdict_output_cardinality_and_text_are_bounded() -> None:
    """The validator prevents a structurally valid verdict from growing forever."""
    with pytest.raises(RuntimeError, match="summary exceeds"):
        noema.validate_verdict_output_bounds(
            {
                "summary": "x" * (noema.NOEMA_MAX_VERDICT_TEXT_CHARS + 1),
                "findings": [],
            }
        )
    with pytest.raises(RuntimeError, match="findings exceeds"):
        noema.validate_verdict_output_bounds(
            {
                "summary": "ok",
                "findings": [
                    {
                        "severity": "low",
                        "file": "a.py",
                        "line": 1,
                        "side": "RIGHT",
                        "message": "bounded",
                    }
                    for _ in range(noema.NOEMA_MAX_FINDINGS + 1)
                ],
            }
        )
