#!/usr/bin/env python3
"""Close the remaining reviewed #1617 model-output and coverage gaps.

Temporary exact-head repair helper. The branch workflow removes this file before
verification and the production commit.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "scripts/ci/noema_review_gate.py"
TEST = ROOT / "tests/test_noema_model_output_failure_classification.py"
CHANGELOG = ROOT / "CHANGELOG.md"
ARCHITECTURE = ROOT / "ARCHITECTURE.md"
BASELINE = ROOT / "docs/product-technical-gap-baseline.md"
DOCTORING = ROOT / "docs/doctoring/noema-model-output-repair-boundary.md"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def update_source() -> None:
    text = SOURCE.read_text(encoding="utf-8")

    # A missing/invalid trusted diff is source evidence, not model output.
    text = replace_once(
        text,
        '        raise NoemaModelOutputError("Noema formal verdict requires parseable changed-line evidence")\n',
        '        raise RuntimeError("Noema formal verdict requires parseable changed-line evidence")\n',
        "trusted diff classification",
    )

    deadline_class = '''class NoemaRepairDeadlineExceeded(TimeoutError):
    """Raised when the corrective attempt exceeds its total wall-clock budget."""
'''
    diagnostic_helper = deadline_class + '''\n\ndef _stable_failure_diagnostic(exc: BaseException) -> str:
    """Return actionable trusted diagnostics without reflecting model values."""
    message = scrub_sensitive_data(str(exc)) or type(exc).__name__
    if not isinstance(exc, NoemaModelOutputError):
        return message

    # Model-output exceptions are raised only by deterministic parsing and
    # validation code. Preserve those static/structural diagnostics because
    # they tell the corrective model and operators exactly which contract was
    # violated. The one validator that embeds an untrusted model value is the
    # unsupported-decision check; redact that value. Unknown model-output
    # exception text fails closed to a stable code rather than being reflected.
    if message.startswith("Noema LLM returned unsupported decision:"):
        return "Noema LLM returned unsupported decision"
    trusted_prefixes = (
        "Noema LLM response ",
        "Noema LLM request_changes ",
        "Noema formal verdict ",
        "Noema reviewed line ",
        "Noema adversarial validation ",
        "Noema adversarial probe ",
        "Noema approve ",
        "Noema request_changes ",
    )
    if message.startswith(trusted_prefixes):
        return message
    return "model-output-contract-invalid"
'''
    text = replace_once(
        text,
        deadline_class,
        diagnostic_helper,
        "stable model-output diagnostic helper",
    )

    text = replace_once(
        text,
        '        current_failure = scrub_sensitive_data(str(exc)) or type(exc).__name__\n',
        '        current_failure = _stable_failure_diagnostic(exc)\n',
        "stable current failure diagnostic",
    )

    # Do not retain a model-controlled exception as an explicit cause: a raw
    # unsupported decision/probe sentinel must not reappear in traceback output.
    old_raise = '''                raise NoemaModelOutputError(
                    "Noema model-output repair remained invalid; "
                    f"initial failure: {initial_failure}; repair failure: {current_failure}"
                ) from exc
'''
    new_raise = '''                raise NoemaModelOutputError(
                    "Noema model-output repair remained invalid; "
                    f"initial failure: {initial_failure}; repair failure: {current_failure}"
                ) from None
'''
    text = replace_once(text, old_raise, new_raise, "model-output exception chaining")
    SOURCE.write_text(text, encoding="utf-8")


def update_tests() -> None:
    text = TEST.read_text(encoding="utf-8")
    marker = "def test_unparseable_diff_remains_source_evidence"
    if marker in text:
        raise RuntimeError("follow-up #1617 regressions already present")
    text += r'''


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
'''
    TEST.write_text(text, encoding="utf-8")


def update_docs() -> None:
    """Add drift-safe traceability for the actionable diagnostic contract."""
    changelog = CHANGELOG.read_text(encoding="utf-8")
    changelog_entry = (
        "- **Harden #1617 corrective diagnostics against model-value reflection.** "
        "The repair prompt and final fail-closed error preserve deterministic structural validator evidence "
        "needed to correct a malformed verdict, while model-controlled values (including an unsupported "
        "decision value) are redacted and an unknown model-output diagnostic collapses to a stable code.\n"
    )
    if changelog_entry not in changelog:
        changelog = replace_once(
            changelog,
            "## [Unreleased]\n",
            "## [Unreleased]\n" + changelog_entry,
            "changelog unreleased heading",
        )
    CHANGELOG.write_text(changelog, encoding="utf-8")

    architecture = ARCHITECTURE.read_text(encoding="utf-8")
    architecture_marker = "#### Actionable Noema repair diagnostics"
    if architecture_marker not in architecture:
        architecture += """

#### Actionable Noema repair diagnostics

The corrective prompt may retain only deterministic structural validator diagnostics
that are generated by trusted validation code. Model-controlled values are never
reflected into the corrective prompt or public exception chain: unsupported decision
values are reduced to their static defect class and unknown model-output diagnostics
collapse to a stable code. This keeps repair evidence actionable without turning the
reviewer itself into a data-reflection channel.
"""
    ARCHITECTURE.write_text(architecture, encoding="utf-8")

    baseline = BASELINE.read_text(encoding="utf-8")
    baseline_marker = "- **Diagnostic hardening:** #1617 corrective prompts"
    if baseline_marker not in baseline:
        baseline_heading = (
            "## 2026-09-01 Noema malformed-verdict retry classification and wall-clock bound (#1611/#1617)\n"
        )
        baseline_note = (
            "\n- **Diagnostic hardening:** #1617 corrective prompts preserve only trusted structural validator "
            "detail; model-controlled values are redacted, unknown model-output text becomes a stable defect "
            "code, and repeated invalid-model exceptions do not retain the raw model exception as a cause.\n"
        )
        baseline = replace_once(
            baseline,
            baseline_heading,
            baseline_heading + baseline_note,
            "baseline #1617 heading",
        )
    BASELINE.write_text(baseline, encoding="utf-8")

    doctoring = DOCTORING.read_text(encoding="utf-8")
    doctoring_marker = "## Actionable diagnostic boundary"
    if doctoring_marker not in doctoring:
        doctoring += """

## Actionable diagnostic boundary

Corrective prompts need the deterministic *class* of a malformed verdict to repair it,
but do not need arbitrary model-produced values. Trusted structural validator messages
(such as a missing required field or an invalid adversarial-probe outcome class) remain
available after secret scrubbing. Unsupported decision values and unknown model-output
text are redacted to stable diagnostics, and a repeated invalid-model exception is raised
without retaining the raw model exception as an explicit cause. Tests use a sentinel value
to prove it reaches neither the retry prompt nor the final diagnostic.
"""
    DOCTORING.write_text(doctoring, encoding="utf-8")


def main() -> None:
    update_source()
    update_tests()
    update_docs()


if __name__ == "__main__":
    main()
