#!/usr/bin/env python3
"""Apply the exact PR #1672 review remediations, then self-delete."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "scripts/ci/noema_review_gate.py"
TELEMETRY_TEST = ROOT / "tests/test_noema_repair_attempt_telemetry.py"
CLASSIFICATION_TEST = ROOT / "tests/test_noema_model_output_failure_classification.py"
DEADLINE_TEST = ROOT / "tests/test_noema_repair_deadline_alarm_safety.py"
DOCTORING = ROOT / "docs/doctoring/noema-repair-attempt-telemetry.md"
CHANGELOG = ROOT / "CHANGELOG.md"
SELF = Path(__file__).resolve()
WORKFLOW = ROOT / ".github/workflows/_temp_pr1672_noema_findings_repair.yml"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    """Replace one exact fragment and refuse drift or ambiguous matches."""
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def regex_replace_once(text: str, pattern: str, replacement: str, label: str) -> str:
    """Replace one regex-delimited block and refuse drift."""
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.DOTALL)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return updated


def remove_test_function(text: str, name: str) -> str:
    """Remove one obsolete top-level test function by exact function name."""
    pattern = rf"\n\ndef {re.escape(name)}\([^\n]*\).*?(?=\n\ndef |\Z)"
    updated, count = re.subn(pattern, "", text, count=1, flags=re.DOTALL)
    if count != 1:
        raise RuntimeError(f"obsolete test {name}: expected one match, found {count}")
    return updated


def repair_source() -> None:
    """Remove the fixed inference deadline and harden repair/telemetry semantics."""
    text = SOURCE.read_text(encoding="utf-8")
    text = replace_once(text, "import signal\n", "", "signal import")

    text = regex_replace_once(
        text,
        r"# NOT DATA-DERIVED -- UNRESOLVED, flagged for an explicit owner decision\..*?NOEMA_REPAIR_DEADLINE_SECONDS = 15 \* 60\n\n",
        "# Repair inference intentionally has no caller-owned fixed wall-clock timeout.\n"
        "# The repair path is exactly one corrective request; contextual-orchestrator\n"
        "# owns provider/request timeout policy and the organization directive defaults\n"
        "# model inference to unlimited unless an audited per-model setting says otherwise.\n\n",
        "arbitrary repair deadline constant",
    )
    text = regex_replace_once(
        text,
        r"\n\nclass NoemaRepairDeadlineExceeded\(TimeoutError\):.*?(?=\n\ndef _stable_failure_diagnostic)",
        "",
        "deadline exception class",
    )

    trailing_helper = '''def _strip_trailing_commas_outside_strings(text: str) -> str:\n    \"\"\"Remove only genuine trailing commas after complete JSON values.\n\n    The scan records only comma indexes that are proven removable instead of\n    appending every input character to a Python list, avoiding list-pointer\n    amplification for large malformed replies. A comma is removable only when\n    the next non-whitespace token closes an object/array *and* the preceding\n    non-whitespace token can terminate a JSON value. This deliberately leaves\n    ``[,]``, ``{,}``, ``[1,,]`` and ``{\"a\":,}`` malformed rather than\n    fabricating empty or missing values. String contents remain opaque.\n    \"\"\"\n    removals: list[int] = []\n    in_string = False\n    escaped = False\n    last_significant: str | None = None\n    length = len(text)\n    for index, char in enumerate(text):\n        if in_string:\n            if escaped:\n                escaped = False\n            elif char == \"\\\\\":\n                escaped = True\n            elif char == '\"':\n                in_string = False\n                last_significant = '\"'\n            continue\n        if char == '\"':\n            in_string = True\n            continue\n        if char == \",\":\n            lookahead = index + 1\n            while lookahead < length and text[lookahead] in \" \\t\\r\\n\":\n                lookahead += 1\n            if (\n                lookahead < length\n                and text[lookahead] in \"}]\"\n                and last_significant not in {None, \"[\", \"{\", \",\", \":\"}\n            ):\n                removals.append(index)\n                continue\n            last_significant = char\n            continue\n        if char not in \" \\t\\r\\n\":\n            last_significant = char\n    if not removals:\n        return text\n    parts: list[str] = []\n    cursor = 0\n    for index in removals:\n        parts.append(text[cursor:index])\n        cursor = index + 1\n    parts.append(text[cursor:])\n    return \"\".join(parts)\n\n\n'''
    text = regex_replace_once(
        text,
        r"def _strip_trailing_commas_outside_strings\(text: str\) -> str:.*?(?=def extract_json_object)",
        trailing_helper,
        "trailing-comma helper",
    )

    text = regex_replace_once(
        text,
        r"\n\n@contextlib\.contextmanager\ndef _repair_wall_clock_deadline\(seconds: float\):.*?(?=\n\nclass StaleHeadDuringRepairRetryError)",
        "",
        "deadline context manager",
    )
    classifier = '''def _classify_attempt_outcome(exc: BaseException) -> str:\n    \"\"\"Return a short, stable outcome class name for attempt telemetry.\"\"\"\n    if isinstance(exc, NoemaModelOutputError):\n        return \"malformed_output\"\n    if isinstance(exc, (urllib.error.URLError, http.client.HTTPException, OSError)):\n        return \"transport_error\"\n    return \"runtime_error\"\n\n\n'''
    text = regex_replace_once(
        text,
        r"def _classify_attempt_outcome\(exc: BaseException\) -> str:.*?(?=def call_llm)",
        classifier,
        "attempt classifier",
    )

    call_start = text.index("def call_llm(")
    try_start = text.index("    try:\n        deadline_context = (", call_start)
    with_marker = "        with deadline_context:\n"
    with_start = text.index(with_marker, try_start)
    except_marker = "    except (RuntimeError, urllib.error.URLError, http.client.HTTPException, OSError) as exc:\n"
    except_start = text.index(except_marker, with_start)
    inner = text[with_start + len(with_marker) : except_start]
    lines = inner.splitlines(keepends=True)
    if any(line.strip() and not line.startswith("    ") for line in lines):
        raise RuntimeError("deadline wrapper: inner block indentation drifted")
    inner = "".join(line[4:] if line.startswith("    ") else line for line in lines)
    text = text[:try_start] + "    try:\n" + inner + text[except_start:]

    text = text.replace("phase_reached", "active_phase")
    text = replace_once(
        text,
        '    # which sub-phase was reached, and (best-effort) which orchestrator/free\n',
        '    # which operation was active at the outcome, and (best-effort) which orchestrator/free\n',
        "phase telemetry comment",
    )
    text = text.replace(
        '    # the original bare "900-second wall-clock deadline" message: it answers\n',
        '    # the original opaque fixed-timeout failure: it answers\n',
    )
    text = text.replace(
        '                f"deadline={NOEMA_REPAIR_DEADLINE_SECONDS:g}s "\n',
        "",
    )
    text = text.replace(
        '                "(one bounded corrective call -- not a retry loop)."\n',
        '                "(one corrective call -- not a retry loop; no fixed inference timeout)."\n',
    )
    text = text.replace(
        '                    "Noema bounded repair transport was exhausted; "\n',
        '                    "Noema repair transport was exhausted; "\n',
    )

    old_primary = '''        if str(fetch_pr(repo, number).get("headRefOid") or "").lower() != expected_head:\n            raise StaleHeadDuringRepairRetryError(\n                "Pull request head changed during review; stale before repair retry."\n            ) from exc\n        print(\n            f"::notice::Noema primary attempt outcome={outcome} phase={active_phase} "\n            f"duration={attempt_elapsed:.1f}s served_model={served_model_note} "\n            f"({current_failure}); starting one bounded repair attempt "\n            f"(deadline={NOEMA_REPAIR_DEADLINE_SECONDS:g}s)."\n        )\n'''
    new_primary = '''        print(\n            f"::notice::Noema primary attempt outcome={outcome} phase={active_phase} "\n            f"duration={attempt_elapsed:.1f}s served_model={served_model_note} "\n            f"({current_failure}); evaluating one corrective repair attempt "\n            "with no caller-owned fixed inference timeout."\n        )\n        if str(fetch_pr(repo, number).get("headRefOid") or "").lower() != expected_head:\n            raise StaleHeadDuringRepairRetryError(\n                "Pull request head changed during review; stale before repair retry."\n            ) from exc\n'''
    text = replace_once(text, old_primary, new_primary, "primary failure telemetry ordering")
    text = replace_once(
        text,
        '        f"::notice::Noema {attempt_kind} attempt outcome=success "\n        f"duration={attempt_elapsed:.1f}s served_model={served_model or \'unknown\'}"\n',
        '        f"::notice::Noema {attempt_kind} attempt outcome=success "\n        f"phase={active_phase} duration={attempt_elapsed:.1f}s "\n        f"served_model={served_model or \'unknown\'}"\n',
        "success phase telemetry",
    )
    text = text.replace(
        "the furthest phase reached (connecting/reading/decoding/\n    validating)",
        "the operation active at the outcome (connecting/reading/decoding/\n    validating)",
    )
    text = text.replace(
        "one bounded repair attempt",
        "one corrective repair attempt",
    )
    SOURCE.write_text(text, encoding="utf-8")


def repair_tests() -> None:
    """Replace deadline contracts with exact no-timeout and parser safety regressions."""
    text = CLASSIFICATION_TEST.read_text(encoding="utf-8")
    for name in (
        "test_total_repair_wall_clock_deadline_interrupts_slow_read",
        "test_repair_wall_clock_deadline_defensive_fail_closed_paths",
        "test_repair_wall_clock_deadline_refuses_existing_process_alarm",
        "test_repair_wall_clock_deadline_rejects_non_main_thread_signal_context",
    ):
        text = remove_test_function(text, name)
    CLASSIFICATION_TEST.write_text(text.rstrip() + "\n", encoding="utf-8")

    if not DEADLINE_TEST.exists():
        raise RuntimeError("deadline-only test file unexpectedly missing")
    DEADLINE_TEST.unlink()

    text = TELEMETRY_TEST.read_text(encoding="utf-8")
    text = replace_once(text, "import signal\nimport time\n", "", "telemetry signal/time imports")
    old_comment = '''def _comment_verdict() -> dict:\n    \"\"\"Return a minimal always-valid verdict (decision=comment needs no probes).\"\"\"\n    return {\"decision\": \"comment\", \"summary\": \"Looks fine.\", \"findings\": []}\n'''
    new_comment = '''def _comment_verdict() -> dict:\n    \"\"\"Return a schema-complete comment verdict with explicit nullable evidence.\"\"\"\n    return {\n        \"decision\": \"comment\",\n        \"summary\": \"Looks fine.\",\n        \"reviewed_lines\": None,\n        \"adversarial_validation\": None,\n        \"findings\": [],\n    }\n'''
    text = replace_once(text, old_comment, new_comment, "schema-complete comment fixture")
    text = regex_replace_once(
        text,
        r"@pytest\.mark\.parametrize\(\n    \(\"exc\", \"expected\"\),\n    \[\n        \(gate\.NoemaRepairDeadlineExceeded\(\"exceeded\"\), \"deadline_exceeded\"\),\n        \(gate\.NoemaModelOutputError\(\"bad\"\), \"malformed_output\"\),\n        \(gate\.NoemaTransportError\(\"bad transport\"\), \"runtime_error\"\),\n        \(RuntimeError\(\"unexpected\"\), \"runtime_error\"\),\n    \],\n\)\ndef test_classify_attempt_outcome_orders_deadline_before_transport\(exc, expected\):.*?    assert gate\._classify_attempt_outcome\(exc\) == expected\n",
        '''@pytest.mark.parametrize(\n    ("exc", "expected"),\n    [\n        (gate.NoemaModelOutputError("bad"), "malformed_output"),\n        (gate.NoemaTransportError("bad transport"), "runtime_error"),\n        (RuntimeError("unexpected"), "runtime_error"),\n    ],\n)\ndef test_classify_attempt_outcome_preserves_model_and_runtime_classes(exc, expected):\n    \"\"\"Typed model-output and unexpected runtime failures stay distinguishable.\"\"\"\n    assert gate._classify_attempt_outcome(exc) == expected\n''',
        "deadline classifier test",
    )
    text = remove_test_function(text, "test_repair_deadline_exceeded_emits_full_attempt_breakdown")
    text = replace_once(
        text,
        '    assert "served_model=some-provider/some-model-v1" in notice\n',
        '    assert "phase=validating" in notice\n    assert "served_model=some-provider/some-model-v1" in notice\n',
        "successful phase assertion",
    )
    text = replace_once(
        text,
        '    assert "served_model=repair-candidate/model-y" in captured\n',
        '    assert "phase=validating" in captured\n    assert "served_model=repair-candidate/model-y" in captured\n',
        "repair success phase assertion",
    )

    additions = r'''

@pytest.mark.parametrize(
    "malformed",
    [
        "[,]",
        "[ , ]",
        '{"findings":[,]}',
        '{"findings":[ , ]}',
        '{"a":,}',
        '[1,,]',
    ],
)
def test_trailing_comma_repair_never_fabricates_missing_values(malformed):
    """Only a comma after a complete JSON value may be removed."""
    assert gate._strip_trailing_commas_outside_strings(malformed) == malformed


@pytest.mark.parametrize(
    ("malformed", "expected"),
    [
        ('{"a":"x",}', '{"a":"x"}'),
        ('{"a":1,}', '{"a":1}'),
        ('{"a":true,}', '{"a":true}'),
        ('{"a":null,}', '{"a":null}'),
        ('{"a":{},}', '{"a":{}}'),
        ('{"a":[],}', '{"a":[]}'),
        ('{"a":[1,],}', '{"a":[1]}'),
    ],
)
def test_trailing_comma_repair_accepts_only_complete_values(malformed, expected):
    """Strings, scalars, literals, objects and arrays can end before a trailing comma."""
    assert gate._strip_trailing_commas_outside_strings(malformed) == expected


def test_repair_path_has_no_caller_owned_fixed_inference_deadline():
    """One corrective request inherits the gateway/provider timeout policy."""
    assert not hasattr(gate, "NOEMA_REPAIR_DEADLINE_SECONDS")
    assert not hasattr(gate, "NoemaRepairDeadlineExceeded")
    assert not hasattr(gate, "_repair_wall_clock_deadline")


def test_stale_head_after_primary_failure_still_emits_attempt_telemetry(monkeypatch, capsys):
    """A completed primary attempt is visible even when a head move suppresses repair."""
    monkeypatch.setenv("NOEMA_LLM_API_URL", "https://llm.example/v1/chat/completions")
    monkeypatch.setenv("NOEMA_LLM_API_KEY", "test-key")
    expected_head = "1" * 40
    live_head = "2" * 40
    monkeypatch.setattr(
        gate.urllib.request.OpenerDirector,
        "open",
        lambda *_a, **_k: _JsonResponse(
            {"choices": [{"message": {"content": json.dumps(_malformed_probe_verdict())}}]}
        ),
    )
    monkeypatch.setattr(gate, "fetch_pr", lambda _repo, _number: {"headRefOid": live_head})

    with pytest.raises(gate.StaleHeadDuringRepairRetryError):
        gate.call_llm(
            "owner/repo",
            7,
            {"title": "test", "headRefOid": expected_head},
            DIFF,
            False,
            expected_head,
            changed_paths=("README.md",),
        )

    notice = capsys.readouterr().out
    assert "::notice::Noema primary attempt outcome=malformed_output" in notice
    assert "phase=validating" in notice
    assert "evaluating one corrective repair attempt" in notice
'''
    if "test_repair_path_has_no_caller_owned_fixed_inference_deadline" in text:
        raise RuntimeError("new telemetry regressions already present unexpectedly")
    TELEMETRY_TEST.write_text(text.rstrip() + additions + "\n", encoding="utf-8")


def repair_traceability() -> None:
    """Record the reviewed design correction without overwriting concurrent main history."""
    doctoring = DOCTORING.read_text(encoding="utf-8")
    marker = "## 2026-09-02 review remediation: remove the arbitrary repair deadline"
    if marker not in doctoring:
        doctoring = doctoring.rstrip() + f'''\n\n{marker}\n\nFresh exact-head review rejected the retained 900-second SIGALRM as a real\ncorrectness/operability defect: a legitimate repair verdict can run longer than\n15 minutes, while ADR-0003 and the product directive put model-request timeout\npolicy at the audited contextual-orchestrator/per-model boundary and default it\nto unlimited. The local Noema gate therefore removes the fixed repair deadline\nentirely. This does **not** create an unbounded local retry loop: `call_llm` still\npermits exactly one corrective request after the primary attempt, and gateway /\nprovider / hosted-job lifecycle controls remain independent failure boundaries.\n\nThe same review found that the local trailing-comma repair could turn `[,]` into\n`[]` and used a per-character Python list. The scanner now records only proven\ntrailing-comma removal indexes and requires a complete preceding JSON value;\nmalformed missing-value arrays/objects remain malformed. Attempt telemetry now\nreports the operation active at outcome on success and failure, and a failed\nprimary attempt is logged before a stale-head check can suppress the corrective\nrequest. Schema tests use complete structured-output fixtures rather than a\nlegacy underspecified mock.\n'''
        DOCTORING.write_text(doctoring, encoding="utf-8")

    changelog = CHANGELOG.read_text(encoding="utf-8")
    entry_marker = "Remove Noema's arbitrary 900-second repair inference deadline"
    if entry_marker not in changelog:
        entry = f'''- **{entry_marker} and close the exact-head telemetry/parser findings.**\n  The repair path remains exactly one corrective request, but no longer installs\n  a caller-owned SIGALRM that can kill a legitimate long semantic review; timeout\n  policy stays at the audited contextual-orchestrator/per-model boundary. The\n  local trailing-comma repair now refuses missing-value shapes such as `[,]` and\n  avoids per-character list amplification, while success/stale-head telemetry and\n  structured-output fixtures cover the reviewed observability contract.\n'''
        changelog = replace_once(
            changelog,
            "## [Unreleased]\n",
            "## [Unreleased]\n" + entry,
            "changelog Unreleased insertion",
        )
        CHANGELOG.write_text(changelog, encoding="utf-8")


def main() -> int:
    """Apply production/test/docs remediation and remove one-shot machinery."""
    repair_source()
    repair_tests()
    repair_traceability()
    if WORKFLOW.exists():
        WORKFLOW.unlink()
    SELF.unlink()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
