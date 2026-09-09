"""Tests for the CodeQL Medium+ SARIF gate shared by codeql-pr.yml's jobs."""

from __future__ import annotations

import json
import runpy
import sys
from pathlib import Path

import pytest

from scripts.ci import codeql_sarif_gate as gate


def _write_sarif(path: Path, runs: list[dict]) -> None:
    path.write_text(json.dumps({"version": "2.1.0", "runs": runs}), encoding="utf-8")


def test_gather_findings_applies_the_medium_plus_rules(tmp_path):
    """Scored, unscored-security, suppressed, and low-severity results are each handled correctly."""
    _write_sarif(
        tmp_path / "a.sarif",
        [
            {
                "tool": {
                    "driver": {
                        "rules": [
                            {"id": "scored-high", "properties": {"security-severity": "7.5"}},
                            {
                                "id": "unscored-security",
                                "properties": {"tags": ["security", "external/cwe/cwe-79"]},
                                "defaultConfiguration": {"level": "warning"},
                            },
                            {"id": "unscored-non-security", "defaultConfiguration": {"level": "error"}},
                        ]
                    }
                },
                "results": [
                    {
                        "ruleId": "scored-high",
                        "message": {"text": "sql injection"},
                        "locations": [{"physicalLocation": {"artifactLocation": {"uri": "a.py"}, "region": {"startLine": 10}}}],
                    },
                    {
                        "ruleId": "unscored-security",
                        "level": "warning",
                        "message": {"text": "xss"},
                    },
                    {
                        "ruleId": "unscored-non-security",
                        "message": {"text": "style nit"},
                    },
                    {
                        "ruleId": "scored-high",
                        "message": {"text": "suppressed dupe"},
                        "suppressions": [{"kind": "inSource"}],
                    },
                    {
                        "ruleId": "scored-low",
                        "properties": {"security-severity": "2.0"},
                        "message": {"text": "low severity"},
                    },
                    "not-a-result",
                ],
            }
        ],
    )

    findings, total_results, file_count = gate.gather_findings(tmp_path)

    assert file_count == 1
    assert total_results == 5
    assert {f.rule_id for f in findings} == {"scored-high", "unscored-security"}
    scored = next(f for f in findings if f.rule_id == "scored-high")
    assert scored.score == 7.5
    assert scored.path == "a.py"
    assert scored.line == 10
    assert scored.message == "sql injection"


def test_gather_findings_resolves_rule_by_index_when_id_is_unknown(tmp_path):
    """A result with no matching ruleId falls back to ruleIndex to find its rule."""
    _write_sarif(
        tmp_path / "b.sarif",
        [
            {
                "tool": {
                    "driver": {
                        "rules": [
                            {"id": "unrelated"},
                            {"id": "indexed-rule", "properties": {"security-severity": "9.0"}},
                        ]
                    }
                },
                "results": [{"ruleIndex": 1, "message": {"text": "indexed"}}],
            }
        ],
    )

    findings, _, _ = gate.gather_findings(tmp_path)

    assert len(findings) == 1
    assert findings[0].rule_id == "indexed-rule"
    assert findings[0].score == 9.0
    assert findings[0].path == "unknown"
    assert findings[0].line == 0


def test_gather_findings_ignores_a_non_dict_rule_at_the_matched_index(tmp_path):
    """A ruleIndex pointing at a malformed (non-dict) rule entry resolves to no rule."""
    _write_sarif(
        tmp_path / "d.sarif",
        [
            {
                "tool": {"driver": {"rules": ["not-a-rule-object"]}},
                "results": [{"ruleIndex": 0, "properties": {"security-severity": "9.0"}}],
            }
        ],
    )

    findings, _, _ = gate.gather_findings(tmp_path)

    assert len(findings) == 1
    assert findings[0].rule_id == "unknown"


def test_gather_findings_defaults_missing_message_and_location(tmp_path):
    """A finding with no message/location text still gates, with safe defaults."""
    _write_sarif(
        tmp_path / "c.sarif",
        [{"results": [{"ruleId": "no-details", "properties": {"security-severity": "5"}}]}],
    )

    findings, _, _ = gate.gather_findings(tmp_path)

    assert findings == [gate.Finding("no-details", 5.0, "none", "unknown", 0, "no message")]


def test_iter_sarif_files_is_sorted(tmp_path):
    """SARIF files are returned in a stable, sorted order."""
    (tmp_path / "z.sarif").write_text("{}", encoding="utf-8")
    (tmp_path / "a.sarif").write_text("{}", encoding="utf-8")
    (tmp_path / "ignore.txt").write_text("nope", encoding="utf-8")

    assert [p.name for p in gate.iter_sarif_files(tmp_path)] == ["a.sarif", "z.sarif"]


def test_format_finding_uses_score_when_present():
    """Findings with a numeric score report security-severity, not level."""
    finding = gate.Finding("rule", 8.0, "warning", "x.py", 3, "msg")

    assert gate.format_finding(finding) == "CODEQL_FINDING rule=rule security-severity=8 path=x.py line=3 message=msg"


def test_format_finding_uses_level_when_unscored():
    """Findings with no score fall back to reporting their SARIF level."""
    finding = gate.Finding("rule", None, "error", "x.py", 3, "msg")

    assert gate.format_finding(finding) == "CODEQL_FINDING rule=rule level=error path=x.py line=3 message=msg"


def test_main_fails_closed_when_no_sarif_produced(tmp_path):
    """An empty SARIF directory means CodeQL produced nothing; fail with a clear reason."""
    with pytest.raises(SystemExit, match="produced no SARIF"):
        gate.main([str(tmp_path)])


def test_main_fails_closed_on_medium_plus_findings(tmp_path, capsys):
    """A Medium+ finding fails the gate and prints CODEQL_SARIF/CODEQL_FINDING evidence lines."""
    _write_sarif(
        tmp_path / "a.sarif",
        [{"results": [{"ruleId": "bad", "properties": {"security-severity": "6"}, "message": {"text": "boom"}}]}],
    )

    with pytest.raises(SystemExit, match="1 unsuppressed Medium\\+ security result"):
        gate.main([str(tmp_path)])

    out = capsys.readouterr().out
    assert "CODEQL_SARIF files=1 results=1 medium_plus=1" in out
    assert "CODEQL_FINDING rule=bad security-severity=6 path=unknown line=0 message=boom" in out


def test_main_passes_when_no_medium_plus_findings(tmp_path, capsys):
    """A clean SARIF directory (no Medium+ findings) passes the gate."""
    _write_sarif(tmp_path / "a.sarif", [{"results": []}])

    assert gate.main([str(tmp_path)]) == 0
    assert "CODEQL_SARIF files=1 results=0 medium_plus=0" in capsys.readouterr().out


def test_main_requires_exactly_one_argument():
    """The CLI exits with usage when not given exactly one SARIF directory."""
    with pytest.raises(SystemExit, match="usage: codeql_sarif_gate.py"):
        gate.main([])


def test_script_entrypoint_exits_with_main_status(tmp_path, monkeypatch):
    """The module entrypoint delegates to main and preserves the exit status."""
    _write_sarif(tmp_path / "a.sarif", [{"results": []}])
    monkeypatch.setattr(sys, "argv", ["codeql_sarif_gate.py", str(tmp_path)])

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_path(str(Path("scripts/ci/codeql_sarif_gate.py")), run_name="__main__")

    assert exc_info.value.code == 0
