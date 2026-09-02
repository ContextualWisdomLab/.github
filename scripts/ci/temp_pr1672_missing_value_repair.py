#!/usr/bin/env python3
"""Apply PR #1672 missing-value JSON safeguards, then retire temporary helpers."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "scripts/ci/noema_review_gate.py"
TESTS = ROOT / "tests/test_noema_repair_attempt_telemetry.py"
DOCTORING = ROOT / "docs/doctoring/noema-repair-attempt-telemetry.md"
CHANGELOG = ROOT / "CHANGELOG.md"
FOLLOWUP_DRIVER = ROOT / "scripts/ci/temp_pr1672_followup_repair.py"
SELF = Path(__file__).resolve()


def repair_source() -> None:
    """Restrict trailing-comma repair to commas following complete JSON values."""
    text = SOURCE.read_text(encoding="utf-8")
    start = text.index("def _strip_trailing_commas_outside_strings(text: str) -> str:")
    end = text.index("\ndef extract_json_object(text: str) -> dict[str, Any]:", start)
    replacement = '''def _comma_follows_complete_json_value(text: str, comma_index: int) -> bool:\n    \"\"\"Return whether the comma is preceded by a complete JSON value token.\"\"\"\n    previous_index = comma_index - 1\n    while previous_index >= 0 and text[previous_index] in \" \\t\\r\\n\":\n        previous_index -= 1\n    if previous_index < 0:\n        return False\n    previous_character = text[previous_index]\n    if previous_character in '\"}]' or previous_character.isdigit():\n        return True\n    for literal_value in (\"true\", \"false\", \"null\"):\n        literal_start = previous_index - len(literal_value) + 1\n        if literal_start < 0 or text[literal_start : previous_index + 1] != literal_value:\n            continue\n        if literal_start == 0:\n            return True\n        token_prefix = text[literal_start - 1]\n        if token_prefix in \" \\t\\r\\n:[,{\":\n            return True\n    return False\n\n\ndef _strip_trailing_commas_outside_strings(text: str) -> str:\n    \"\"\"Remove only true trailing commas after complete JSON values.\n\n    Missing-value forms such as ``[,]``, ``{,}``, ``[1,,]`` and\n    ``{\"a\":,}`` are intentionally left malformed and fail closed.\n    \"\"\"\n    result: list[str] = []\n    in_string = False\n    escaped = False\n    index = 0\n    length = len(text)\n    while index < length:\n        char = text[index]\n        if in_string:\n            result.append(char)\n            if escaped:\n                escaped = False\n            elif char == \"\\\\\":\n                escaped = True\n            elif char == '\"':\n                in_string = False\n            index += 1\n            continue\n        if char == '\"':\n            in_string = True\n            result.append(char)\n            index += 1\n            continue\n        if char == \",\":\n            lookahead = index + 1\n            while lookahead < length and text[lookahead] in \" \\t\\r\\n\":\n                lookahead += 1\n            if (\n                lookahead < length\n                and text[lookahead] in \"}]\"\n                and _comma_follows_complete_json_value(text, index)\n            ):\n                index += 1\n                continue\n        result.append(char)\n        index += 1\n    return \"\".join(result)\n\n'''
    SOURCE.write_text(text[:start] + replacement + text[end + 1 :], encoding="utf-8")


def repair_tests() -> None:
    """Add focused regressions for accepted trailing commas and rejected missing values."""
    text = TESTS.read_text(encoding="utf-8")
    marker = "test_pr1672_trailing_comma_repair_requires_complete_json_value"
    if marker in text:
        return
    additions = r'''


def test_pr1672_trailing_comma_repair_requires_complete_json_value():
    """Only commas following complete JSON values are eligible for local repair."""
    accepted = {
        '{"a":"text",}': '{"a":"text"}',
        '{"a":1,}': '{"a":1}',
        '{"a":true,}': '{"a":true}',
        '{"a":false,}': '{"a":false}',
        '{"a":null,}': '{"a":null}',
        '{"a":{},}': '{"a":{}}',
        '{"a":[],}': '{"a":[]}',
    }
    for malformed_json, expected_json in accepted.items():
        assert gate._strip_trailing_commas_outside_strings(malformed_json) == expected_json
        assert json.loads(expected_json) == json.loads(
            gate._strip_trailing_commas_outside_strings(malformed_json)
        )


@pytest.mark.parametrize("malformed_json", ["[,]", "{,}", "[1,,]", '{"a":,}'])
def test_pr1672_trailing_comma_repair_preserves_missing_value_failures(malformed_json):
    """Missing values stay malformed instead of being silently deleted."""
    repaired_json = gate._strip_trailing_commas_outside_strings(malformed_json)
    assert repaired_json == malformed_json
    with pytest.raises(json.JSONDecodeError):
        json.loads(repaired_json)
'''
    TESTS.write_text((text.rstrip() + additions).rstrip() + "\n", encoding="utf-8")


def repair_traceability() -> None:
    """Record the fail-closed missing-value contract in existing traceability docs."""
    doctoring = DOCTORING.read_text(encoding="utf-8")
    marker = "## 2026-09-02 follow-up: trailing-comma repair must not invent missing values"
    if marker not in doctoring:
        doctoring += (
            f"\n\n{marker}\n\n"
            "Exact-head review proved that stripping every comma before a closing bracket "
            "could turn missing-value JSON into a different valid value. The local repair "
            "now removes a trailing comma only after a complete string, number, literal, "
            "object, or array; missing-value shapes remain malformed and fail closed.\n"
        )
        DOCTORING.write_text(doctoring, encoding="utf-8")

    changelog = CHANGELOG.read_text(encoding="utf-8")
    marker = "Keep Noema local JSON repair fail-closed for missing values"
    if marker not in changelog:
        entry = (
            f"- **{marker}.** Restrict trailing-comma recovery to commas following complete "
            "JSON values so missing-value forms remain invalid instead of being silently erased.\n"
        )
        anchor = "## [Unreleased]\n"
        if changelog.count(anchor) != 1:
            raise RuntimeError("CHANGELOG Unreleased anchor drifted")
        changelog = changelog.replace(anchor, anchor + entry, 1)
        CHANGELOG.write_text(changelog, encoding="utf-8")


def main() -> int:
    """Apply the repair and remove obsolete temporary helpers before coverage runs."""
    repair_source()
    repair_tests()
    repair_traceability()
    for temporary_path in (FOLLOWUP_DRIVER, SELF):
        if temporary_path.exists():
            temporary_path.unlink()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
