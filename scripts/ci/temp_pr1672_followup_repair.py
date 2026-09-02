#!/usr/bin/env python3
"""Apply exact-head follow-up repairs for PR #1672, then self-delete."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "scripts/ci/noema_review_gate.py"
GATE_TEST = ROOT / "tests/test_noema_review_gate.py"
TELEMETRY_TEST = ROOT / "tests/test_noema_repair_attempt_telemetry.py"
DOCTORING = ROOT / "docs/doctoring/noema-repair-attempt-telemetry.md"
CHANGELOG = ROOT / "CHANGELOG.md"
SELF = Path(__file__).resolve()


def regex_replace_once(text: str, pattern: str, replacement: str, label: str) -> str:
    """Replace exactly one regex-delimited block and refuse source drift."""
    updated, count = re.subn(pattern, lambda _match: replacement, text, count=1, flags=re.DOTALL)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return updated


def repair_validator_diagnostics(text: str) -> str:
    """Restore location-rich diagnostics while retaining shared probe-count authority."""
    helpers_and_validator = r'''def _entry_ordinal(position: int, total: int) -> str:
    """Return an unambiguous array-position label for a validated JSON entry."""
    return f"entry {position}/{total} (array index {position - 1}, not a source line)"


def _format_location(path: Any, line: Any, side: Any) -> str:
    """Format one rejected path/line/side citation without lossy coercion."""
    return f"path={path!r} line={line!r} side={side!r}"


def _nearby_changed_locations(
    locations: set[tuple[str, int, str]], path: Any, line: Any, *, limit: int = 5
) -> str:
    """Return nearest real changed locations sharing the rejected path."""
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
    """Reject formal verdicts without changed-line and adversarial evidence."""
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
    if "def _entry_ordinal(" in text:
        # A concurrent writer may already have restored the helper; only replace the validator.
        prefix = text[: text.index("def _entry_ordinal(")]
        required_start = text.index("def _required_probe_count(")
        if required_start > len(prefix):
            # _required_probe_count precedes the helper on the intended tree; preserve it.
            pass
        start = text.index("def _entry_ordinal(")
        end = text.index("def truncate_text(", start)
        return text[:start] + helpers_and_validator + "\n\n\n" + text[end:]
    marker = "def validate_substantive_verdict("
    if text.count(marker) != 1:
        raise RuntimeError("validator anchor drifted")
    return regex_replace_once(
        text,
        r"def validate_substantive_verdict\(.*?(?=def truncate_text\()",
        helpers_and_validator + "\n\n\n",
        "validator diagnostics",
    )


def repair_served_model(text: str) -> str:
    """Make telemetry model identifiers bounded, scrubbed and always printable."""
    replacement = r'''def _extract_served_model(raw: str) -> str | None:
    """Best-effort read of a bounded, scrubbed and log-safe serving model id."""
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    served = data.get("model")
    if not isinstance(served, str) or not served.strip():
        return None
    bounded = served.strip()[:200]
    scrubbed = scrub_sensitive_data(bounded)
    safe = "".join(
        char if char.isprintable() else f"\\u{ord(char):04x}"
        for char in scrubbed
    )
    return safe[:200] or None
'''
    return regex_replace_once(
        text,
        r"def _extract_served_model\(raw: str\) -> str \| None:.*?(?=def _truthy_env\()",
        replacement + "\n\n\n",
        "served-model log safety",
    )


def append_regressions() -> None:
    """Add focused executable coverage for both newly reviewed defects."""
    gate_text = GATE_TEST.read_text(encoding="utf-8")
    marker = "test_pr1672_invalid_review_location_reports_nearby_changed_lines"
    if marker not in gate_text:
        gate_text = gate_text.rstrip() + r'''


def test_pr1672_invalid_review_location_reports_nearby_changed_lines():
    """A repair prompt gets the rejected citation and nearest valid changed line."""
    diff = """diff --git a/tool.py b/tool.py
--- a/tool.py
+++ b/tool.py
@@ -1 +1 @@
-old
+new
"""
    verdict = {
        "decision": "approve",
        "summary": "checked",
        "reviewed_lines": [
            {"path": "tool.py", "line": 99, "side": "RIGHT", "analysis": "checked"}
        ],
        "adversarial_validation": {
            "status": "passed",
            "residual_risk": "none",
            "probes": [
                {
                    "path": "tool.py",
                    "line": 1,
                    "side": "RIGHT",
                    "hypothesis": "h1",
                    "attack_or_counterexample": "a1",
                    "evidence": "e1",
                    "outcome": "falsified",
                },
                {
                    "path": "tool.py",
                    "line": 1,
                    "side": "LEFT",
                    "hypothesis": "h2",
                    "attack_or_counterexample": "a2",
                    "evidence": "e2",
                    "outcome": "falsified",
                },
            ],
        },
        "findings": [],
    }
    with pytest.raises(noema.NoemaModelOutputError) as exc_info:
        noema.validate_substantive_verdict(verdict, diff, changed_paths=("tool.py",))
    message = str(exc_info.value)
    assert "entry 1/1 (array index 0, not a source line)" in message
    assert "path='tool.py' line=99 side='RIGHT'" in message
    assert "nearest changed lines for tool.py: tool.py:1 (RIGHT), tool.py:1 (LEFT)" in message


def test_pr1672_invalid_probe_location_reports_nearby_changed_lines():
    """A rejected adversarial probe carries the same corrective location evidence."""
    diff = """diff --git a/tool.py b/tool.py
--- a/tool.py
+++ b/tool.py
@@ -1 +1 @@
-old
+new
"""
    verdict = {
        "decision": "approve",
        "summary": "checked",
        "reviewed_lines": [
            {"path": "tool.py", "line": 1, "side": "RIGHT", "analysis": "checked"}
        ],
        "adversarial_validation": {
            "status": "passed",
            "residual_risk": "none",
            "probes": [
                {
                    "path": "tool.py",
                    "line": 99,
                    "side": "RIGHT",
                    "hypothesis": "h1",
                    "attack_or_counterexample": "a1",
                    "evidence": "e1",
                    "outcome": "falsified",
                },
                {
                    "path": "tool.py",
                    "line": 1,
                    "side": "LEFT",
                    "hypothesis": "h2",
                    "attack_or_counterexample": "a2",
                    "evidence": "e2",
                    "outcome": "falsified",
                },
            ],
        },
        "findings": [],
    }
    with pytest.raises(noema.NoemaModelOutputError) as exc_info:
        noema.validate_substantive_verdict(verdict, diff, changed_paths=("tool.py",))
    message = str(exc_info.value)
    assert "adversarial probe entry 1/2" in message
    assert "path='tool.py' line=99 side='RIGHT'" in message
    assert "nearest changed lines for tool.py" in message
'''
        GATE_TEST.write_text(gate_text.rstrip() + "\n", encoding="utf-8")

    telemetry = TELEMETRY_TEST.read_text(encoding="utf-8")
    marker = "test_pr1672_served_model_surrogate_is_safe_on_success"
    if marker not in telemetry:
        telemetry = telemetry.rstrip() + r'''


def test_pr1672_served_model_surrogate_is_safe_on_success(monkeypatch, capsys):
    """A lone surrogate in the serving model cannot crash success telemetry."""
    monkeypatch.setenv("NOEMA_LLM_API_URL", "https://llm.example/v1/chat/completions")
    monkeypatch.setenv("NOEMA_LLM_API_KEY", "test-key")
    head_sha = "3" * 40
    payload = {
        "model": "provider/\ud800\nmodel",
        "choices": [{"message": {"content": json.dumps(_comment_verdict())}}],
    }
    monkeypatch.setattr(
        gate.urllib.request.OpenerDirector,
        "open",
        lambda *_a, **_k: _JsonResponse(payload),
    )
    monkeypatch.setattr(gate, "fetch_pr", lambda _repo, _number: {"headRefOid": head_sha})
    assert gate.call_llm(
        "owner/repo",
        7,
        {"title": "test", "headRefOid": head_sha},
        DIFF,
        False,
        head_sha,
        changed_paths=("README.md",),
    ) == _comment_verdict()
    notice = capsys.readouterr().out
    notice.encode("utf-8")
    assert "served_model=provider/\\ud800\\u000amodel" in notice


def test_pr1672_served_model_surrogate_is_safe_on_failure(monkeypatch, capsys):
    """The same untrusted model id cannot mask a malformed-output failure."""
    monkeypatch.setenv("NOEMA_LLM_API_URL", "https://llm.example/v1/chat/completions")
    monkeypatch.setenv("NOEMA_LLM_API_KEY", "test-key")
    head_sha = "4" * 40
    payload = {
        "model": "provider/\ud800\tmodel",
        "choices": [{"message": {"content": "not-json"}}],
    }
    monkeypatch.setattr(
        gate.urllib.request.OpenerDirector,
        "open",
        lambda *_a, **_k: _JsonResponse(payload),
    )
    monkeypatch.setattr(gate, "fetch_pr", lambda _repo, _number: {"headRefOid": head_sha})
    with pytest.raises(RuntimeError):
        gate.call_llm(
            "owner/repo",
            7,
            {"title": "test", "headRefOid": head_sha},
            DIFF,
            False,
            head_sha,
            changed_paths=("README.md",),
        )
    notice = capsys.readouterr().out
    notice.encode("utf-8")
    assert "served_model=provider/\\ud800\\u0009model" in notice
'''
        TELEMETRY_TEST.write_text(telemetry.rstrip() + "\n", encoding="utf-8")


def repair_traceability() -> None:
    """Record exact-head follow-up findings without replacing executable proof."""
    doctoring = DOCTORING.read_text(encoding="utf-8")
    marker = "## 2026-09-02 exact-head follow-up: corrective diagnostics and log-safe model ids"
    if marker not in doctoring:
        doctoring = doctoring.rstrip() + f"""\n\n{marker}\n\nFresh review found two additional correctness defects on the same writer head.\nRejected `reviewed_lines`/probe citations had lost the merge-base diagnostic\ncontext needed by the corrective model, so the validator again reports the\narray ordinal, rejected path/line/side and nearest real changed lines. The\nserving-model telemetry field is untrusted gateway output; escaped lone\nsurrogates and control characters are now scrubbed into bounded printable\ntext before any Actions annotation is emitted. Focused success/failure\nregressions prove that telemetry cannot mask the underlying review outcome.\n"""
        DOCTORING.write_text(doctoring, encoding="utf-8")

    changelog = CHANGELOG.read_text(encoding="utf-8")
    marker = "Restore Noema corrective-location diagnostics and log-safe served-model telemetry"
    if marker not in changelog:
        entry = (
            f"- **{marker}.** Rejected citations again include exact location and nearest "
            "changed-line evidence for the one corrective request, while untrusted model identifiers "
            "cannot inject control characters or lone surrogates into Actions telemetry.\n"
        )
        if "## [Unreleased]\n" not in changelog:
            raise RuntimeError("CHANGELOG Unreleased anchor missing")
        changelog = changelog.replace("## [Unreleased]\n", "## [Unreleased]\n" + entry, 1)
        CHANGELOG.write_text(changelog, encoding="utf-8")


def main() -> int:
    """Apply source/tests/docs repair and remove this one-shot helper."""
    text = SOURCE.read_text(encoding="utf-8")
    text = repair_validator_diagnostics(text)
    text = repair_served_model(text)
    SOURCE.write_text(text, encoding="utf-8")
    append_regressions()
    repair_traceability()
    SELF.unlink()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
