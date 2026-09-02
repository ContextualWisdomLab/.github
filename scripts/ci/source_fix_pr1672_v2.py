#!/usr/bin/env python3
"""Materialize PR #1672 single-request ownership and replace stale retry regressions."""
from __future__ import annotations

import ast
import runpy
from pathlib import Path

ROOT = Path(".")
PRIMARY = ROOT / "scripts/ci/source_fix_pr1672_single_request.py"
REVIEW_TEST = ROOT / "tests/test_noema_review_gate.py"
TELEMETRY_TEST = ROOT / "tests/test_noema_repair_attempt_telemetry.py"
SELF = ROOT / "scripts/ci/source_fix_pr1672_v2.py"
WORKFLOW = ROOT / ".github/workflows/source-fix-pr1672-single-request-v2.yml"

STALE_TESTS = {
    "test_call_llm_repairs_one_malformed_envelope_before_failing_closed",
    "test_call_llm_still_repairs_once_when_head_has_not_moved",
    "test_call_llm_fails_closed_after_repeated_malformed_envelope",
    "test_call_llm_fails_closed_after_repeated_invalid_utf8_response",
    "test_call_llm_repairs_once_after_a_transport_error_then_succeeds",
    "test_call_llm_fails_closed_after_a_repeated_transport_error",
    "test_call_llm_repairs_once_after_a_truncated_response_then_succeeds",
    "test_call_llm_fails_closed_after_a_repeated_truncated_response",
    "test_call_llm_repairs_once_after_a_socket_timeout_then_succeeds",
    "test_call_llm_fails_closed_after_a_repeated_socket_timeout",
    "test_call_llm_repairs_one_malformed_json_response",
    "test_call_llm_repairs_one_rejected_changed_line_verdict",
}


def _replace_labeled_call(source: str, label: str, replacement: str) -> str:
    marker = f"        '{label}',\n    )"
    marker_pos = source.find(marker)
    if marker_pos < 0 or source.find(marker, marker_pos + 1) >= 0:
        raise RuntimeError(f"PR1672 {label} marker moved or duplicated")
    start = source.rfind("    source = replace_once(\n", 0, marker_pos)
    if start < 0:
        raise RuntimeError(f"PR1672 {label} replacement start missing")
    end = marker_pos + len(marker)
    return source[:start] + replacement + source[end:]


def _insert_after_labeled_call(source: str, label: str, addition: str) -> str:
    marker = f"        '{label}',\n    )"
    marker_pos = source.find(marker)
    if marker_pos < 0 or source.find(marker, marker_pos + 1) >= 0:
        raise RuntimeError(f"PR1672 {label} marker moved or duplicated")
    end = marker_pos + len(marker)
    return source[:end] + "\n" + addition + source[end:]


def normalize_primary_materializer() -> None:
    """Codify the previously runtime-only materializer repairs before execution."""
    text = PRIMARY.read_text(encoding="utf-8")
    old_span = "        start = node.lineno - 1\n        end = node.end_lineno or node.lineno\n"
    new_span = (
        "        decorator_lines = [decorator.lineno for decorator in node.decorator_list]\n"
        "        start = min([node.lineno, *decorator_lines]) - 1\n"
        "        end = node.end_lineno or node.lineno\n"
    )
    if text.count(old_span) != 1:
        raise RuntimeError("PR1672 remove_functions span contract moved")
    text = text.replace(old_span, new_span, 1)

    gate_call = '''    source = replace_once(
        source,
        r'    try:\\n        verdict = call_llm\\(repo, number, pr, diff, truncated, expected_head, review_context, changed_paths\\)\\n    except StaleHeadDuringRepairRetryError:\\n        print\\("Pull request head changed during review; Noema review skipped before repair retry\\."\\)\\n        return 0\\n',
        '    verdict = call_llm(repo, number, pr, diff, truncated, expected_head, review_context, changed_paths)\\n',
        'inspect_and_review retry catch',
    )
    source = source.replace(
        '    comparisons below, and before the one ``call_llm`` performs on its own\\n'
        '    repair-retry path (see ``StaleHeadDuringRepairRetryError``). The CLI and\\n',
        '    comparisons below and the post-model publication check. The CLI and\\n',
    )'''
    text = _replace_labeled_call(text, "inspect_and_review retry catch", gate_call)

    two_phase_call = '''    source = replace_once(
        source,
        r'    try:\\n        verdict = gate\\.call_llm\\(\\n            repo,\\n            number,\\n            pull_request,\\n            diff,\\n            truncated,\\n            expected,\\n            review_context,\\n            changed_paths,\\n        \\)\\n    except gate\\.StaleHeadDuringRepairRetryError:\\n        print\\("Pull request head changed during model repair retry; verdict was not sealed\\."\\)\\n        return 0\\n',
        '    verdict = gate.call_llm(\\n        repo,\\n        number,\\n        pull_request,\\n        diff,\\n        truncated,\\n        expected,\\n        review_context,\\n        changed_paths,\\n    )\\n',
        'two-phase retry catch',
    )'''
    text = _replace_labeled_call(text, "two-phase retry catch", two_phase_call)

    stale_exception_call = '''    source = replace_once(
        source,
        r'class StaleHeadDuringRepairRetryError\\(RuntimeError\\):\\n    """Raised when the PR head moves before ``call_llm``.s repair-retry request fires\\."""\\n\\n'.replace('``.s', "``'s"),
        '',
        'stale repair exception',
    )'''
    text = _insert_after_labeled_call(text, "deadline exception", stale_exception_call)
    PRIMARY.write_text(text, encoding="utf-8")


def remove_stale_retry_tests() -> None:
    """Remove only obsolete two-request tests; replacement coverage is added below."""
    source = REVIEW_TEST.read_text(encoding="utf-8")
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    spans: list[tuple[int, int]] = []
    found: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in STALE_TESTS:
            decorator_lines = [decorator.lineno for decorator in node.decorator_list]
            start = min([node.lineno, *decorator_lines]) - 1
            end = node.end_lineno or node.lineno
            spans.append((start, end))
            found.add(node.name)
    missing = STALE_TESTS - found
    if missing:
        raise RuntimeError(f"PR1672 stale retry tests moved unexpectedly: {sorted(missing)}")
    for start, end in sorted(spans, reverse=True):
        del lines[start:end]
    REVIEW_TEST.write_text("".join(lines), encoding="utf-8")


def append_single_request_failure_regressions() -> None:
    """Retain transport/output/validation coverage under the one-request contract."""
    current = TELEMETRY_TEST.read_text(encoding="utf-8")
    if "test_malformed_gateway_envelope_is_one_request_fail_closed" in current:
        return
    extra = r'''


def _single_request_transport(monkeypatch, *, raw=None, open_error=None, read_error=None):
    monkeypatch.setenv("NOEMA_LLM_API_URL", "https://llm.example/v1/chat/completions")
    monkeypatch.setenv("NOEMA_LLM_API_KEY", "test-key")
    calls = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            if read_error is not None:
                raise read_error
            assert raw is not None
            return raw

    def open_response(_opener, request, **kwargs):
        calls.append(request)
        assert kwargs == {}
        if open_error is not None:
            raise open_error(request) if callable(open_error) else open_error
        return Response()

    monkeypatch.setattr(gate.urllib.request.OpenerDirector, "open", open_response)
    return calls


def _invoke_once(monkeypatch, **transport):
    calls = _single_request_transport(monkeypatch, **transport)
    kwargs = dict(
        repo="owner/repo",
        number=7,
        pr={"title": "t", "headRefOid": "c" * 40},
        diff=DIFF,
        truncated=False,
        expected_head="c" * 40,
        changed_paths=("README.md",),
    )
    return calls, kwargs


def test_malformed_gateway_envelope_is_one_request_fail_closed(monkeypatch) -> None:
    calls, kwargs = _invoke_once(monkeypatch, raw=b"[]")
    with pytest.raises(gate.NoemaModelOutputError, match="caller attempts=1"):
        gate.call_llm(**kwargs)
    assert len(calls) == 1


def test_invalid_utf8_is_one_request_fail_closed(monkeypatch) -> None:
    calls, kwargs = _invoke_once(monkeypatch, raw=b"invalid: \x80\x81\xfe")
    with pytest.raises(gate.NoemaModelOutputError, match="caller attempts=1"):
        gate.call_llm(**kwargs)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "failure",
    [
        lambda request: gate.urllib.error.HTTPError(request.full_url, 502, "Bad Gateway", {}, None),
        OSError("socket timeout"),
    ],
)
def test_connect_failures_are_one_request_and_typed(monkeypatch, failure) -> None:
    calls, kwargs = _invoke_once(monkeypatch, open_error=failure)
    with pytest.raises(gate.NoemaTransportError, match="caller attempts=1"):
        gate.call_llm(**kwargs)
    assert len(calls) == 1


def test_truncated_read_is_one_request_and_typed(monkeypatch) -> None:
    calls, kwargs = _invoke_once(
        monkeypatch, read_error=gate.http.client.IncompleteRead(b"partial", 10)
    )
    with pytest.raises(gate.NoemaTransportError, match="caller attempts=1"):
        gate.call_llm(**kwargs)
    assert len(calls) == 1


def test_malformed_verdict_json_is_not_retried(monkeypatch) -> None:
    raw = json.dumps({"model": "provider/model", "choices": [{"message": {"content": "{bad"}}]}).encode()
    calls, kwargs = _invoke_once(monkeypatch, raw=raw)
    with pytest.raises(gate.NoemaModelOutputError, match="caller attempts=1"):
        gate.call_llm(**kwargs)
    assert len(calls) == 1


def test_rejected_changed_line_verdict_is_not_retried(monkeypatch) -> None:
    verdict = _verdict()
    verdict["decision"] = "request_changes"
    verdict["findings"] = [{
        "severity": "high",
        "file": "README.md",
        "line": 99,
        "side": "RIGHT",
        "message": "Outside the changed hunk.",
    }]
    raw = json.dumps({"model": "provider/model", "choices": [{"message": {"content": json.dumps(verdict)}}]}).encode()
    calls, kwargs = _invoke_once(monkeypatch, raw=raw)
    with pytest.raises(gate.NoemaModelOutputError, match="caller attempts=1"):
        gate.call_llm(**kwargs)
    assert len(calls) == 1
'''
    TELEMETRY_TEST.write_text(current.rstrip() + extra + "\n", encoding="utf-8")


def normalize_trailing_newlines() -> None:
    """Keep generated text Git-clean with exactly one terminal newline."""
    for relative_path in (
        "docs/product-technical-gap-baseline.md",
        "tests/test_noema_model_output_failure_classification.py",
        "tests/test_noema_repair_attempt_telemetry.py",
    ):
        path = ROOT / relative_path
        if path.exists():
            path.write_text(path.read_text(encoding="utf-8").rstrip() + "\n", encoding="utf-8")


def main() -> None:
    """Run the owner repair, retain equivalent GREEN regressions, and retire helpers."""
    normalize_primary_materializer()
    runpy.run_path(str(PRIMARY), run_name="__main__")
    remove_stale_retry_tests()
    append_single_request_failure_regressions()
    normalize_trailing_newlines()
    SELF.unlink(missing_ok=True)
    WORKFLOW.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
