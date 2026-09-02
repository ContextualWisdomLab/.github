#!/usr/bin/env python3
"""Repair current-head PR #1672 diagnostics/telemetry findings and retire one-shots."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "scripts/ci/noema_review_gate.py"
TESTS = ROOT / "tests/test_noema_repair_attempt_telemetry.py"
DOCTORING = ROOT / "docs/doctoring/noema-repair-attempt-telemetry.md"
CHANGELOG = ROOT / "CHANGELOG.md"
SELF = Path(__file__).resolve()
V2_WORKFLOW = ROOT / ".github/workflows/_temp_pr1672_current_findings_v2.yml"
OLD_WORKFLOW = ROOT / ".github/workflows/_temp_pr1672_noema_findings_repair.yml"
OLD_DRIVER = ROOT / "scripts/ci/temp_pr1672_noema_findings_repair.py"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    """Replace one exact fragment and fail closed on drift."""
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def repair_source() -> None:
    """Restore current-main citation diagnostics and harden untrusted telemetry text."""
    text = SOURCE.read_text(encoding="utf-8")

    if "def _entry_ordinal(" not in text:
        helpers = '''def _entry_ordinal(position: int, total: int) -> str:\n    \"\"\"Describe an array entry without implying it is a source-code line.\"\"\"\n    return f\"entry {position}/{total} (array index {position - 1}, not a source line)\"\n\n\ndef _format_location(path: Any, line: Any, side: Any) -> str:\n    \"\"\"Format one rejected citation without silently coercing malformed fields.\"\"\"\n    return f\"path={path!r} line={line!r} side={side!r}\"\n\n\ndef _nearby_changed_locations(\n    locations: set[tuple[str, int, str]], path: Any, line: Any, *, limit: int = 5\n) -> str:\n    \"\"\"Return a bounded nearest-line hint for a rejected same-path citation.\"\"\"\n    if not isinstance(path, str):\n        return \"\"\n    same_path = [location for location in locations if location[0] == path]\n    if not same_path:\n        return \"\"\n    if isinstance(line, int):\n        same_path.sort(key=lambda location: (abs(location[1] - line), location[1], location[2]))\n    else:\n        same_path.sort(key=lambda location: (location[1], location[2]))\n    sample = \", \".join(f\"{p}:{ln} ({s})\" for p, ln, s in same_path[:limit])\n    remaining = len(same_path) - limit\n    more = f\", +{remaining} more\" if remaining > 0 else \"\"\n    return f\"; nearest changed lines for {path}: {sample}{more}\"\n\n\n'''
        marker = "def validate_substantive_verdict(\n"
        if text.count(marker) != 1:
            raise RuntimeError("citation helper insertion marker drifted")
        text = text.replace(marker, helpers + marker, 1)

    old_reviewed = '''    reviewed_lines = verdict.get("reviewed_lines")\n    if not isinstance(reviewed_lines, list) or not reviewed_lines:\n        raise NoemaModelOutputError("Noema formal verdict requires at least one reviewed changed line")\n    for index, reviewed in enumerate(reviewed_lines, start=1):\n        if not isinstance(reviewed, dict):\n            raise NoemaModelOutputError(f"Noema reviewed line {index} must be an object")\n        location = (reviewed.get("path"), reviewed.get("line"), reviewed.get("side"))\n        if location not in locations:\n            raise NoemaModelOutputError(f"Noema reviewed line {index} is not an exact changed-side line")\n        analysis = reviewed.get("analysis")\n        if not isinstance(analysis, str) or not analysis.strip():\n            raise NoemaModelOutputError(f"Noema reviewed line {index} requires concrete analysis")\n'''
    new_reviewed = '''    reviewed_lines = verdict.get("reviewed_lines")\n    if not isinstance(reviewed_lines, list) or not reviewed_lines:\n        raise NoemaModelOutputError("Noema formal verdict requires at least one reviewed changed line")\n    reviewed_total = len(reviewed_lines)\n    for position, reviewed in enumerate(reviewed_lines, start=1):\n        entry = _entry_ordinal(position, reviewed_total)\n        if not isinstance(reviewed, dict):\n            raise NoemaModelOutputError(f"Noema reviewed line {entry} must be an object")\n        location = (reviewed.get("path"), reviewed.get("line"), reviewed.get("side"))\n        if location not in locations:\n            path, line, side = location\n            raise NoemaModelOutputError(\n                f"Noema reviewed line {entry} cites {_format_location(path, line, side)}, "\n                f"which is not an exact changed-side line"\n                f"{_nearby_changed_locations(locations, path, line)}"\n            )\n        analysis = reviewed.get("analysis")\n        if not isinstance(analysis, str) or not analysis.strip():\n            raise NoemaModelOutputError(f"Noema reviewed line {entry} requires concrete analysis")\n'''
    if old_reviewed in text:
        text = replace_once(text, old_reviewed, new_reviewed, "reviewed-line diagnostics")
    elif new_reviewed not in text:
        raise RuntimeError("reviewed-line diagnostic block drifted")

    old_probes = '''    confirmed: set[tuple[str, int, str]] = set()\n    identities: set[tuple[Any, ...]] = set()\n    for index, probe in enumerate(probes, start=1):\n        if not isinstance(probe, dict):\n            raise NoemaModelOutputError(f"Noema adversarial probe {index} must be an object")\n        location = (probe.get("path"), probe.get("line"), probe.get("side"))\n        if location not in locations:\n            raise NoemaModelOutputError(f"Noema adversarial probe {index} is not an exact changed-side line")\n        for field in ("hypothesis", "attack_or_counterexample", "evidence"):\n            value = probe.get(field)\n            if not isinstance(value, str) or not value.strip():\n                raise NoemaModelOutputError(f"Noema adversarial probe {index} requires {field}")\n        outcome = probe.get("outcome")\n        if outcome not in {"falsified", "confirmed"}:\n            raise NoemaModelOutputError(f"Noema adversarial probe {index} outcome must be falsified or confirmed")\n        identity = (*location, probe["hypothesis"].strip().casefold(), probe["attack_or_counterexample"].strip().casefold())\n        if identity in identities:\n            raise NoemaModelOutputError(f"Noema adversarial probe {index} duplicates an earlier probe")\n'''
    new_probes = '''    confirmed: set[tuple[str, int, str]] = set()\n    identities: set[tuple[Any, ...]] = set()\n    probes_total = len(probes)\n    for position, probe in enumerate(probes, start=1):\n        entry = _entry_ordinal(position, probes_total)\n        if not isinstance(probe, dict):\n            raise NoemaModelOutputError(f"Noema adversarial probe {entry} must be an object")\n        location = (probe.get("path"), probe.get("line"), probe.get("side"))\n        if location not in locations:\n            path, line, side = location\n            raise NoemaModelOutputError(\n                f"Noema adversarial probe {entry} cites {_format_location(path, line, side)}, "\n                f"which is not an exact changed-side line"\n                f"{_nearby_changed_locations(locations, path, line)}"\n            )\n        for field in ("hypothesis", "attack_or_counterexample", "evidence"):\n            value = probe.get(field)\n            if not isinstance(value, str) or not value.strip():\n                raise NoemaModelOutputError(f"Noema adversarial probe {entry} requires {field}")\n        outcome = probe.get("outcome")\n        if outcome not in {"falsified", "confirmed"}:\n            raise NoemaModelOutputError(f"Noema adversarial probe {entry} outcome must be falsified or confirmed")\n        identity = (*location, probe["hypothesis"].strip().casefold(), probe["attack_or_counterexample"].strip().casefold())\n        if identity in identities:\n            raise NoemaModelOutputError(f"Noema adversarial probe {entry} duplicates an earlier probe")\n'''
    if old_probes in text:
        text = replace_once(text, old_probes, new_probes, "probe diagnostics")
    elif new_probes not in text:
        raise RuntimeError("probe diagnostic block drifted")

    old_model = '    return scrub_sensitive_data(served.strip()[:200])\n'
    new_model = '''    scrubbed = scrub_sensitive_data(served.strip()[:200])\n    safe_parts: list[str] = []\n    used = 0\n    for char in scrubbed:\n        codepoint = ord(char)\n        if char.isprintable() and not 0xD800 <= codepoint <= 0xDFFF:\n            fragment = char\n        elif codepoint <= 0xFFFF:\n            fragment = f"\\\\u{codepoint:04x}"\n        else:\n            fragment = f"\\\\U{codepoint:08x}"\n        if used + len(fragment) > 200:\n            break\n        safe_parts.append(fragment)\n        used += len(fragment)\n    return "".join(safe_parts) or None\n'''
    text = replace_once(text, old_model, new_model, "served-model log safety")

    old_notice = '''        print(\n            "::notice::Noema local trailing-comma JSON repair recovered an "\n            "otherwise-malformed response; no network repair retry was needed."\n        )\n'''
    new_notice = '''        print(\n            "::notice::Noema local trailing-comma JSON repair recovered JSON syntax "\n            "before verdict validation; semantic validation may still require the "\n            "single corrective network repair."\n        )\n'''
    text = replace_once(text, old_notice, new_notice, "local-repair telemetry wording")
    SOURCE.write_text(text, encoding="utf-8")


def repair_tests() -> None:
    """Add regressions for restored diagnostics, safe model telemetry, and notice truthfulness."""
    text = TESTS.read_text(encoding="utf-8")
    marker = "test_pr1672_rejected_citations_preserve_current_main_diagnostics"
    if marker in text:
        return
    additions = r'''


def _formal_verdict(*, reviewed_line: int = 1, probe_line: int = 1) -> dict:
    """Return a minimal formal verdict whose citation lines are caller-selectable."""
    return {
        "decision": "approve",
        "summary": "Reviewed the exact change.",
        "reviewed_lines": [
            {"path": "README.md", "line": reviewed_line, "side": "RIGHT", "analysis": "Checked."}
        ],
        "adversarial_validation": {
            "status": "passed",
            "residual_risk": "None identified.",
            "probes": [
                {
                    "path": "README.md",
                    "line": probe_line,
                    "side": "RIGHT",
                    "hypothesis": "The edit could regress behavior.",
                    "attack_or_counterexample": "Inspect the changed line.",
                    "evidence": "The exact replacement is bounded.",
                    "outcome": "falsified",
                }
            ],
        },
        "findings": [],
    }


def test_pr1672_rejected_citations_preserve_current_main_diagnostics():
    """Repair prompts retain the rejected location and nearest valid changed line."""
    with pytest.raises(gate.NoemaModelOutputError) as reviewed_exc:
        gate.validate_substantive_verdict(_formal_verdict(reviewed_line=2), DIFF, ("README.md",))
    reviewed = str(reviewed_exc.value)
    assert "entry 1/1 (array index 0, not a source line)" in reviewed
    assert "path='README.md' line=2 side='RIGHT'" in reviewed
    assert "nearest changed lines for README.md: README.md:1 (RIGHT)" in reviewed

    with pytest.raises(gate.NoemaModelOutputError) as probe_exc:
        gate.validate_substantive_verdict(_formal_verdict(probe_line=2), DIFF, ("README.md",))
    probe = str(probe_exc.value)
    assert "entry 1/1 (array index 0, not a source line)" in probe
    assert "path='README.md' line=2 side='RIGHT'" in probe
    assert "nearest changed lines for README.md: README.md:1 (RIGHT)" in probe


def test_pr1672_served_model_is_utf8_print_safe_and_bounded():
    """Escaped lone surrogates and controls cannot break Actions annotations."""
    served = gate._extract_served_model('{"model":"provider/\\ud800/\\u0001/model"}')
    assert served is not None
    served.encode("utf-8")
    assert "\\ud800" in served
    assert "\\u0001" in served
    assert len(served) <= 200


def test_pr1672_success_telemetry_survives_lone_surrogate_model(monkeypatch, capsys):
    """A successful response cannot be masked by an unprintable served-model field."""
    monkeypatch.setenv("NOEMA_LLM_API_URL", "https://llm.example/v1/chat/completions")
    monkeypatch.setenv("NOEMA_LLM_API_KEY", "test-key")
    head_sha = "3" * 40
    monkeypatch.setattr(
        gate.urllib.request.OpenerDirector,
        "open",
        lambda *_a, **_k: _JsonResponse(
            {"model": "provider/\ud800/model", "choices": [{"message": {"content": json.dumps(_comment_verdict())}}]}
        ),
    )
    monkeypatch.setattr(gate, "fetch_pr", lambda _repo, _number: {"headRefOid": head_sha})
    assert gate.call_llm(
        "owner/repo", 7, {"title": "test", "headRefOid": head_sha}, DIFF, False, head_sha,
        changed_paths=("README.md",),
    )["decision"] == "comment"
    output = capsys.readouterr().out
    output.encode("utf-8")
    assert "served_model=provider/\\ud800/model" in output


def test_pr1672_failure_telemetry_survives_lone_surrogate_model(monkeypatch, capsys):
    """A malformed primary response still reports its safe model before repair."""
    monkeypatch.setenv("NOEMA_LLM_API_URL", "https://llm.example/v1/chat/completions")
    monkeypatch.setenv("NOEMA_LLM_API_KEY", "test-key")
    head_sha = "4" * 40
    responses = iter(
        [
            _JsonResponse(
                {"model": "provider/\ud800/model", "choices": [{"message": {"content": json.dumps(_malformed_probe_verdict())}}]}
            ),
            _JsonResponse(
                {"model": "provider/repair", "choices": [{"message": {"content": json.dumps(_comment_verdict())}}]}
            ),
        ]
    )
    monkeypatch.setattr(gate.urllib.request.OpenerDirector, "open", lambda *_a, **_k: next(responses))
    monkeypatch.setattr(gate, "fetch_pr", lambda _repo, _number: {"headRefOid": head_sha})
    assert gate.call_llm(
        "owner/repo", 7, {"title": "test", "headRefOid": head_sha}, DIFF, False, head_sha,
        changed_paths=("README.md",),
    )["decision"] == "comment"
    output = capsys.readouterr().out
    output.encode("utf-8")
    assert "served_model=provider/\\ud800/model" in output
    assert "outcome=malformed_output" in output


def test_pr1672_local_repair_notice_does_not_prejudge_semantic_validation(capsys):
    """Syntax repair telemetry does not claim the later corrective request is unnecessary."""
    assert gate.extract_json_object('{"decision":"comment","summary":"ok","findings":[],}')["decision"] == "comment"
    notice = capsys.readouterr().out
    assert "before verdict validation" in notice
    assert "semantic validation may still require" in notice
    assert "no network repair retry was needed" not in notice
'''
    TESTS.write_text((text.rstrip() + additions).rstrip() + "\n", encoding="utf-8")


def repair_traceability() -> None:
    """Record the exact current-head remediation without changing scientific behavior."""
    doctoring = DOCTORING.read_text(encoding="utf-8")
    marker = "## 2026-09-02 current-head follow-up: preserve diagnostics and log safety"
    if marker not in doctoring:
        doctoring += f'''\n{marker}\n\nThe current-head review found three additional control-plane defects. The PR had\ndropped protected-main's rejected-citation diagnostics while introducing the\nshared probe-count helper; this follow-up restores the entry ordinal, rejected\npath/line/side, and bounded nearest-changed-line hints without rolling back the\nnew helper. The untrusted top-level `model` telemetry field is now converted to\na UTF-8-print-safe, 200-character-bounded annotation value so escaped lone\nsurrogates or controls cannot mask a valid review or its real failure. Finally,\nlocal trailing-comma recovery now says only that JSON syntax was recovered\nbefore verdict validation; it no longer claims that a later semantic failure\nwill not need the single corrective network request.\n'''
        DOCTORING.write_text(doctoring, encoding="utf-8")

    changelog = CHANGELOG.read_text(encoding="utf-8")
    marker = "Preserve Noema rejected-citation diagnostics and harden served-model telemetry"
    if marker not in changelog:
        entry = f'''- **{marker}.** Restore protected-main's precise rejected-location and\n  nearest-changed-line feedback alongside the shared probe-count contract, encode\n  untrusted served-model text into a bounded print-safe annotation value, and make\n  local JSON-repair telemetry truthful about post-parse semantic validation.\n'''
        changelog = replace_once(
            changelog,
            "## [Unreleased]\n",
            "## [Unreleased]\n" + entry,
            "changelog follow-up",
        )
        CHANGELOG.write_text(changelog, encoding="utf-8")


def retire_one_shots() -> None:
    """Remove every temporary repair artifact after this replacement has applied."""
    for path in (OLD_WORKFLOW, OLD_DRIVER, V2_WORKFLOW, SELF):
        if path.exists():
            path.unlink()


def main() -> int:
    """Apply current-head remediations and remove temporary repair machinery."""
    repair_source()
    repair_tests()
    repair_traceability()
    retire_one_shots()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
