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


def _extension_run(results: list[dict], *, driver_rules: list | None = None) -> dict:
    """A run shaped like a real CodeQL artifact: 0 driver rules, rules in a query-pack extension."""
    extension_rules = [{"id": f"py/filler-{n}"} for n in range(17)] + [
        {
            "id": "py/incomplete-url-substring-sanitization",
            "properties": {"security-severity": "7.8", "tags": ["security", "external/cwe/cwe-020"]},
            "defaultConfiguration": {"level": "warning"},
        }
    ]
    return {
        "tool": {
            "driver": {"name": "CodeQL", "rules": driver_rules or []},
            "extensions": [{"name": "codeql/python-queries", "rules": extension_rules}],
        },
        "results": results,
    }


def test_gather_findings_resolves_rules_from_the_referenced_extension(tmp_path):
    """Issue #2150: a result whose rule lives in tool.extensions must gate, not fail open."""
    _write_sarif(
        tmp_path / "ext.sarif",
        [
            _extension_run(
                [
                    {
                        "ruleId": "py/incomplete-url-substring-sanitization",
                        "rule": {"id": "py/incomplete-url-substring-sanitization", "index": 17, "toolComponent": {"index": 0}},
                        "message": {"text": "doi check"},
                        "locations": [{"physicalLocation": {"artifactLocation": {"uri": "src/x.py"}, "region": {"startLine": 4}}}],
                    },
                    {
                        "ruleId": "py/incomplete-url-substring-sanitization",
                        "rule": {"index": 17, "toolComponent": {"name": "codeql/python-queries"}},
                        "message": {"text": "by component name"},
                    },
                ]
            )
        ],
    )

    findings, total_results, _ = gate.gather_findings(tmp_path)

    assert total_results == 2
    assert [(f.rule_id, f.score, f.level, f.path, f.line) for f in findings] == [
        ("py/incomplete-url-substring-sanitization", 7.8, "warning", "src/x.py", 4),
        ("py/incomplete-url-substring-sanitization", 7.8, "warning", "unknown", 0),
    ]


def test_gather_findings_keeps_colliding_rule_ids_per_component(tmp_path):
    """The same rule id in the driver and an extension resolves to the referenced component's metadata."""
    _write_sarif(
        tmp_path / "collide.sarif",
        [
            _extension_run(
                [
                    {"ruleId": "shared/id", "message": {"text": "driver copy"}},
                    {"ruleId": "shared/id", "rule": {"toolComponent": {"index": 0}}, "message": {"text": "extension copy"}},
                ],
                driver_rules=[{"id": "shared/id", "defaultConfiguration": {"level": "note"}}],
            )
        ],
    )
    # extension gets a colliding scored rule appended
    payload = json.loads((tmp_path / "collide.sarif").read_text(encoding="utf-8"))
    payload["runs"][0]["tool"]["extensions"][0]["rules"].append(
        {"id": "shared/id", "properties": {"security-severity": "9.1"}}
    )
    (tmp_path / "collide.sarif").write_text(json.dumps(payload), encoding="utf-8")

    findings, _, _ = gate.gather_findings(tmp_path)

    assert [(f.message, f.score) for f in findings] == [("extension copy", 9.1)]


@pytest.mark.parametrize(
    "result",
    [
        {"ruleId": "py/x", "rule": {"index": 17, "toolComponent": {"index": 5}}},
        {"ruleId": "py/x", "rule": {"index": 17, "toolComponent": {"name": "codeql/no-such-pack"}}},
        {"ruleId": "py/x", "rule": {"index": 99, "toolComponent": {"index": 0}}},
        {"ruleId": "py/other", "rule": {"index": 17, "toolComponent": {"index": 0}}},
        {"ruleId": "py/x", "rule": {"id": "py/y", "toolComponent": {"index": 0}}},
        {"rule": {"index": 3, "toolComponent": {"guid": "00000000-0000-0000-0000-000000000000"}}},
        {"ruleId": "py/x", "rule": {"toolComponent": {}}},
    ],
    ids=["bad-component-index", "bad-component-name", "bad-rule-index", "indexed-rule-id-mismatch", "ruleId-vs-rule-id-mismatch", "bad-component-guid", "empty-component-reference"],
)
def test_gather_findings_fails_closed_on_unresolvable_rule_references(tmp_path, result):
    """A rule reference that cannot be resolved, with no severity evidence, gates instead of passing."""
    _write_sarif(tmp_path / "bad.sarif", [_extension_run([dict(result, message={"text": "m"})])])

    findings, _, _ = gate.gather_findings(tmp_path)

    assert len(findings) == 1
    assert findings[0].level == "unresolved-rule"
    assert findings[0].score is None
    assert gate.format_finding(findings[0]).startswith("CODEQL_FINDING rule=")


def test_gather_findings_uses_result_score_even_when_rule_is_unresolvable(tmp_path):
    """Explicit result-level security-severity still decides gating when the rule cannot be resolved."""
    _write_sarif(
        tmp_path / "scored.sarif",
        [_extension_run([{"ruleId": "py/x", "rule": {"toolComponent": {"index": 9}}, "properties": {"security-severity": "1.0"}}])],
    )

    findings, _, _ = gate.gather_findings(tmp_path)

    assert findings == []


def test_gather_findings_gates_an_unreferenced_result_on_its_own_score(tmp_path):
    """A result with no rule reference at all is judged purely on its result-level severity."""
    _write_sarif(tmp_path / "bare.sarif", [_extension_run([{"properties": {"security-severity": "6.0"}}])])

    findings, _, _ = gate.gather_findings(tmp_path)

    assert [(f.rule_id, f.score, f.level) for f in findings] == [("unknown", 6.0, "none")]


def test_gather_findings_leaves_resolved_non_security_extension_rules_alone(tmp_path):
    """A resolved extension rule with no security metadata keeps the existing non-gating semantics."""
    _write_sarif(
        tmp_path / "style.sarif",
        [_extension_run([{"rule": {"index": 3, "toolComponent": {"index": 0}}, "level": "note", "message": {"text": "style"}}])],
    )

    assert gate.gather_findings(tmp_path)[0] == []
