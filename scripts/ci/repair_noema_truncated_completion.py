#!/usr/bin/env python3
"""Apply the test-first repair for truncated Noema completion envelopes.

This temporary branch writer creates the regression contract first, then
transforms the protected-main reviewer without embedding untrusted model text
in diagnostics. The file removes itself from the final repair commit.
"""

from __future__ import annotations

import argparse
from pathlib import Path


SOURCE_PATH = Path("scripts/ci/noema_review_gate.py")
TEST_PATH = Path("tests/test_noema_truncated_completion_contract.py")
CHANGELOG_PATH = Path("CHANGELOG.md")


TEST_SOURCE = r'''"""Regression contract for bounded Noema structured completions."""

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
'''


def replace_once(text: str, old: str, new: str, label: str) -> str:
    """Replace one exact anchor and fail before corrupting an unexpected tree."""
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def write_tests() -> None:
    """Write the RED regression file without changing production code."""
    if TEST_PATH.exists():
        raise SystemExit(f"{TEST_PATH} already exists")
    TEST_PATH.write_text(TEST_SOURCE, encoding="utf-8")


def apply_source_repair() -> None:
    """Transform the protected-main Noema client and update its changelog."""
    text = SOURCE_PATH.read_text(encoding="utf-8")

    text = replace_once(
        text,
        "from collections.abc import Sequence\nfrom typing import Any\n",
        "from collections.abc import Sequence\nfrom dataclasses import dataclass\nfrom typing import Any\n",
        "dataclass import",
    )

    constant_anchor = "MAX_THREAD_BODY_CHARS = 1200\n"
    constants = """MAX_THREAD_BODY_CHARS = 1200
NOEMA_LLM_MAX_COMPLETION_TOKENS = 4096
NOEMA_MAX_VERDICT_TEXT_CHARS = 600
NOEMA_MAX_REVIEWED_LINES = 6
NOEMA_MAX_ADVERSARIAL_PROBES = 4
NOEMA_MAX_FINDINGS = 5
NOEMA_MAX_CLASS_EVIDENCE_FIELDS = 6
NOEMA_MAX_CLASS_EVIDENCE_CHARS = 400
"""
    text = replace_once(text, constant_anchor, constants, "completion constants")

    parser_start = text.index("def extract_llm_message_content(raw: str) -> str:\n")
    parser_end = text.index("\n\ndef decode_llm_response_body", parser_start)
    parser = r'''def _bounded_token_count(value: Any, field: str) -> int | None:
    """Validate one optional usage count without retaining an unbounded value.

    Provider usage metadata is safe to retain for diagnosis only while it is a
    non-negative integer within a deliberately generous operational ceiling.
    """

    if value is None:
        return None
    if type(value) is not int or value < 0 or value > 1_048_576_000:
        raise RuntimeError(
            f"Noema LLM response usage.{field} was not a bounded non-negative integer"
        )
    return value


def extract_llm_completion(raw: str) -> LLMCompletion:
    """Parse one OpenAI-compatible completion and retain bounded metadata.

    Raw model content remains in memory and is never copied into diagnostics.
    Only the normalized finish reason, bounded model identifier, and token
    counts are retained beside the content so truncation is distinguishable
    from arbitrary malformed JSON.
    """

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Noema LLM response body was not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(
            f"Noema LLM response body was not a JSON object (got {type(data).__name__})"
        )

    choices = data.get("choices")
    if not choices:
        choices = [{}]
    elif not isinstance(choices, list):
        raise RuntimeError(
            f"Noema LLM response 'choices' was not a list (got {type(choices).__name__})"
        )
    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        raise RuntimeError(
            "Noema LLM response choices[0] was not a JSON object "
            f"(got {type(first_choice).__name__})"
        )

    message = first_choice.get("message")
    if not message:
        message = {}
    elif not isinstance(message, dict):
        raise RuntimeError(
            f"Noema LLM response 'message' was not a JSON object (got {type(message).__name__})"
        )
    content = message.get("content")
    if not content:
        content = ""
    elif not isinstance(content, str):
        raise RuntimeError(
            f"Noema LLM response 'content' was not a string (got {type(content).__name__})"
        )

    finish_reason_value = first_choice.get("finish_reason")
    if finish_reason_value is None:
        finish_reason = ""
    elif not isinstance(finish_reason_value, str):
        raise RuntimeError("Noema LLM response finish_reason was not a string")
    else:
        finish_reason = finish_reason_value.strip().lower()
        if len(finish_reason) > 64 or not re.fullmatch(r"[a-z0-9_-]*", finish_reason):
            raise RuntimeError("Noema LLM response finish_reason was malformed")

    model_value = data.get("model")
    if model_value is None:
        model = ""
    elif not isinstance(model_value, str):
        raise RuntimeError("Noema LLM response model metadata was not a string")
    else:
        model = model_value.strip()
        if len(model) > 256 or any(ord(character) < 32 for character in model):
            raise RuntimeError("Noema LLM response model metadata was malformed")

    usage_value = data.get("usage")
    if usage_value is None:
        usage: dict[str, Any] = {}
    elif not isinstance(usage_value, dict):
        raise RuntimeError("Noema LLM response usage metadata was not an object")
    else:
        usage = usage_value

    prompt_tokens = _bounded_token_count(
        usage.get("prompt_tokens", usage.get("input_tokens")), "prompt_tokens"
    )
    completion_tokens = _bounded_token_count(
        usage.get("completion_tokens", usage.get("output_tokens")),
        "completion_tokens",
    )
    return LLMCompletion(
        content=content.strip(),
        finish_reason=finish_reason,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )


def extract_llm_message_content(raw: str) -> str:
    """Return content from a validated completion envelope.

    This compatibility wrapper keeps the older direct parser contract while
    ``call_llm`` consumes the richer completion metadata.
    """

    return extract_llm_completion(raw).content
'''
    text = text[:parser_start] + parser + text[parser_end:]

    class_anchor = '''class StaleHeadDuringRepairRetryError(RuntimeError):
    """Raised when the PR head moves before ``call_llm``'s repair-retry request fires."""


def call_llm(
'''
    classes_and_bounds = '''class StaleHeadDuringRepairRetryError(RuntimeError):
    """Signal that the reviewed head moved before a bounded repair request."""


class TruncatedCompletionError(RuntimeError):
    """Signal a provider-declared output-budget termination.

    The exception contains no model content and therefore remains safe in the
    public ``pull_request_target`` workflow log.
    """


class InvalidCompletionError(RuntimeError):
    """Signal an unusable structured-completion envelope or JSON payload.

    This type separates arbitrary malformed output from a provider-declared
    ``finish_reason=length`` response.
    """


@dataclass(frozen=True)
class LLMCompletion:
    """Store validated content and bounded provider completion metadata.

    Model output is retained only in ``content`` for immediate validation; no
    formatter or diagnostic emits it.
    """

    content: str
    finish_reason: str
    model: str
    prompt_tokens: int | None
    completion_tokens: int | None


def _bounded_text(value: Any, label: str, limit: int) -> None:
    """Reject a present text field that exceeds the declared output budget."""
    if isinstance(value, str) and len(value) > limit:
        raise RuntimeError(f"Noema LLM response {label} exceeds {limit} characters")


def _bounded_list(value: Any, label: str, limit: int) -> list[Any]:
    """Return an optional list after enforcing type and cardinality bounds."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise RuntimeError(f"Noema LLM response {label} must be a list")
    if len(value) > limit:
        raise RuntimeError(f"Noema LLM response {label} exceeds {limit} items")
    return value


def validate_verdict_output_bounds(verdict: dict[str, Any]) -> None:
    """Enforce compact cardinality and text limits on a decoded verdict.

    The schema still permits substantive exact-line evidence, but it cannot
    consume an unbounded completion or later inflate a GitHub review body.
    """

    _bounded_text(
        verdict.get("summary"), "summary", NOEMA_MAX_VERDICT_TEXT_CHARS
    )

    reviewed_lines = _bounded_list(
        verdict.get("reviewed_lines"), "reviewed_lines", NOEMA_MAX_REVIEWED_LINES
    )
    for reviewed in reviewed_lines:
        if isinstance(reviewed, dict):
            _bounded_text(
                reviewed.get("analysis"),
                "reviewed_lines.analysis",
                NOEMA_MAX_VERDICT_TEXT_CHARS,
            )

    validation = verdict.get("adversarial_validation")
    if validation is not None and not isinstance(validation, dict):
        raise RuntimeError("Noema LLM response adversarial_validation must be an object")
    if isinstance(validation, dict):
        _bounded_text(
            validation.get("residual_risk"),
            "adversarial_validation.residual_risk",
            NOEMA_MAX_VERDICT_TEXT_CHARS,
        )
        probes = _bounded_list(
            validation.get("probes"),
            "adversarial_validation.probes",
            NOEMA_MAX_ADVERSARIAL_PROBES,
        )
        for probe in probes:
            if not isinstance(probe, dict):
                continue
            for field in ("hypothesis", "attack_or_counterexample", "evidence"):
                _bounded_text(
                    probe.get(field),
                    f"adversarial_validation.probes.{field}",
                    NOEMA_MAX_VERDICT_TEXT_CHARS,
                )
            class_evidence = probe.get("class_evidence")
            if class_evidence is None:
                continue
            if not isinstance(class_evidence, dict):
                raise RuntimeError(
                    "Noema LLM response adversarial probe class_evidence must be an object"
                )
            if len(class_evidence) > NOEMA_MAX_CLASS_EVIDENCE_FIELDS:
                raise RuntimeError(
                    "Noema LLM response adversarial probe class_evidence "
                    f"exceeds {NOEMA_MAX_CLASS_EVIDENCE_FIELDS} fields"
                )
            for value in class_evidence.values():
                _bounded_text(
                    value,
                    "adversarial_validation.probes.class_evidence",
                    NOEMA_MAX_CLASS_EVIDENCE_CHARS,
                )

    findings = _bounded_list(
        verdict.get("findings"), "findings", NOEMA_MAX_FINDINGS
    )
    for finding in findings:
        if isinstance(finding, dict):
            _bounded_text(
                finding.get("message"),
                "findings.message",
                NOEMA_MAX_VERDICT_TEXT_CHARS,
            )


def call_llm(
'''
    text = replace_once(
        text, class_anchor, classes_and_bounds, "completion classes and bounds"
    )

    prompt_anchor = (
        '                "Use request_changes only for blocking, concrete issues. '
        'A generic no-issues statement is not review evidence.",\n'
    )
    prompt_replacement = prompt_anchor + (
        '                "Keep the JSON compact: summary, reviewed-line analysis, '
        'probe hypothesis/attack/evidence, residual risk, and finding messages '
        'must each stay within 600 characters; use at most 6 reviewed_lines, '
        '4 probes, and 5 findings.",\n'
    )
    text = replace_once(
        text, prompt_anchor, prompt_replacement, "bounded prompt instruction"
    )

    retry_anchor = (
        '                        "Return one corrected JSON verdict using only exact '
        'changed-side locations from the supplied diff.",\n'
    )
    retry_replacement = retry_anchor + (
        '                        "Repair mode: emit the smallest complete JSON verdict '
        'that satisfies the schema; prefer one reviewed line, the minimum required '
        'probes, and no nonblocking findings.",\n'
    )
    text = replace_once(
        text, retry_anchor, retry_replacement, "compact retry instruction"
    )

    payload_anchor = '''    payload = {
        "model": model,
        "temperature": 0,
        "messages": [
'''
    payload_replacement = '''    payload = {
        "model": model,
        "temperature": 0,
        "max_completion_tokens": NOEMA_LLM_MAX_COMPLETION_TOKENS,
        "response_format": {"type": "json_object"},
        "messages": [
'''
    text = replace_once(
        text, payload_anchor, payload_replacement, "bounded completion payload"
    )

    extraction_anchor = '''        raw = decode_llm_response_body(raw_bytes)
        content = extract_llm_message_content(raw)
        verdict = extract_json_object(content)
'''
    extraction_replacement = '''        raw = decode_llm_response_body(raw_bytes)
        try:
            completion = extract_llm_completion(raw)
        except RuntimeError as exc:
            raise InvalidCompletionError(str(exc)) from exc
        if completion.finish_reason == "length":
            raise TruncatedCompletionError(
                "Noema LLM completion ended with finish_reason=length"
            )
        if completion.finish_reason not in {"", "stop"}:
            raise InvalidCompletionError(
                "Noema LLM completion ended with an unsupported finish reason"
            )
        try:
            verdict = extract_json_object(completion.content)
        except RuntimeError as exc:
            raise InvalidCompletionError(str(exc)) from exc
'''
    text = replace_once(
        text, extraction_anchor, extraction_replacement, "completion extraction"
    )

    validate_anchor = "        validate_substantive_verdict(verdict, diff, changed_paths)\n"
    validate_replacement = (
        "        validate_verdict_output_bounds(verdict)\n"
        + validate_anchor
    )
    text = replace_once(
        text, validate_anchor, validate_replacement, "verdict output bounds"
    )

    retry_exception_anchor = '''        if is_retry:
            if isinstance(exc, RuntimeError):
                raise
            raise RuntimeError(str(exc)) from exc
'''
    retry_exception_replacement = '''        if is_retry:
            if isinstance(exc, TruncatedCompletionError):
                raise RuntimeError(
                    "Noema LLM response truncated_after_retry: "
                    "the provider again ended the structured completion at its output limit"
                ) from exc
            if isinstance(exc, InvalidCompletionError):
                raise RuntimeError(
                    f"Noema LLM response invalid_json_after_retry: {exc}"
                ) from exc
            if isinstance(exc, RuntimeError):
                raise
            raise RuntimeError(str(exc)) from exc
'''
    text = replace_once(
        text,
        retry_exception_anchor,
        retry_exception_replacement,
        "typed exhausted retry",
    )

    SOURCE_PATH.write_text(text, encoding="utf-8")

    changelog = CHANGELOG_PATH.read_text(encoding="utf-8")
    changelog_anchor = "## [Unreleased]\n"
    changelog_entry = """## [Unreleased]
- **Recover Noema from provider-truncated structured review completions (`#1596`).**
  The review client now retains bounded `finish_reason`, model, and token-usage
  metadata from the OpenAI-compatible envelope, requests JSON mode with an
  explicit 4,096-token output budget through Contextual Orchestrator, and
  constrains verdict cardinality and field lengths. A provider-declared
  `finish_reason=length` receives one compact exact-head repair request; a
  repeated length stop fails closed as `truncated_after_retry`, distinct from
  `invalid_json_after_retry`. Raw model output remains absent from public logs.
"""
    changelog = replace_once(
        changelog, changelog_anchor, changelog_entry, "changelog unreleased"
    )
    CHANGELOG_PATH.write_text(changelog, encoding="utf-8")


def main() -> int:
    """Run the selected deterministic phase."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-tests", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.write_tests == args.apply:
        parser.error("choose exactly one of --write-tests or --apply")
    if args.write_tests:
        write_tests()
    else:
        apply_source_repair()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
