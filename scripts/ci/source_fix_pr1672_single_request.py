#!/usr/bin/env python3
"""Materialize PR #1672's single-request Noema contract and retire obsolete retry policy."""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path('.')
GATE = ROOT / 'scripts/ci/noema_review_gate.py'
TWO_PHASE = ROOT / '.github/actions/noema-review/two_phase.py'
MODEL_TEST = ROOT / 'tests/test_noema_model_output_failure_classification.py'
DEADLINE_TEST = ROOT / 'tests/test_noema_repair_deadline_alarm_safety.py'
TELEMETRY_TEST = ROOT / 'tests/test_noema_repair_attempt_telemetry.py'
DOCTORING = ROOT / 'docs/doctoring/noema-repair-attempt-telemetry.md'
CHANGELOG = ROOT / 'CHANGELOG.md'
BASELINE = ROOT / 'docs/product-technical-gap-baseline.md'
SELF = ROOT / 'scripts/ci/source_fix_pr1672_single_request.py'
WORKFLOW = ROOT / '.github/workflows/source-fix-pr1672-single-request.yml'


def replace_once(text: str, pattern: str, replacement: str, label: str, *, flags: int = re.DOTALL) -> str:
    updated, count = re.subn(pattern, lambda _m: replacement, text, count=1, flags=flags)
    if count != 1:
        raise RuntimeError(f'{label}: expected one replacement, got {count}')
    return updated


def remove_functions(path: Path, markers: tuple[str, ...]) -> None:
    """Delete only test functions coupled to removed retry/deadline symbols."""
    source = path.read_text(encoding='utf-8')
    tree = ast.parse(source)
    spans: list[tuple[int, int]] = []
    lines = source.splitlines(keepends=True)
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        start = node.lineno - 1
        end = node.end_lineno or node.lineno
        block = ''.join(lines[start:end])
        if any(marker in block for marker in markers):
            spans.append((start, end))
    for start, end in reversed(spans):
        del lines[start:end]
    path.write_text(''.join(lines), encoding='utf-8')


def repair_gate() -> None:
    source = GATE.read_text(encoding='utf-8')
    source = source.replace('import contextlib\n', '').replace('import signal\n', '')
    source = replace_once(
        source,
        r'# NOT DATA-DERIVED -- UNRESOLVED, flagged for an explicit owner decision\..*?NOEMA_REPAIR_DEADLINE_SECONDS = 15 \* 60\n\n',
        '',
        'fixed deadline block',
    )
    source = replace_once(
        source,
        r'class NoemaRepairDeadlineExceeded\(TimeoutError\):\n    """Raised when the corrective attempt exceeds its total wall-clock budget\."""\n\n',
        '',
        'deadline exception',
    )

    evidence_block = r'''def _required_probe_count(diff: str, changed_paths: Sequence[str] = ()) -> int:
    """Return the minimum adversarial-probe count a formal verdict must carry.

    This is the single source of truth shared by the structured-output schema
    and deterministic local validator. Executable/test/workflow changes require
    two distinct probes; other diffs require one. The bound is cardinality-
    based and independent of repository path count, so a near-MAX_DIFF_CHARS
    review remains representable within the gateway output budget.
    """
    locations = changed_diff_locations(diff)
    all_changed_paths = set(changed_paths) or {path for path, _line, _side in locations}
    return 2 if any(changed_file_is_material(path) for path in all_changed_paths) else 1


def _entry_ordinal(position: int, total: int) -> str:
    """Return an unambiguous 1-based array-position label for diagnostics."""
    return f"entry {position}/{total} (array index {position - 1}, not a source line)"


def _format_location(path: Any, line: Any, side: Any) -> str:
    """Format one rejected path/line/side citation without coercing its types."""
    return f"path={path!r} line={line!r} side={side!r}"


def _nearby_changed_locations(
    locations: set[tuple[str, int, str]], path: Any, line: Any, *, limit: int = 5
) -> str:
    """Return a bounded nearest-line hint for the rejected path."""
    if not isinstance(path, str):
        return ""
    same_path = [location for location in locations if location[0] == path]
    if not same_path:
        return ""
    if isinstance(line, int):
        same_path.sort(key=lambda location: (abs(location[1] - line), location[1], location[2]))
    else:
        same_path.sort(key=lambda location: (location[1], location[2]))
    sample = ", ".join(f"{p}:{ln} ({s})" for p, ln, s in same_path[:limit])
    remaining = len(same_path) - limit
    more = f", +{remaining} more" if remaining > 0 else ""
    return f"; nearest changed lines for {path}: {sample}{more}"


def validate_substantive_verdict(
    verdict: dict[str, Any], diff: str, changed_paths: Sequence[str] = ()
) -> None:
    """Reject formal verdicts without exact changed-line/adversarial evidence."""
    decision = str(verdict.get("decision") or "").lower()
    if decision == "comment":
        return
    locations = changed_diff_locations(diff)
    if not locations:
        raise RuntimeError("Noema formal verdict requires parseable changed-line evidence")

    reviewed_lines = verdict.get("reviewed_lines")
    if not isinstance(reviewed_lines, list) or not reviewed_lines:
        raise NoemaModelOutputError("Noema formal verdict requires at least one reviewed changed line")
    reviewed_total = len(reviewed_lines)
    for position, reviewed in enumerate(reviewed_lines, start=1):
        entry = _entry_ordinal(position, reviewed_total)
        if not isinstance(reviewed, dict):
            raise NoemaModelOutputError(f"Noema reviewed line {entry} must be an object")
        location = (reviewed.get("path"), reviewed.get("line"), reviewed.get("side"))
        if location not in locations:
            path, line, side = location
            raise NoemaModelOutputError(
                f"Noema reviewed line {entry} cites {_format_location(path, line, side)}, "
                f"which is not an exact changed-side line"
                f"{_nearby_changed_locations(locations, path, line)}"
            )
        analysis = reviewed.get("analysis")
        if not isinstance(analysis, str) or not analysis.strip():
            raise NoemaModelOutputError(f"Noema reviewed line {entry} requires concrete analysis")

    validation = verdict.get("adversarial_validation")
    if not isinstance(validation, dict):
        raise NoemaModelOutputError("Noema formal verdict requires adversarial_validation")
    status = validation.get("status")
    expected_status = "passed" if decision == "approve" else "failed"
    if status != expected_status:
        raise NoemaModelOutputError(f"Noema {decision} requires adversarial_validation.status={expected_status}")
    residual_risk = validation.get("residual_risk")
    if not isinstance(residual_risk, str) or not residual_risk.strip():
        raise NoemaModelOutputError("Noema adversarial validation requires residual_risk")
    probes = validation.get("probes")
    required_probes = _required_probe_count(diff, changed_paths)
    if not isinstance(probes, list) or len(probes) < required_probes:
        raise NoemaModelOutputError(
            f"Noema adversarial validation requires at least {required_probes} concrete probe(s)"
        )

    confirmed: set[tuple[str, int, str]] = set()
    identities: set[tuple[Any, ...]] = set()
    probes_total = len(probes)
    for position, probe in enumerate(probes, start=1):
        entry = _entry_ordinal(position, probes_total)
        if not isinstance(probe, dict):
            raise NoemaModelOutputError(f"Noema adversarial probe {entry} must be an object")
        location = (probe.get("path"), probe.get("line"), probe.get("side"))
        if location not in locations:
            path, line, side = location
            raise NoemaModelOutputError(
                f"Noema adversarial probe {entry} cites {_format_location(path, line, side)}, "
                f"which is not an exact changed-side line"
                f"{_nearby_changed_locations(locations, path, line)}"
            )
        for field in ("hypothesis", "attack_or_counterexample", "evidence"):
            value = probe.get(field)
            if not isinstance(value, str) or not value.strip():
                raise NoemaModelOutputError(f"Noema adversarial probe {entry} requires {field}")
        outcome = probe.get("outcome")
        if outcome not in {"falsified", "confirmed"}:
            raise NoemaModelOutputError(
                f"Noema adversarial probe {entry} outcome must be falsified or confirmed"
            )
        identity = (
            *location,
            probe["hypothesis"].strip().casefold(),
            probe["attack_or_counterexample"].strip().casefold(),
        )
        if identity in identities:
            raise NoemaModelOutputError(f"Noema adversarial probe {entry} duplicates an earlier probe")
        identities.add(identity)
        if outcome == "confirmed":
            confirmed.add((str(probe["path"]), int(probe["line"]), str(probe["side"])))

    if decision == "approve" and confirmed:
        raise NoemaModelOutputError("Noema approve cannot contain a confirmed adversarial probe")
    if decision == "request_changes":
        finding_locations = {
            (str(finding.get("file") or ""), finding.get("line"), str(finding.get("side") or ""))
            for finding in verdict.get("findings") or []
            if isinstance(finding, dict)
        }
        if not confirmed or not confirmed.intersection(finding_locations):
            raise NoemaModelOutputError(
                "Noema request_changes requires a confirmed probe on a published finding"
            )


'''
    source = replace_once(
        source,
        r'def _required_probe_count\(.*?\n\ndef truncate_text\(',
        evidence_block + 'def truncate_text(',
        'evidence validator',
    )

    comma_block = r'''def _strip_trailing_commas_outside_strings(text: str) -> str:
    """Remove only a genuine trailing comma after a complete JSON value.

    Missing-value forms such as ``[,]``, ``{,}``, ``[1,,]`` and ``{"a":,}``
    remain malformed and therefore fail closed. String contents are untouched.
    """
    result: list[str] = []
    in_string = False
    escaped = False
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if in_string:
            result.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            result.append(char)
            index += 1
            continue
        if char == ",":
            lookahead = index + 1
            while lookahead < length and text[lookahead] in " \t\r\n":
                lookahead += 1
            previous = len(result) - 1
            while previous >= 0 and result[previous] in " \t\r\n":
                previous -= 1
            prior = result[previous] if previous >= 0 else ""
            value_ending = prior in {'"', '}', ']'} or prior.isdigit() or prior in {'e', 'l'}
            if lookahead < length and text[lookahead] in "}]" and value_ending:
                index += 1
                continue
        result.append(char)
        index += 1
    return "".join(result)


'''
    source = replace_once(
        source,
        r'def _strip_trailing_commas_outside_strings\(.*?\n\ndef extract_json_object\(',
        comma_block + 'def extract_json_object(',
        'trailing-comma parser',
    )
    source = source.replace(
        '''        print(\n            "::notice::Noema local trailing-comma JSON repair recovered an "\n            "otherwise-malformed response; no network repair retry was needed."\n        )\n        return verdict\n''',
        '        return verdict\n',
    )

    model_block = r'''def _extract_served_model(raw: str) -> str | None:
    """Return a bounded, scrubbed, single-line UTF-8-printable serving model id."""
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    served = data.get("model")
    if not isinstance(served, str) or not served.strip():
        return None
    scrubbed = scrub_sensitive_data(served.strip()) or ""
    printable = scrubbed.encode("utf-8", errors="backslashreplace").decode("utf-8")
    printable = "".join(" " if ord(char) < 32 or ord(char) == 127 else char for char in printable)
    printable = " ".join(printable.split())
    return printable[:200] or None


'''
    source = replace_once(
        source,
        r'def _extract_served_model\(.*?\n\ndef _truthy_env\(',
        model_block + 'def _truthy_env(',
        'served-model sanitizer',
    )

    source = replace_once(
        source,
        r'@contextlib\.contextmanager\ndef _repair_wall_clock_deadline\(.*?\n\ndef call_llm\(',
        'def call_llm(',
        'retry/deadline machinery',
    )

    call_block = r'''def call_llm(
    repo: str,
    number: int,
    pr: dict[str, Any],
    diff: str,
    truncated: bool,
    expected_head: str,
    review_context: str = "",
    changed_paths: Sequence[str] = (),
) -> dict[str, Any]:
    """Issue exactly one structured-output request through contextual-orchestrator.

    The gateway owns provider discovery, schema repair, candidate exclusion,
    failover, and model timeouts. This caller therefore performs one request,
    carries no fixed model wall-clock deadline or sampling temperature, and
    fails closed if the gateway does not return a locally valid verdict.
    Publication still performs a fresh exact-head check after model work.
    """
    api_url = os.environ.get("NOEMA_LLM_API_URL", "").strip()
    api_key = os.environ.get("NOEMA_LLM_API_KEY", "").strip()
    model = os.environ.get("NOEMA_LLM_MODEL", "").strip() or "orchestrator/free"
    if not api_url or not api_key:
        raise RuntimeError(
            "Noema LLM review unavailable: NOEMA_LLM_API_URL or NOEMA_LLM_API_KEY is not configured."
        )
    reject_private_llm_url(api_url)

    allowed_locations = [
        {"path": path, "line": line, "side": side}
        for path, line, side in sorted(changed_diff_locations(diff))
    ]
    location_example = allowed_locations[0] if allowed_locations else {
        "path": "path", "line": 0, "side": "RIGHT"
    }
    prompt = {
        "role": "user",
        "content": "\n".join(
            [
                "You are Noema, an independent pull request reviewer for ContextualWisdomLab.",
                "Review the PR diff plus the additional changed-file and review-thread context for correctness, security, maintainability, and behavioral regressions.",
                "Return only JSON with the declared response_format schema.",
                "Every formal verdict must cite exact changed-side lines. APPROVE requires falsifying concrete regression hypotheses; source or test changes require at least two distinct probes and other changes require at least one. REQUEST_CHANGES requires a confirmed probe at a finding location.",
                "Use request_changes only for blocking, concrete issues. A generic no-issues statement is not review evidence.",
                f"Repository: {repo}",
                f"PR: #{number}",
                f"Title: {pr.get('title') or ''}",
                f"Head SHA: {pr.get('headRefOid') or ''}",
                f"Diff truncated: {truncated}",
                "Additional context:",
                review_context or "No additional context was available.",
                "Diff:",
                diff,
            ]
        ),
    }
    payload = {
        "model": model,
        "response_format": _noema_verdict_response_format(
            _required_probe_count(diff, changed_paths)
        ),
        "messages": [
            {"role": "system", "content": "Return strict JSON only. Do not include markdown."},
            prompt,
        ],
    }
    request = urllib.request.Request(
        api_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "authorization": f"Bearer {api_key}",
            "content-type": "application/json",
        },
        method="POST",
    )
    opener = urllib.request.build_opener(NoRedirectHandler())
    attempt_started = time.monotonic()
    active_phase = "connecting"
    served_model: str | None = None
    try:
        with opener.open(request) as response:  # nosec B310
            active_phase = "reading"
            raw_bytes = response.read()
        active_phase = "decoding"
        raw = decode_llm_response_body(raw_bytes)
        served_model = _extract_served_model(raw)
        content = extract_llm_message_content(raw)
        verdict = extract_json_object(content)
        active_phase = "validating"
        decision = str(verdict.get("decision") or "").strip().lower()
        if decision not in {"approve", "request_changes", "comment"}:
            raise NoemaModelOutputError(
                f"Noema LLM returned unsupported decision: {decision!r}"
            )
        summary = verdict.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            raise NoemaModelOutputError(
                "Noema LLM response did not contain a substantive summary"
            )
        findings = verdict.get("findings")
        if not isinstance(findings, list) or any(
            not isinstance(finding, dict) for finding in findings
        ):
            raise NoemaModelOutputError(
                "Noema LLM response findings must be a list of objects"
            )
        for finding in findings:
            if (
                finding.get("severity") not in {"high", "medium", "low"}
                or not isinstance(finding.get("file"), str)
                or not finding["file"].strip()
                or type(finding.get("line")) is not int
                or finding["line"] <= 0
                or finding.get("side") not in {"RIGHT", "LEFT"}
                or not isinstance(finding.get("message"), str)
                or not finding["message"].strip()
            ):
                raise NoemaModelOutputError(
                    "Noema LLM response contained a malformed finding"
                )
        if decision == "request_changes" and not findings:
            raise NoemaModelOutputError(
                "Noema LLM request_changes response did not contain a substantive finding"
            )
        validate_substantive_verdict(verdict, diff, changed_paths)
    except (RuntimeError, urllib.error.URLError, http.client.HTTPException, OSError) as exc:
        elapsed = time.monotonic() - attempt_started
        current_failure = _stable_failure_diagnostic(exc)
        model_note = served_model or "unknown"
        print(
            f"::warning::Noema gateway attempt outcome=failed phase={active_phase} "
            f"duration={elapsed:.1f}s served_model={model_note}; "
            "caller attempts=1 (gateway owns repair/failover)."
        )
        suffix = (
            f"; caller attempts=1, duration={elapsed:.1f}s, "
            f"phase={active_phase}, served_model={model_note}"
        )
        if isinstance(exc, NoemaModelOutputError):
            raise NoemaModelOutputError(
                f"Noema model output failed local validation: {current_failure}{suffix}"
            ) from None
        if isinstance(exc, (urllib.error.URLError, http.client.HTTPException, OSError)):
            raise NoemaTransportError(
                f"Noema gateway transport failed: {type(exc).__name__}: {current_failure}{suffix}"
            ) from exc
        raise RuntimeError(
            f"Noema review failed closed: {current_failure}{suffix}"
        ) from exc
    elapsed = time.monotonic() - attempt_started
    print(
        f"::notice::Noema gateway attempt outcome=success phase={active_phase} "
        f"duration={elapsed:.1f}s served_model={served_model or 'unknown'}; "
        "caller attempts=1."
    )
    return verdict


'''
    source = replace_once(
        source,
        r'def call_llm\(.*?\n\ndef format_findings\(',
        call_block + 'def format_findings(',
        'single-request call_llm',
    )
    source = replace_once(
        source,
        r'    try:\n        verdict = call_llm\((.*?)\n        \)\n    except StaleHeadDuringRepairRetryError:\n        print\("Pull request head changed during review; Noema review skipped before repair retry\."\)\n        return 0\n',
        r'    verdict = call_llm(\1\n    )\n',
        'inspect_and_review retry catch',
    )

    forbidden = (
        'NOEMA_REPAIR_DEADLINE_SECONDS', '_repair_wall_clock_deadline(',
        'NoemaRepairDeadlineExceeded', 'signal.setitimer', 'StaleHeadDuringRepairRetryError',
        'is_retry', 'repair_error', 'return call_llm(', '"temperature"', 'import signal', 'import contextlib',
    )
    for token in forbidden:
        if token in source:
            raise RuntimeError(f'forbidden caller retry/deadline token remains: {token}')
    ast.parse(source)
    GATE.write_text(source, encoding='utf-8')


def repair_two_phase() -> None:
    source = TWO_PHASE.read_text(encoding='utf-8')
    source = replace_once(
        source,
        r'    try:\n        verdict = gate\.call_llm\((.*?)\n        \)\n    except gate\.StaleHeadDuringRepairRetryError:\n        print\("Pull request head changed during model repair retry; verdict was not sealed\."\)\n        return 0\n',
        r'    verdict = gate.call_llm(\1\n    )\n',
        'two-phase retry catch',
    )
    ast.parse(source)
    TWO_PHASE.write_text(source, encoding='utf-8')


def repair_tests() -> None:
    remove_functions(
        MODEL_TEST,
        (
            'NOEMA_REPAIR_DEADLINE_SECONDS', '_repair_wall_clock_deadline',
            'NoemaRepairDeadlineExceeded', 'len(requests) == 2', 'decode_calls == 2',
            'repair failure', 'bounded_repair', 'repeated_model_output_failure',
        ),
    )
    review_test = ROOT / 'tests/test_noema_review_gate.py'
    remove_functions(
        review_test,
        (
            'StaleHeadDuringRepairRetryError', 'stale before repair retry',
            'repair retry', 'repair_retry', 'is_retry=', 'repair_error=',
            'NOEMA_REPAIR_DEADLINE_SECONDS', '_repair_wall_clock_deadline',
        ),
    )
    DEADLINE_TEST.unlink(missing_ok=True)
    TELEMETRY_TEST.write_text(r'''"""Exact contracts for Noema's single gateway request and passive telemetry."""

import json

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
        "summary": "Reviewed the exact changed line.",
        "reviewed_lines": [{"path": "README.md", "line": 1, "side": "RIGHT", "analysis": "Bounded replacement."}],
        "adversarial_validation": {
            "status": "passed",
            "residual_risk": "No additional risk identified.",
            "probes": [{
                "path": "README.md", "line": 1, "side": "RIGHT",
                "hypothesis": "The replacement could be wrong.",
                "attack_or_counterexample": "Inspect the exact changed line.",
                "evidence": "The new value is present at the cited line.",
                "outcome": "falsified",
            }],
        },
        "findings": [],
    }


def _configure(monkeypatch, raw: bytes):
    monkeypatch.setenv("NOEMA_LLM_API_URL", "https://llm.example/v1/chat/completions")
    monkeypatch.setenv("NOEMA_LLM_API_KEY", "test-key")
    requests = []

    class Response:
        def __enter__(self): return self
        def __exit__(self, *_args): return None
        def read(self): return raw

    def open_response(_opener, request, **kwargs):
        requests.append(request)
        assert kwargs == {}
        return Response()

    monkeypatch.setattr(gate.urllib.request.OpenerDirector, "open", open_response)
    return requests


def test_success_uses_one_request_and_one_phase_annotation(monkeypatch, capsys) -> None:
    raw = json.dumps({"model": "provider/model", "choices": [{"message": {"content": json.dumps(_verdict())}}]}).encode()
    requests = _configure(monkeypatch, raw)
    verdict = gate.call_llm("owner/repo", 7, {"title": "t", "headRefOid": "a" * 40}, DIFF, False, "a" * 40, changed_paths=("README.md",))
    assert verdict["decision"] == "approve"
    assert len(requests) == 1
    output = capsys.readouterr().out
    assert output.count("::notice::Noema gateway attempt") == 1
    assert "phase=validating" in output
    assert "caller attempts=1" in output


def test_malformed_output_fails_closed_without_caller_retry(monkeypatch, capsys) -> None:
    raw = json.dumps({"model": "provider/model", "choices": [{"message": {"content": "not-json"}}]}).encode()
    requests = _configure(monkeypatch, raw)
    with pytest.raises(gate.NoemaModelOutputError, match="caller attempts=1"):
        gate.call_llm("owner/repo", 7, {"title": "t", "headRefOid": "b" * 40}, DIFF, False, "b" * 40, changed_paths=("README.md",))
    assert len(requests) == 1
    output = capsys.readouterr().out
    assert output.count("::warning::Noema gateway attempt") == 1


def test_served_model_is_annotation_safe() -> None:
    raw = json.dumps({"model": "bad\r\n::error::boom\u0000\ud800"})
    value = gate._extract_served_model(raw)
    assert value is not None
    assert "\r" not in value and "\n" not in value and "\x00" not in value
    assert "\\ud800" in value
    assert len(value) <= 200


@pytest.mark.parametrize("text", ["[,]", "{,}", "[1,,]", '{"a":,}'])
def test_local_json_repair_never_fabricates_missing_values(text: str) -> None:
    assert gate._strip_trailing_commas_outside_strings(text) == text


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('{"a":"x",}', '{"a":"x"}'),
        ('{"a":1,}', '{"a":1}'),
        ('{"a":true,}', '{"a":true}'),
        ('{"a":null,}', '{"a":null}'),
        ('{"a":{},}', '{"a":{}}'),
        ('{"a":[],}', '{"a":[]}'),
        ('["x",]', '["x"]'),
        ('[1,]', '[1]'),
    ],
)
def test_local_json_repair_accepts_only_complete_value_trailing_commas(text: str, expected: str) -> None:
    assert gate._strip_trailing_commas_outside_strings(text) == expected
''', encoding='utf-8')


def repair_docs() -> None:
    DOCTORING.write_text('''# Noema single-request review incident and telemetry contract\n\n## Incident\n\nOn 2026-09-02, a required Noema review reported only a caller-owned 900-second repair deadline after a malformed structured response. The bound had no owner-specified or measured basis and conflicted with ADR-0003: model inference and repair verdict calls do not carry repository-authored fixed wall-clock deadlines.\n\n```text\ninitial malformed structured response -> repository repair request -> fixed 900-second abort\n```\n\nThe later review established a second ownership error: `contextual-orchestrator` already owns structured-output validation and its governed repair/failover. Issuing another repository-side model request duplicated that policy and could turn one gateway failure into two expensive calls.\n\n## Final executable contract\n\nNoema now sends exactly one structured-output request to the configured gateway. GitHub Actions fixes the model alias to `orchestrator/free`; the caller declares no provider, paid fallback, sampling temperature, or fixed inference timeout. `contextual-orchestrator` owns provider discovery, capability routing, structured-output repair, failover, and upstream completion. The repository remains responsible for deterministic local validation and exact-head publication.\n\nEvery gateway call emits exactly one passive Actions annotation. Success and failure annotations include caller attempt count, elapsed duration, active phase (`connecting`, `reading`, `decoding`, or `validating`), and a best-effort serving-model identifier. Serving-model text is secret-scrubbed, control-character-normalized, UTF-8 printable, and bounded before it can reach an annotation. Raw model output is never logged.\n\nThe local trailing-comma parser remains a deterministic syntax transform only. It may remove a genuine trailing comma after a complete JSON value, but missing-value forms such as `[,]`, `{,}`, `[1,,]`, and `{"a":,}` remain invalid. The transform emits no second attempt-level annotation and never bypasses semantic verdict validation.\n\nExact changed-line diagnostics include the rejected path/line/side, an unambiguous array position, and a bounded nearest-line hint. This keeps a failed verdict repairable at the gateway without expanding the output contract to one record per changed line.\n\n## Ownership and failure scenes\n\n```text\nNoema workflow -> local contextual-orchestrator sidecar -> orchestrator/free -> routed free candidate\n               -> one returned envelope -> local deterministic validation -> exact-head publication\n```\n\nIf the gateway cannot produce a valid structured verdict, Noema fails closed after that one caller request. If the PR head moves during model work, the post-call exact-head check discards the stale verdict. If telemetry carries hostile model identifiers, annotation sanitization prevents CR/LF or surrogate data from becoming workflow commands or crashing the runner.\n\n## Verification\n\nThe permanent contract test forbids `NOEMA_REPAIR_DEADLINE_SECONDS`, `_repair_wall_clock_deadline`, `NoemaRepairDeadlineExceeded`, `signal.setitimer`, retry-only parameters/recursion, and caller-specified `temperature`. Focused regressions prove one request on success and failure, one annotation per attempt, safe serving-model telemetry, strict missing-value rejection, accepted genuine trailing commas, and preserved exact changed-line diagnostics.\n''', encoding='utf-8')

    change = '''## 2026-09-02 — Noema single-request gateway ownership\n\n- Removed the repository-owned 900-second repair deadline and duplicate model repair call from Noema. The GitHub Actions caller now issues one structured-output request while `contextual-orchestrator` owns repair/failover/timeouts.\n- Hardened serving-model telemetry against control-character/workflow-command injection and lone-surrogate encoding failures, restored actionable exact changed-line diagnostics, and constrained local trailing-comma repair to complete JSON values.\n- Added permanent single-request/no-fixed-timeout regressions and retired obsolete deadline/retry fixtures.\n\n'''
    changelog = CHANGELOG.read_text(encoding='utf-8')
    if change not in changelog:
        CHANGELOG.write_text(change + changelog, encoding='utf-8')

    baseline = BASELINE.read_text(encoding='utf-8')
    section = '''\n\n## Noema single-request model-control ownership — PR #1672 (2026-09-02)\n\n**Status:** Proposed / exact-head verification required before merge.\n\n**Root cause.** Noema duplicated `contextual-orchestrator` structured-output repair by making a second model request and wrapped that request in an unmeasured 900-second repository wall-clock deadline. This created a self-hosting admission failure: the required review could terminate valid long inference using policy that the gateway already owns.\n\n**Context Map / responsibility boundary.** `.github` owns CI review orchestration, exact-revision evidence, deterministic verdict validation and publication. `contextual-orchestrator` owns provider discovery, capability routing, `orchestrator/free`, structured-output repair/failover and provider completion. No provider/model-specific fallback or caller wall-clock timeout crosses that boundary.\n\n**Action.** Replace recursive caller repair with one structured-output gateway request; remove fixed deadline/signal machinery and sampling temperature; retain exact-head checks before and after model work; sanitize serving-model telemetry; restore exact changed-line diagnostics; retain bounded non-heuristic evidence cardinality and strict local JSON parsing.\n\n**Evidence / acceptance.** Permanent tests forbid retry/deadline/sampling symbols and prove one gateway request, one attempt annotation, control-character-safe telemetry, missing-value rejection, valid trailing-comma normalization, and exact changed-line guidance. Fresh exact-head repository checks/reviews remain the admission authority; predecessor-head evidence is not transferable.\n'''
    if '## Noema single-request model-control ownership — PR #1672 (2026-09-02)' not in baseline:
        BASELINE.write_text(baseline.rstrip() + section + '\n', encoding='utf-8')


def main() -> None:
    repair_gate()
    repair_two_phase()
    repair_tests()
    repair_docs()
    SELF.unlink(missing_ok=True)
    WORKFLOW.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
