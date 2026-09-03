"""Fail closed on unsuppressed Medium+ CodeQL SARIF findings.

Extracted from the duplicated inline Python previously embedded in both the
``analyze-head`` and ``analyze-merge`` jobs of ``codeql-pr.yml`` so the same
severity gate can be reused by the dispatch-based rewrite proposed in
ContextualWisdomLab/.github#1772 without a third copy of this logic.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, NamedTuple

MEDIUM_PLUS_SCORE = 4.0
SEVERITY_LEVELS = {"error", "warning"}


class Finding(NamedTuple):
    """One unsuppressed Medium+ CodeQL SARIF result."""

    rule_id: str
    score: float | None
    level: str
    path: str
    line: int
    message: str


def iter_sarif_files(root: Path) -> list[Path]:
    """Return every ``*.sarif`` file under ``root``, sorted for stable output."""
    return sorted(root.rglob("*.sarif"))


def _rule_for_result(result: dict[str, Any], rules: list[Any]) -> dict[str, Any]:
    """Resolve the SARIF rule definition referenced by a result."""
    rules_by_id = {
        str(rule.get("id") or ""): rule for rule in rules if isinstance(rule, dict)
    }
    rule = rules_by_id.get(str(result.get("ruleId") or ""), {})
    if rule:
        return rule
    rule_index = result.get("ruleIndex")
    if isinstance(rule_index, int) and 0 <= rule_index < len(rules):
        candidate = rules[rule_index]
        if isinstance(candidate, dict):
            return candidate
    return {}


def _is_medium_plus(score: float | None, level: str, security_rule: bool) -> bool:
    """A result gates the PR if it scores >=4.0, or is an unscored security finding."""
    if score is not None:
        return score >= MEDIUM_PLUS_SCORE
    return security_rule and level in SEVERITY_LEVELS


def _finding_from_result(result: dict[str, Any], rules: list[Any]) -> Finding | None:
    """Build a `Finding` for one SARIF result, or None if it doesn't gate the PR."""
    if not isinstance(result, dict) or result.get("suppressions"):
        return None
    rule = _rule_for_result(result, rules)
    result_properties = result.get("properties") or {}
    rule_properties = rule.get("properties") or {}
    raw_score = result_properties.get("security-severity", rule_properties.get("security-severity"))
    try:
        score = float(raw_score)
    except (TypeError, ValueError):
        score = None
    level = str(result.get("level") or (rule.get("defaultConfiguration") or {}).get("level") or "none").lower()
    tags = {str(tag).lower() for tag in rule_properties.get("tags") or []}
    security_rule = "security" in tags or any(tag.startswith("external/cwe/") for tag in tags)
    if not _is_medium_plus(score, level, security_rule):
        return None
    physical = ((result.get("locations") or [{}])[0].get("physicalLocation") or {})
    artifact = (physical.get("artifactLocation") or {}).get("uri") or "unknown"
    line = (physical.get("region") or {}).get("startLine") or 0
    message = str((result.get("message") or {}).get("text") or "no message").replace("\n", " ")
    return Finding(
        rule_id=str(result.get("ruleId") or rule.get("id") or "unknown"),
        score=score,
        level=level,
        path=artifact,
        line=line,
        message=message,
    )


def gather_findings(root: Path) -> tuple[list[Finding], int, int]:
    """Scan every SARIF file under `root`; return (findings, total_results, file_count)."""
    paths = iter_sarif_files(root)
    findings: list[Finding] = []
    total_results = 0
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        for run in payload.get("runs") or []:
            rules = ((run.get("tool") or {}).get("driver") or {}).get("rules") or []
            for result in run.get("results") or []:
                if not isinstance(result, dict):
                    continue
                total_results += 1
                finding = _finding_from_result(result, rules)
                if finding is not None:
                    findings.append(finding)
    return findings, total_results, len(paths)


def format_finding(finding: Finding) -> str:
    """Render one finding as a single grep-able log line."""
    severity = f"security-severity={finding.score:g}" if finding.score is not None else f"level={finding.level}"
    return f"CODEQL_FINDING rule={finding.rule_id} {severity} path={finding.path} line={finding.line} message={finding.message}"


def main(argv: list[str] | None = None) -> int:
    """Gate on a directory of CodeQL SARIF output; print evidence and fail closed."""
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        raise SystemExit("usage: codeql_sarif_gate.py SARIF_DIR")

    root = Path(args[0])
    findings, total_results, file_count = gather_findings(root)
    if file_count == 0:
        raise SystemExit(f"CodeQL produced no SARIF under {root}; inspect the analysis log above.")

    print(f"CODEQL_SARIF files={file_count} results={total_results} medium_plus={len(findings)}")
    for finding in findings:
        print(format_finding(finding))
    if findings:
        raise SystemExit(f"CodeQL found {len(findings)} unsuppressed Medium+ security result(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
