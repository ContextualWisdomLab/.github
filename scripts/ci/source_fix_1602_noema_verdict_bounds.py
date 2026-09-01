#!/usr/bin/env python3
"""Apply and verify the PR #1602 structured-verdict hardening review fixes."""

from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess


TEST_PATH = Path("tests/test_noema_truncated_completion_contract.py")
SOURCE_PATH = Path("scripts/ci/noema_review_gate.py")


def run(*args: str, check: bool = True, capture: bool = False) -> subprocess.CompletedProcess[str]:
    """Run one trusted local command with deterministic text handling."""
    return subprocess.run(
        args,
        check=check,
        text=True,
        capture_output=capture,
        env={**os.environ, "PYTHONPATH": "."},
    )


def commit_and_push(message: str) -> None:
    """Commit staged repair content and publish it without rewriting history."""
    run("git", "diff", "--cached", "--check")
    run("git", "commit", "-m", message)
    run("git", "push", "origin", f"HEAD:{os.environ['TARGET_BRANCH']}")


def add_red_tests() -> None:
    """Append regressions that fail against the current malformed-output boundary."""
    text = TEST_PATH.read_text(encoding="utf-8")
    if "test_call_llm_rejects_non_string_rendered_evidence" in text:
        return
    text += r'''


def test_call_llm_rejects_non_string_rendered_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A comment verdict cannot expand list/object evidence into a review body."""
    malformed = json.dumps(
        {
            "decision": "comment",
            "summary": "bounded",
            "findings": [],
            "reviewed_lines": [
                {
                    "path": "src/example.py",
                    "line": 7,
                    "side": "RIGHT",
                    "analysis": ["x" * noema.NOEMA_MAX_VERDICT_TEXT_CHARS],
                }
            ],
        }
    )
    opener = _Opener([_envelope(malformed, "stop"), _envelope(malformed, "stop")])
    _configure(monkeypatch, opener)

    with pytest.raises(RuntimeError, match="reviewed_lines.analysis must be a string"):
        noema.call_llm("owner/repo", 7, _pr(), "diff", False, HEAD)

    assert len(opener.requests) == 2


def test_verdict_output_bounds_type_check_every_rendered_probe_field() -> None:
    """Every adversarial field interpolated into Markdown has a typed bound."""
    base_probe = {
        "path": "src/example.py",
        "line": 8,
        "side": "RIGHT",
        "outcome": "inconclusive",
        "hypothesis": "bounded hypothesis",
        "attack_or_counterexample": "bounded attack",
        "evidence": "bounded evidence",
    }
    for field in (
        "path",
        "side",
        "outcome",
        "hypothesis",
        "attack_or_counterexample",
        "evidence",
    ):
        probe = dict(base_probe)
        probe[field] = ["not", "text"]
        with pytest.raises(RuntimeError, match=rf"probes\.{field} must be a string"):
            noema.validate_verdict_output_bounds(
                {
                    "summary": "bounded",
                    "findings": [],
                    "adversarial_validation": {
                        "residual_risk": "bounded",
                        "probes": [probe],
                    },
                }
            )

    bad_line = dict(base_probe)
    bad_line["line"] = [8]
    with pytest.raises(RuntimeError, match="probes.line must be a positive integer"):
        noema.validate_verdict_output_bounds(
            {
                "summary": "bounded",
                "findings": [],
                "adversarial_validation": {
                    "residual_risk": "bounded",
                    "probes": [bad_line],
                },
            }
        )


def test_call_llm_types_repeated_schema_invalid_verdict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A decoded but schema-invalid verdict gets a stable retry diagnostic."""
    malformed = json.dumps(
        {"decision": "unsupported", "summary": "bounded", "findings": []}
    )
    opener = _Opener([_envelope(malformed, "stop"), _envelope(malformed, "stop")])
    _configure(monkeypatch, opener)

    with pytest.raises(RuntimeError, match="invalid_verdict_after_retry"):
        noema.call_llm("owner/repo", 7, _pr(), "diff", False, HEAD)

    assert len(opener.requests) == 2
'''
    TEST_PATH.write_text(text, encoding="utf-8")


def verify_red() -> None:
    """Prove the new tests fail for the intended missing production behavior."""
    result = run(
        "python3",
        "-m",
        "pytest",
        "-q",
        f"{TEST_PATH}::test_call_llm_rejects_non_string_rendered_evidence",
        f"{TEST_PATH}::test_verdict_output_bounds_type_check_every_rendered_probe_field",
        f"{TEST_PATH}::test_call_llm_types_repeated_schema_invalid_verdict",
        check=False,
        capture=True,
    )
    output = result.stdout + result.stderr
    print(output)
    if result.returncode != 1 or "3 failed" not in output:
        raise SystemExit(
            "Expected exactly three RED regressions before the production repair"
        )


def patch_source() -> None:
    """Make rendered verdict evidence typed/bounded and classify schema retries."""
    text = SOURCE_PATH.read_text(encoding="utf-8")

    class_anchor = '''class InvalidCompletionError(RuntimeError):\n    """Signal an unusable structured-completion envelope or JSON payload.\n\n    This type separates arbitrary malformed output from a provider-declared\n    ``finish_reason=length`` response.\n    """\n\n\n'''
    class_replacement = class_anchor + '''class InvalidVerdictError(RuntimeError):\n    """Signal decoded JSON that fails the bounded Noema verdict contract."""\n\n\n'''
    if "class InvalidVerdictError" not in text:
        if text.count(class_anchor) != 1:
            raise SystemExit("InvalidCompletionError anchor changed unexpectedly")
        text = text.replace(class_anchor, class_replacement, 1)

    bounded_old = '''def _bounded_text(value: Any, label: str, limit: int) -> None:\n    """Reject a present text field that exceeds the declared output budget."""\n    if isinstance(value, str) and len(value) > limit:\n        raise RuntimeError(f"Noema LLM response {label} exceeds {limit} characters")\n\n\n'''
    bounded_new = '''def _bounded_text(value: Any, label: str, limit: int) -> None:\n    """Reject a present rendered field unless it is bounded text."""\n    if value is None:\n        return\n    if not isinstance(value, str):\n        raise RuntimeError(f"Noema LLM response {label} must be a string")\n    if len(value) > limit:\n        raise RuntimeError(f"Noema LLM response {label} exceeds {limit} characters")\n\n\ndef _required_bounded_text(value: Any, label: str, limit: int) -> str:\n    """Return one non-empty rendered text field after enforcing its bound."""\n    _bounded_text(value, label, limit)\n    if not isinstance(value, str) or not value.strip():\n        raise RuntimeError(f"Noema LLM response {label} must be a non-empty string")\n    return value\n\n\ndef _positive_line(value: Any, label: str) -> int:\n    """Return one positive rendered line number after rejecting bools/objects."""\n    if type(value) is not int or value <= 0:\n        raise RuntimeError(f"Noema LLM response {label} must be a positive integer")\n    return value\n\n\n'''
    if bounded_old not in text:
        raise SystemExit("_bounded_text implementation changed unexpectedly")
    text = text.replace(bounded_old, bounded_new, 1)

    replacement = r'''def validate_verdict_output_bounds(verdict: dict[str, Any]) -> None:
    """Enforce typed cardinality and text limits on every rendered verdict field.

    ``comment`` verdicts bypass the stronger substantive-evidence validator, so
    this boundary must independently ensure that values later interpolated into
    GitHub Markdown cannot expand arbitrary lists/objects or unbounded strings.
    """

    _bounded_text(
        verdict.get("summary"), "summary", NOEMA_MAX_VERDICT_TEXT_CHARS
    )

    reviewed_lines = _bounded_list(
        verdict.get("reviewed_lines"), "reviewed_lines", NOEMA_MAX_REVIEWED_LINES
    )
    for reviewed in reviewed_lines:
        if not isinstance(reviewed, dict):
            raise RuntimeError("Noema LLM response reviewed_lines entries must be objects")
        _required_bounded_text(
            reviewed.get("path"),
            "reviewed_lines.path",
            NOEMA_MAX_VERDICT_TEXT_CHARS,
        )
        _positive_line(reviewed.get("line"), "reviewed_lines.line")
        _required_bounded_text(
            reviewed.get("side"),
            "reviewed_lines.side",
            NOEMA_MAX_VERDICT_TEXT_CHARS,
        )
        _required_bounded_text(
            reviewed.get("analysis"),
            "reviewed_lines.analysis",
            NOEMA_MAX_VERDICT_TEXT_CHARS,
        )

    validation = verdict.get("adversarial_validation")
    if validation is not None and not isinstance(validation, dict):
        raise RuntimeError("Noema LLM response adversarial_validation must be an object")
    if isinstance(validation, dict):
        _required_bounded_text(
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
                raise RuntimeError(
                    "Noema LLM response adversarial_validation.probes entries must be objects"
                )
            for field in (
                "path",
                "side",
                "outcome",
                "hypothesis",
                "attack_or_counterexample",
                "evidence",
            ):
                _required_bounded_text(
                    probe.get(field),
                    f"adversarial_validation.probes.{field}",
                    NOEMA_MAX_VERDICT_TEXT_CHARS,
                )
            _positive_line(
                probe.get("line"), "adversarial_validation.probes.line"
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
        if not isinstance(finding, dict):
            raise RuntimeError("Noema LLM response findings entries must be objects")
        _required_bounded_text(
            finding.get("file"), "findings.file", NOEMA_MAX_VERDICT_TEXT_CHARS
        )
        _bounded_text(
            finding.get("message"),
            "findings.message",
            NOEMA_MAX_VERDICT_TEXT_CHARS,
        )

'''
    text, count = re.subn(
        r"def validate_verdict_output_bounds\(verdict: dict\[str, Any\]\) -> None:\n.*?(?=\ndef call_llm\()",
        replacement,
        text,
        count=1,
        flags=re.DOTALL,
    )
    if count != 1:
        raise SystemExit("validate_verdict_output_bounds block changed unexpectedly")

    envelope_old = '''        raw = decode_llm_response_body(raw_bytes)\n        try:\n            completion = extract_llm_completion(raw)\n        except RuntimeError as exc:\n            raise InvalidCompletionError(str(exc)) from exc\n'''
    envelope_new = '''        try:\n            raw = decode_llm_response_body(raw_bytes)\n            completion = extract_llm_completion(raw)\n        except RuntimeError as exc:\n            raise InvalidCompletionError(str(exc)) from exc\n'''
    if envelope_old not in text:
        raise SystemExit("completion envelope block changed unexpectedly")
    text = text.replace(envelope_old, envelope_new, 1)

    validation_pattern = re.compile(
        r'''        decision = str\(verdict\.get\("decision"\) or ""\)\.strip\(\)\.lower\(\)\n.*?        validate_substantive_verdict\(verdict, diff, changed_paths\)\n''',
        re.DOTALL,
    )
    validation_replacement = '''        try:\n            decision_value = verdict.get("decision")\n            if not isinstance(decision_value, str):\n                raise RuntimeError("Noema LLM response decision must be a string")\n            decision = decision_value.strip().lower()\n            if decision not in {"approve", "request_changes", "comment"}:\n                raise RuntimeError("Noema LLM returned an unsupported decision")\n            summary = verdict.get("summary")\n            if not isinstance(summary, str) or not summary.strip():\n                raise RuntimeError("Noema LLM response did not contain a substantive summary")\n            findings = verdict.get("findings")\n            if not isinstance(findings, list) or any(not isinstance(finding, dict) for finding in findings):\n                raise RuntimeError("Noema LLM response findings must be a list of objects")\n            for finding in findings:\n                if (\n                    finding.get("severity") not in {"high", "medium", "low"}\n                    or not isinstance(finding.get("file"), str)\n                    or not finding["file"].strip()\n                    or type(finding.get("line")) is not int\n                    or finding["line"] <= 0\n                    or finding.get("side") not in {"RIGHT", "LEFT"}\n                    or not isinstance(finding.get("message"), str)\n                    or not finding["message"].strip()\n                ):\n                    raise RuntimeError("Noema LLM response contained a malformed finding")\n            if decision == "request_changes" and not findings:\n                raise RuntimeError("Noema LLM request_changes response did not contain a substantive finding")\n            validate_verdict_output_bounds(verdict)\n            validate_substantive_verdict(verdict, diff, changed_paths)\n        except RuntimeError as exc:\n            raise InvalidVerdictError(str(exc)) from exc\n'''
    text, count = validation_pattern.subn(validation_replacement, text, count=1)
    if count != 1:
        raise SystemExit("call_llm verdict validation block changed unexpectedly")

    retry_old = '''            if isinstance(exc, InvalidCompletionError):\n                raise RuntimeError(\n                    f"Noema LLM response invalid_json_after_retry: {exc}"\n                ) from exc\n            if isinstance(exc, RuntimeError):\n                raise\n'''
    retry_new = '''            if isinstance(exc, InvalidCompletionError):\n                raise RuntimeError(\n                    f"Noema LLM response invalid_json_after_retry: {exc}"\n                ) from exc\n            if isinstance(exc, InvalidVerdictError):\n                raise RuntimeError(\n                    f"Noema LLM response invalid_verdict_after_retry: {exc}"\n                ) from exc\n            if isinstance(exc, RuntimeError):\n                raise\n'''
    if retry_old not in text:
        raise SystemExit("retry classifier block changed unexpectedly")
    text = text.replace(retry_old, retry_new, 1)

    SOURCE_PATH.write_text(text, encoding="utf-8")


def verify_green() -> None:
    """Run focused and full repository evidence after the source repair."""
    run("python3", "-m", "pytest", "-q", str(TEST_PATH))
    run("python3", "-m", "pytest", "-q", "tests")
    run("python3", "-m", "compileall", "-q", "scripts/ci/noema_review_gate.py")
    run("git", "diff", "--check")


def main() -> None:
    """Execute RED, publish the test, then implement and verify GREEN."""
    add_red_tests()
    verify_red()
    run("git", "add", str(TEST_PATH))
    commit_and_push("test(noema): expose unbounded structured verdict fields")

    patch_source()
    verify_green()
    run("git", "add", str(SOURCE_PATH), str(TEST_PATH))
    commit_and_push("fix(noema): bound rendered verdict fields and retry diagnostics")


if __name__ == "__main__":
    main()
